from fastapi import APIRouter, HTTPException, Request

from models.requests import CheckRequest
from models.responses import CheckResponse, StatusResponse
from services.rate_limiter_service import RuleNotFoundError

router = APIRouter(prefix="/api/v1", tags=["rate-limit"])


@router.post("/check", response_model=CheckResponse)
async def check_rate_limit(body: CheckRequest, request: Request) -> CheckResponse:
    """Check if a request is allowed under the specified rule."""
    service = request.app.state.service
    try:
        return await service.check(body.key, body.rule_id)
    except RuleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/status/{key}", response_model=StatusResponse)
async def get_status(key: str, rule_id: str, request: Request) -> StatusResponse:
    """Get rate limit status for a key under a specific rule.

    Note: this consumes a token — same as /check but returns more detail.
    For a true "peek" without consuming, we'd need a separate storage read.
    """
    service = request.app.state.service
    try:
        return await service.status(key, rule_id)
    except RuleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
