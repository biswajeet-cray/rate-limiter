from fastapi import APIRouter, HTTPException, Request

from models.requests import RuleCreate
from models.responses import DeleteResponse, RuleResponse

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


@router.post("", response_model=RuleResponse, status_code=201)
async def create_rule(body: RuleCreate, request: Request) -> RuleResponse:
    """Create or update a rate limit rule."""
    service = request.app.state.service
    return service.add_rule(body)


@router.get("", response_model=list[RuleResponse])
async def list_rules(request: Request) -> list[RuleResponse]:
    """List all rate limit rules."""
    service = request.app.state.service
    return service.get_rules()


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(rule_id: str, request: Request) -> RuleResponse:
    """Get a specific rule by ID."""
    service = request.app.state.service
    rule = service.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return rule


@router.delete("/{rule_id}", response_model=DeleteResponse)
async def delete_rule(rule_id: str, request: Request) -> DeleteResponse:
    """Delete a rate limit rule."""
    service = request.app.state.service
    deleted = service.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return DeleteResponse(deleted=True, rule_id=rule_id)
