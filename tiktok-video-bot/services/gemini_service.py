import asyncio
import base64
import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.utils import unique_file_path
from services.rate_limiter import gemini_rate_limiter

logger = logging.getLogger(__name__)

TEXT_MODEL = "gemini-2.5-flash"
IMAGE_MODEL = "gemini-3.1-flash-image"


def _client() -> genai.Client:
    settings.validate_required()
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def generate_video_plan(topic: str) -> dict:
    prompt = f"""
Tu es un scénariste TikTok francophone spécialisé dans les contenus utiles pour le Sénégal.

Retourne uniquement un JSON valide, sans markdown, sans explication.

Sujet: {topic}

Schéma JSON strict:
{{
  "title": "string",
  "hook": "string",
  "script": "string",
  "hashtags": ["string"],
  "target_duration_seconds": 62,
  "scenes": [
    {{
      "scene_number": 1,
      "subtitle": "string",
      "image_prompt": "string",
      "duration_seconds": 3.5
    }}
  ]
}}

Contraintes:
- Langue du script: français simple, naturel, adapté au public sénégalais.
- Ton: utile, direct, naturel, professionnel.
- Durée cible: environ 62 secondes, acceptable entre 58 et 66 secondes.
- Le script doit être prêt pour une voix off TikTok d'environ 62 secondes.
- La première phrase doit être un hook fort dans les 3 premières secondes.
- Évite les fausses statistiques, la politique, les promesses médicales, légales ou financières risquées.
- Crée 18 scènes par défaut, entre 15 et 20 scènes seulement.
- Chaque scène a un sous-titre court en français.
- Chaque scène dure environ 3 à 4 secondes.
- Chaque image_prompt est en anglais.
- Les prompts demandent une image réaliste verticale 9:16, style TikTok moderne.
- Ajoute un contexte sénégalais quand c'est pertinent.
- Aucun texte dans les images, aucun logo, aucune marque, aucune célébrité, aucun personnage protégé, aucun contenu politique.
- Hashtags: 3 à 6 hashtags pertinents, en incluant si utile #Senegal ou #TikTokSenegal.
"""

    def request() -> dict:
        response = _client().models.generate_content(
            model=TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        text = getattr(response, "text", "") or ""
        return _parse_video_plan(text, topic)

    try:
        return gemini_rate_limiter.call(request, fallback=lambda: fallback_video_plan(topic))
    except Exception:
        logger.exception("Gemini video plan generation failed. Using fallback plan.")
        return fallback_video_plan(topic)


async def generate_scene_images(video_plan: dict, output_dir: str, progress_callback=None) -> list[str]:
    scenes = _normalize_scenes(video_plan.get("scenes") or [], video_plan.get("title", "Conseil TikTok"))
    total = len(scenes)
    image_paths: list[str] = []

    for index, scene in enumerate(scenes, start=1):
        if progress_callback:
            await progress_callback(index, total)

        output_path = unique_file_path(Path(output_dir), ".jpg")
        subtitle = scene.get("subtitle") or f"Scène {index}"
        prompt = _sanitize_image_prompt(scene.get("image_prompt") or "", video_plan.get("title", ""))

        def fallback() -> str:
            return create_fallback_image(subtitle, str(output_path), index)

        def request() -> str:
            return _generate_single_image(prompt, str(output_path), subtitle, index)

        image_path = await asyncio.to_thread(gemini_rate_limiter.call, request, fallback)
        image_paths.append(image_path)

    return image_paths


def _generate_single_image(prompt: str, output_path: str, subtitle: str, scene_number: int) -> str:
    try:
        response = _client().models.generate_content(
            model=IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )
        image_bytes = _extract_image_bytes(response)
        if not image_bytes:
            logger.warning("Gemini returned no image for scene %s. Using fallback.", scene_number)
            return create_fallback_image(subtitle, output_path, scene_number)

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        image = _resize_crop(image, settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT)
        image.save(output_path, "JPEG", quality=88, optimize=True)
        return output_path
    except Exception as exc:
        if gemini_rate_limiter._is_rate_limit_error(exc):
            raise
        logger.exception("Image generation failed for scene %s. Using fallback.", scene_number)
        return create_fallback_image(subtitle, output_path, scene_number)


def _extract_image_bytes(response: Any) -> bytes | None:
    for part in getattr(response, "parts", None) or []:
        if hasattr(part, "as_image"):
            image = part.as_image()
            if image:
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()
        inline_data = getattr(part, "inline_data", None)
        if inline_data and getattr(inline_data, "data", None):
            data = inline_data.data
            if isinstance(data, bytes):
                return data
            return base64.b64decode(data)

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        for part in parts:
            if hasattr(part, "as_image"):
                image = part.as_image()
                if image:
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    return buffer.getvalue()
            inline_data = getattr(part, "inline_data", None)
            if inline_data and getattr(inline_data, "data", None):
                data = inline_data.data
                if isinstance(data, bytes):
                    return data
                return base64.b64decode(data)
    return None


def _parse_video_plan(text: str, topic: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        json_text = _extract_json_object(text)
        if not json_text:
            raise
        data = json.loads(json_text)

    if not isinstance(data, dict):
        raise ValueError("Gemini response is not a JSON object.")

    plan = _normalize_plan(data, topic)
    return plan


def _normalize_plan(data: dict, topic: str) -> dict:
    fallback = fallback_video_plan(topic)
    title = str(data.get("title") or fallback["title"])[:90]
    hook = str(data.get("hook") or fallback["hook"])[:180]
    script = str(data.get("script") or fallback["script"]).strip()
    hashtags = data.get("hashtags") if isinstance(data.get("hashtags"), list) else fallback["hashtags"]
    hashtags = [str(tag).strip() for tag in hashtags if str(tag).strip()][:6] or fallback["hashtags"]
    scenes = _normalize_scenes(data.get("scenes") or [], title)

    if not script:
        script = fallback["script"]

    return {
        "title": title,
        "hook": hook,
        "script": script,
        "hashtags": hashtags,
        "target_duration_seconds": 62,
        "scenes": scenes,
    }


def _normalize_scenes(scenes: list, title: str) -> list[dict]:
    clean_scenes = []
    for idx, scene in enumerate(scenes[:20], start=1):
        if not isinstance(scene, dict):
            continue
        subtitle = str(scene.get("subtitle") or f"Conseil {idx}").strip()[:80]
        prompt = str(scene.get("image_prompt") or "").strip()
        clean_scenes.append(
            {
                "scene_number": idx,
                "subtitle": subtitle,
                "image_prompt": _sanitize_image_prompt(prompt, title),
                "duration_seconds": _safe_scene_duration(scene.get("duration_seconds")),
            }
        )

    if len(clean_scenes) < 15:
        for idx in range(len(clean_scenes) + 1, 19):
            subtitle = f"Conseil utile {idx}"
            clean_scenes.append(
                {
                    "scene_number": idx,
                    "subtitle": subtitle,
                    "image_prompt": _sanitize_image_prompt("", title),
                    "duration_seconds": 3.5,
                }
            )
    return clean_scenes[:20]


def _safe_scene_duration(value: Any) -> float:
    try:
        duration = float(value or 3.5)
    except (TypeError, ValueError):
        return 3.5
    return max(2.5, min(duration, 5.0))


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _sanitize_image_prompt(prompt: str, title: str) -> str:
    base = prompt or f"Realistic modern TikTok-style scene in Senegal about {title}"
    safety = (
        " Vertical 9:16 realistic image, modern social media style, Senegalese context when relevant, "
        "natural lighting, no text, no logos, no brand names, no celebrity, no copyrighted character, no politics."
    )
    return f"{base.strip()}.{safety}"


def fallback_video_plan(topic: str) -> dict:
    title = f"Conseil pratique : {topic[:55]}"
    script = (
        f"Tu veux mieux comprendre {topic} ? Voici une méthode simple et utile pour éviter les erreurs. "
        "D'abord, clarifie ton besoin réel avant de décider. Ensuite, compare plusieurs options, pas seulement la première. "
        "Regarde l'état général, le prix, les frais cachés et la fiabilité de la personne ou du service. "
        "Au Sénégal, prends le temps de poser des questions simples et directes. Demande une preuve, teste ce qui peut être testé, "
        "et ne paie jamais sous pression. Si quelque chose semble trop beau pour être vrai, prends du recul. "
        "Parle aussi avec quelqu'un qui connaît le sujet, même rapidement, parce qu'un avis extérieur peut t'éviter une mauvaise surprise. "
        "Note les points importants dans ton téléphone avant de te déplacer, comme ça tu n'oublies rien au moment de vérifier. "
        "Le bon choix, c'est celui qui répond à ton besoin, respecte ton budget et te laisse tranquille après l'achat. "
        "Garde cette vidéo et partage-la avec quelqu'un qui en a besoin."
    )
    subtitles = [
        "Clarifie ton besoin",
        "Compare plusieurs options",
        "Vérifie l'état général",
        "Regarde les frais cachés",
        "Pose des questions directes",
        "Demande des preuves",
        "Teste avant de payer",
        "Évite la pression",
        "Prends ton temps",
        "Protège ton budget",
        "Choisis le plus fiable",
        "Vérifie les détails",
        "Demande conseil",
        "Reste prudent",
        "Pense au long terme",
        "Évite les promesses faciles",
        "Garde une trace",
        "Partage ce conseil",
    ]
    scenes = [
        {
            "scene_number": index,
            "subtitle": subtitle,
            "image_prompt": _sanitize_image_prompt(
                f"Realistic vertical photo in Dakar, Senegal, showing everyday people making a smart practical decision about {topic}",
                title,
            ),
            "duration_seconds": 3.5,
        }
        for index, subtitle in enumerate(subtitles, start=1)
    ]
    return {
        "title": title,
        "hook": f"Avant de te lancer sur {topic}, regarde ça.",
        "script": script,
        "hashtags": ["#Senegal", "#Conseils", "#TikTokSenegal"],
        "target_duration_seconds": 62,
        "scenes": scenes,
    }


def create_fallback_image(subtitle: str, output_path: str, scene_number: int) -> str:
    width, height = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT
    palette = [
        ((22, 92, 125), (245, 184, 65)),
        ((26, 106, 82), (237, 94, 83)),
        ((70, 62, 118), (246, 200, 92)),
        ((35, 48, 68), (67, 160, 160)),
    ]
    start, end = palette[scene_number % len(palette)]
    image = Image.new("RGB", (width, height), start)
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / height
        color = tuple(int(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)

    for offset in range(0, width, 180):
        draw.ellipse(
            [offset - 240, 240 + (scene_number * 37) % 420, offset + 160, 680 + (scene_number * 37) % 420],
            outline=(255, 255, 255, 45),
            width=5,
        )

    font = _load_font(68)
    small_font = _load_font(34)
    lines = _wrap_text(subtitle, font, width - 180)
    line_height = 86
    block_height = line_height * len(lines) + 80
    top = (height - block_height) // 2
    box = [80, top - 45, width - 80, top + block_height - 20]
    draw.rounded_rectangle(box, radius=42, fill=(0, 0, 0, 115))

    y = top
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_height

    badge = f"Scene {scene_number}"
    draw.rounded_rectangle([80, 120, 260, 178], radius=24, fill=(255, 255, 255, 210))
    draw.text((105, 131), badge, font=small_font, fill=(24, 24, 24))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "JPEG", quality=90, optimize=True)
    return output_path


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


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = settings.FONTS_DIR / "font.ttf"
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size=size)
    for font_name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    dummy = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy)
    for word in words:
        candidate = f"{current} {word}".strip()
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:5]
