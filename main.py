import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bot import initialize_bot, shutdown_bot
from app.config import settings
from app.routes import router
from app.utils import ensure_directories

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    settings.validate_required()
    await initialize_bot()
    logger.info("Application started and Telegram webhook configured.")
    yield
    await shutdown_bot()


app = FastAPI(title="TikTok Video Bot", version="1.0.0", lifespan=lifespan)
app.include_router(router)
