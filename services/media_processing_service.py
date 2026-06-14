import logging
import shutil
import uuid
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.config import settings

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_BYTES = 45 * 1024 * 1024
REQUEST_TIMEOUT = (5, 45)


def prepare_selected_media(selected_media: list[dict], job_id: str) -> list[dict]:
    job_dir = settings.MEDIA_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    prepared = []
    previous_path: str | None = None

    for index, item in enumerate(selected_media, start=1):
        scene = item.get("scene") or {}
        try:
            if item.get("media_type") == "photo" and item.get("download_url"):
                path = _download_file(item["download_url"], job_dir, ".jpg")
                prepared_path = _prepare_photo(path, job_dir / f"scene_{index:02d}.jpg")
                _safe_unlink(path)
                previous_path = str(prepared_path)
                prepared.append({**item, "prepared_path": str(prepared_path), "prepared_type": "photo"})
            elif item.get("media_type") == "video" and item.get("download_url"):
                suffix = ".mp4"
                path = _download_file(item["download_url"], job_dir, suffix)
                previous_path = str(path)
                prepared.append({**item, "prepared_path": str(path), "prepared_type": "video"})
            elif previous_path:
                prepared.append({**item, "prepared_path": previous_path, "prepared_type": _type_from_path(previous_path), "reuse": True})
            else:
                prepared_path = create_fallback_visual(scene.get("subtitle") or f"Scène {index}", job_dir / f"scene_{index:02d}_fallback.jpg", index)
                previous_path = str(prepared_path)
                prepared.append({**item, "prepared_path": str(prepared_path), "prepared_type": "photo"})
        except Exception:
            logger.exception("Media preparation failed for scene %s. Using fallback.", index)
            prepared_path = create_fallback_visual(scene.get("subtitle") or f"Scène {index}", job_dir / f"scene_{index:02d}_fallback.jpg", index)
            previous_path = str(prepared_path)
            prepared.append({**item, "prepared_path": str(prepared_path), "prepared_type": "photo"})

    return prepared


def cleanup_job_files(paths: list[str | None]) -> None:
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        try:
            if path.is_dir() and path.is_relative_to(settings.OUTPUT_DIR):
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file() and path.is_relative_to(settings.OUTPUT_DIR):
                path.unlink(missing_ok=True)
        except Exception:
            logger.debug("Could not cleanup %s", path, exc_info=True)


def create_fallback_visual(text: str, output_path: Path, scene_number: int) -> Path:
    width, height = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT
    palette = [
        ((17, 84, 112), (244, 179, 64)),
        ((31, 98, 72), (236, 96, 80)),
        ((54, 58, 98), (88, 178, 170)),
    ]
    start, end = palette[scene_number % len(palette)]
    image = Image.new("RGB", (width, height), start)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / height
        color = tuple(int(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    font = _load_font(max(42, int(width * 0.075)))
    lines = _wrap_text(text, font, width - 120)
    line_height = int(width * 0.1)
    block_height = line_height * len(lines) + 70
    top = (height - block_height) // 2
    draw.rounded_rectangle([50, top - 30, width - 50, top + block_height], radius=32, fill=(0, 0, 0, 125))
    y = top
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_height
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "JPEG", quality=88, optimize=True)
    return output_path


def _download_file(url: str, directory: Path, suffix: str) -> Path:
    path = directory / f"{uuid.uuid4().hex}{suffix}"
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if suffix == ".mp4" and "video" not in content_type and "octet-stream" not in content_type:
            raise RuntimeError(f"Unexpected video content type: {content_type}")
        if suffix == ".jpg" and "image" not in content_type and "octet-stream" not in content_type:
            raise RuntimeError(f"Unexpected image content type: {content_type}")
        total = 0
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("Downloaded media is too large.")
                handle.write(chunk)
    return path


def _prepare_photo(source: Path, destination: Path) -> Path:
    image = Image.open(source).convert("RGB")
    image = ImageOps.exif_transpose(image)
    image = _resize_crop(image, settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, "JPEG", quality=88, optimize=True)
    return destination


def _resize_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    source_ratio = image.width / image.height
    target_ratio = width / height
    if source_ratio > target_ratio:
        new_height = height
        new_width = int(height * source_ratio)
    else:
        new_width = width
        new_height = int(width / source_ratio)
    resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    left = (new_width - width) // 2
    top = (new_height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _load_font(size: int):
    font_path = settings.FONTS_DIR / "font.ttf"
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size=size)
    for font_name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:4]


def _type_from_path(path: str) -> str:
    return "video" if Path(path).suffix.lower() in {".mp4", ".mov", ".m4v"} else "photo"


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
