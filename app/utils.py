import logging
import re
import shutil
import uuid
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def ensure_directories() -> None:
    for directory in [
        settings.IMAGE_DIR,
        settings.MEDIA_DIR,
        settings.AUDIO_DIR,
        settings.OVERLAY_OUTPUT_DIR,
        settings.VIDEO_DIR,
        settings.MUSIC_DIR,
        settings.FONTS_DIR,
        settings.BACKGROUNDS_DIR,
        settings.OVERLAYS_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def unique_file_path(directory: Path, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{uuid.uuid4().hex}{suffix}"


def extract_topic(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^\s*sujet\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())[: settings.MAX_TOPIC_LENGTH]


def is_topic_too_long(text: str) -> bool:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^\s*sujet\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    return len(cleaned) > settings.MAX_TOPIC_LENGTH


def find_background_music() -> str | None:
    music_path = settings.MUSIC_DIR / "background.mp3"
    return str(music_path) if music_path.exists() else None


def cleanup_old_outputs(max_files_per_dir: int = 80) -> None:
    for directory in [settings.IMAGE_DIR, settings.MEDIA_DIR, settings.AUDIO_DIR, settings.OVERLAY_OUTPUT_DIR, settings.VIDEO_DIR]:
        if not directory.exists():
            continue
        files = sorted(
            [path for path in directory.iterdir() if path.is_file() and path.name != ".gitkeep"],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_file in files[max_files_per_dir:]:
            try:
                old_file.unlink()
            except OSError:
                logger.warning("Could not delete old output file: %s", old_file)


def copy_or_none(source: str | None, destination: Path) -> str | None:
    if not source:
        return None
    src = Path(source)
    if not src.exists():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, destination)
    return str(destination)
