from enum import Enum

from pydantic import BaseModel, Field


class Algorithm(str, Enum):
    """Supported rate limiting algorithms."""

    TOKEN_BUCKET = "token_bucket"
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"


class CheckRequest(BaseModel):
    """Request to check if a key is rate limited."""

    key: str = Field(..., min_length=1, max_length=256, examples=["user:123"])
    rule_id: str = Field(..., min_length=1, max_length=256, examples=["api_default"])


class RuleCreate(BaseModel):
    """Request to create a rate limit rule."""

    rule_id: str = Field(..., min_length=1, max_length=256, examples=["api_default"])
    algorithm: Algorithm = Field(..., examples=["token_bucket"])
    max_requests: int = Field(..., gt=0, le=100_000, examples=[100])
    window_seconds: int = Field(..., gt=0, le=86_400, examples=[60])
    # Token bucket only — tokens refilled per second (defaults to max_requests/window_seconds)
    refill_rate: float | None = Field(default=None, gt=0, examples=[1.67])
