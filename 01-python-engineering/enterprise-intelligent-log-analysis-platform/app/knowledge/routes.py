from fastapi import APIRouter, Query

from app.knowledge.magento import KNOWN_ISSUES, match_issues

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("")
async def list_issues() -> dict:
    return {"items": [issue.to_dict() for issue in KNOWN_ISSUES]}


@router.get("/match")
async def match(text: str = Query(min_length=1, max_length=20000)) -> dict:
    return {"items": [issue.to_dict() for issue in match_issues(text)]}
