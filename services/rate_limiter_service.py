from algorithms.fixed_window import FixedWindow
from algorithms.sliding_window import SlidingWindow
from algorithms.token_bucket import TokenBucket
from models.requests import Algorithm, RuleCreate
from models.responses import CheckResponse, RuleResponse, StatusResponse
from storage.base import StorageBackend


class RateLimiterService:
    """Orchestrates algorithm selection, rule management, and rate limit checks.

    Like a .NET service registered in DI — owns the business logic and
    delegates to the appropriate algorithm based on each rule's config.

    When the backend is Redis, uses atomic Lua scripts instead of the
    Python algorithm classes — eliminates race conditions in distributed
    deployments.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage
        self._rules: dict[str, RuleCreate] = {}

    def add_rule(self, rule: RuleCreate) -> RuleResponse:
        self._rules[rule.rule_id] = rule
        return self._rule_to_response(rule)

    def get_rules(self) -> list[RuleResponse]:
        return [self._rule_to_response(r) for r in self._rules.values()]

    def get_rule(self, rule_id: str) -> RuleResponse | None:
        rule = self._rules.get(rule_id)
        return self._rule_to_response(rule) if rule else None

    def delete_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    async def check(self, key: str, rule_id: str) -> CheckResponse:
        rule = self._rules.get(rule_id)
        if rule is None:
            raise RuleNotFoundError(rule_id)

        storage_key = f"{rule_id}:{key}"

        # Use atomic Lua scripts for Redis, Python algorithms for memory
        if hasattr(self.storage, "atomic_token_bucket"):
            return await self._check_atomic(rule, storage_key)
        return await self._check_algorithm(rule, storage_key)

    async def status(self, key: str, rule_id: str) -> StatusResponse:
        """Get status without consuming a token — performs a check and returns details."""
        check_result = await self.check(key, rule_id)
        return StatusResponse(
            key=key,
            rule_id=rule_id,
            allowed=check_result.allowed,
            remaining=check_result.remaining,
            retry_after=check_result.retry_after,
        )

    async def _check_atomic(self, rule: RuleCreate, storage_key: str) -> CheckResponse:
        """Redis path — atomic Lua scripts, no race conditions."""
        if rule.algorithm == Algorithm.TOKEN_BUCKET:
            refill_rate = rule.refill_rate or (rule.max_requests / rule.window_seconds)
            result = await self.storage.atomic_token_bucket(
                storage_key, rule.max_requests, refill_rate
            )
        elif rule.algorithm == Algorithm.FIXED_WINDOW:
            result = await self.storage.atomic_fixed_window(
                storage_key, rule.max_requests, rule.window_seconds
            )
        else:
            result = await self.storage.atomic_sliding_window(
                storage_key, rule.max_requests, rule.window_seconds
            )

        return CheckResponse(
            allowed=result["allowed"],
            remaining=int(result["remaining"]),
            retry_after=result["retry_after"],
        )

    async def _check_algorithm(self, rule: RuleCreate, storage_key: str) -> CheckResponse:
        """Memory path — Python algorithm classes."""
        algorithm = self._build_algorithm(rule)
        result = await algorithm.consume(storage_key)

        return CheckResponse(
            allowed=result.allowed,
            remaining=int(
                result.remaining_tokens
                if hasattr(result, "remaining_tokens")
                else result.remaining_requests
            ),
            retry_after=round(result.retry_after, 2) if result.retry_after else None,
        )

    def _build_algorithm(self, rule: RuleCreate) -> TokenBucket | FixedWindow | SlidingWindow:
        if rule.algorithm == Algorithm.TOKEN_BUCKET:
            refill_rate = rule.refill_rate or (rule.max_requests / rule.window_seconds)
            return TokenBucket(
                max_tokens=rule.max_requests,
                refill_rate=refill_rate,
                storage=self.storage,
            )
        elif rule.algorithm == Algorithm.FIXED_WINDOW:
            return FixedWindow(
                max_requests=rule.max_requests,
                window_seconds=rule.window_seconds,
                storage=self.storage,
            )
        else:
            return SlidingWindow(
                max_requests=rule.max_requests,
                window_seconds=rule.window_seconds,
                storage=self.storage,
            )

    @staticmethod
    def _rule_to_response(rule: RuleCreate) -> RuleResponse:
        return RuleResponse(
            rule_id=rule.rule_id,
            algorithm=rule.algorithm.value,
            max_requests=rule.max_requests,
            window_seconds=rule.window_seconds,
            refill_rate=rule.refill_rate,
        )


class RuleNotFoundError(Exception):
    def __init__(self, rule_id: str) -> None:
        self.rule_id = rule_id
        super().__init__(f"Rule '{rule_id}' not found")
