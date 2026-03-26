from pydantic import BaseModel


class CheckResponse(BaseModel):
    """Response from a rate limit check."""

    allowed: bool
    remaining: int
    retry_after: float | None = None


class StatusResponse(BaseModel):
    """Response from a rate limit status query."""

    key: str
    rule_id: str
    allowed: bool
    remaining: int
    retry_after: float | None = None


class RuleResponse(BaseModel):
    """Response representing a rate limit rule."""

    rule_id: str
    algorithm: str
    max_requests: int
    window_seconds: int
    refill_rate: float | None = None


class DeleteResponse(BaseModel):
    """Response from deleting a rule."""

    deleted: bool
    rule_id: str
