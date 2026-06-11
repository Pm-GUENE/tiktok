from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Settings:
    BASE_DIR = Path(__file__).resolve().parent.parent

    TELEGRAM_BOT_TOKEN: str | None = None
    GEMINI_API_KEY: str | None = None
    PUBLIC_URL: str | None = None

    OUTPUT_DIR = BASE_DIR / "output"
    IMAGE_DIR = OUTPUT_DIR / "images"
    AUDIO_DIR = OUTPUT_DIR / "audio"
    VIDEO_DIR = OUTPUT_DIR / "videos"
    ASSETS_DIR = BASE_DIR / "assets"
    MUSIC_DIR = ASSETS_DIR / "music"
    FONTS_DIR = ASSETS_DIR / "fonts"
    BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"

    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 24
    TARGET_DURATION_SECONDS = 62
    MAX_TOPIC_LENGTH = 250

    def __init__(self) -> None:
        import os

        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        self.PUBLIC_URL = os.getenv("PUBLIC_URL")

    @property
    def webhook_url(self) -> str:
        public_url = (self.PUBLIC_URL or "").rstrip("/")
        return f"{public_url}/webhook"

    def validate_required(self) -> None:
        missing = []
        if not self.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if not self.PUBLIC_URL:
            missing.append("PUBLIC_URL")
        if missing:
            raise RuntimeError(
                "Variables d'environnement manquantes: "
                + ", ".join(missing)
                + ". Configure-les sur Render ou dans un fichier .env local."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
