"""The live AI assistant used by the on-page chat."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..database import get_db
from ..ratelimit import rate_limit
from ..schemas import AssistantIn
from ..services import assistant as engine
from ..services.billing import plans_summary

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def get_llm_client() -> httpx.AsyncClient | None:
    """Override in tests to inject a mock transport. None means 'create one per request'."""
    return None


def _summary(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> str:
    return plans_summary(db, settings)


@router.post(
    "/message",
    dependencies=[Depends(rate_limit("assistant-min", 12, 60)), Depends(rate_limit("assistant-hour", 80, 3600))],
)
async def message(
    data: AssistantIn,
    settings: Settings = Depends(get_settings),
    summary: str = Depends(_summary),
    client: httpx.AsyncClient | None = Depends(get_llm_client),
):
    messages = [{"role": m.role, "content": m.content} for m in data.messages]
    result = await engine.answer(messages, settings, summary, client)
    return {"reply": result.reply, "source": result.source, "flagged": result.flagged, "chips": result.chips, "action": result.action}
