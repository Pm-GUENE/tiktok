import logging

from fastapi import APIRouter, Request
from telegram import Update

from app.bot import get_application

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "telegram_bot": "ready"}


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    payload = await request.json()
    application = get_application()
    update = Update.de_json(payload, application.bot)
    await application.process_update(update)
    return {"ok": True}
