import json
import logging
import re
from threading import Lock
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from services.rate_limiter import gemini_rate_limiter

logger = logging.getLogger(__name__)

TEXT_MODEL = "gemini-2.5-flash"
_GEMINI_CLIENT: genai.Client | None = None
_CLIENT_LOCK = Lock()


def _client() -> genai.Client:
    global _GEMINI_CLIENT
    settings.validate_required()
    with _CLIENT_LOCK:
        if _GEMINI_CLIENT is None:
            _GEMINI_CLIENT = genai.Client(api_key=settings.GEMINI_API_KEY)
        return _GEMINI_CLIENT


def _reset_client() -> None:
    global _GEMINI_CLIENT
    with _CLIENT_LOCK:
        client = _GEMINI_CLIENT
        _GEMINI_CLIENT = None
    if client and hasattr(client, "close"):
        try:
            client.close()
        except Exception:
            logger.debug("Gemini client close failed during reset.", exc_info=True)


def _generate_content(model: str, contents: str, config: types.GenerateContentConfig):
    for attempt in range(2):
        try:
            return _client().models.generate_content(model=model, contents=contents, config=config)
        except RuntimeError as exc:
            if "client has been closed" in str(exc).lower() and attempt == 0:
                logger.warning("Gemini client was closed; resetting client and retrying once.")
                _reset_client()
                continue
            raise


def generate_video_plan(topic: str) -> dict:
    prompt = f"""
Tu es un scénariste TikTok et directeur artistique pour une audience sénégalaise francophone.

Retourne uniquement un JSON valide, sans markdown, sans commentaire.

Sujet: {topic}

Schéma strict:
{{
  "title": "string",
  "hook": "string",
  "script": "string",
  "hashtags": ["string"],
  "target_duration_seconds": 62,
  "visual_profile": {{
    "style": "realistic documentary",
    "main_subject": "string",
    "environment": "string",
    "lighting": "string",
    "mood": "string",
    "dominant_topic": "string",
  "preferred_media_type": "photo"
  }},
  "scenes": [
    {{
      "scene_number": 1,
      "voice_segment": "string",
      "subtitle": "string",
      "duration_seconds": 3.4,
      "preferred_media_type": "photo",
      "subject": "string",
      "shot_type": "string",
      "action": "string",
      "environment": "string",
      "search_queries": ["string", "string", "string"],
      "negative_keywords": ["logo", "text overlay", "animation"]
    }}
  ]
}}

Contraintes:
- Script en français simple, naturel et utile pour le Sénégal.
- Première phrase = hook fort.
- Durée cible: 62 secondes, acceptable 58 à 66 secondes.
- 18 scènes par défaut, toujours entre 15 et 20.
- Une direction visuelle stable pour toute la vidéo.
- Chaque scène décrit un moment visuel clair.
- Chaque scène a 3 requêtes de recherche en anglais: précise, africaine plus large, générique pertinente.
- Préfère des photos réalistes, documentaires, verticales si possible.
- Recherche d'abord contexte sénégalais, puis africain, puis générique.
- Évite marques, logos, célébrités, personnages protégés, politique, texte visible.
- Pas de fausses statistiques, pas de conseils médicaux/légaux/financiers risqués.
"""

    def request() -> dict:
        response = _generate_content(
            model=TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return _parse_video_plan(getattr(response, "text", "") or "", topic)

    try:
        return gemini_rate_limiter.call(request, fallback=lambda exc=None: fallback_video_plan(topic))
    except Exception:
        logger.exception("Gemini video plan generation failed. Using fallback plan.")
        return fallback_video_plan(topic)


def _parse_video_plan(text: str, topic: str) -> dict:
    text = _strip_markdown(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        json_text = _extract_json_object(text)
        if not json_text:
            raise
        data = json.loads(json_text)

    if not isinstance(data, dict):
        raise ValueError("Gemini response is not a JSON object.")
    return _normalize_plan(data, topic)


def _strip_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


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


def _normalize_plan(data: dict, topic: str) -> dict:
    fallback = fallback_video_plan(topic)
    title = str(data.get("title") or fallback["title"]).strip()[:90]
    hook = str(data.get("hook") or fallback["hook"]).strip()[:180]
    script = str(data.get("script") or fallback["script"]).strip() or fallback["script"]
    hashtags = data.get("hashtags") if isinstance(data.get("hashtags"), list) else fallback["hashtags"]
    hashtags = [str(tag).strip() for tag in hashtags if str(tag).strip()][:6] or fallback["hashtags"]
    visual_profile = data.get("visual_profile") if isinstance(data.get("visual_profile"), dict) else fallback["visual_profile"]
    scenes = _normalize_scenes(data.get("scenes") or [], topic, visual_profile)
    return {
        "title": title,
        "hook": hook,
        "script": script,
        "hashtags": hashtags,
        "target_duration_seconds": 62,
        "visual_profile": visual_profile,
        "scenes": scenes,
    }


def _normalize_scenes(scenes: list, topic: str, visual_profile: dict) -> list[dict]:
    clean = []
    for index, scene in enumerate(scenes[:20], start=1):
        if not isinstance(scene, dict):
            continue
        queries = scene.get("search_queries") if isinstance(scene.get("search_queries"), list) else []
        queries = [str(query).strip() for query in queries if str(query).strip()][:3]
        while len(queries) < 3:
            queries.append(_default_query(topic, visual_profile, len(queries)))
        clean.append(
            {
                "scene_number": index,
                "voice_segment": str(scene.get("voice_segment") or "").strip(),
                "subtitle": str(scene.get("subtitle") or f"Conseil {index}").strip()[:90],
                "duration_seconds": _safe_duration(scene.get("duration_seconds")),
                "preferred_media_type": _media_type(scene.get("preferred_media_type")),
                "subject": str(scene.get("subject") or visual_profile.get("main_subject") or topic).strip(),
                "shot_type": str(scene.get("shot_type") or "medium shot").strip(),
                "action": str(scene.get("action") or "practical demonstration").strip(),
                "environment": str(scene.get("environment") or visual_profile.get("environment") or "Senegal").strip(),
                "search_queries": queries,
                "negative_keywords": _negative_keywords(scene.get("negative_keywords")),
            }
        )
    if len(clean) < 15:
        fallback = fallback_video_plan(topic)
        clean.extend(fallback["scenes"][len(clean) :])
    return clean[:20]


def _safe_duration(value: Any) -> float:
    try:
        return max(2.5, min(float(value or 3.5), 5.0))
    except (TypeError, ValueError):
        return 3.5


def _media_type(value: Any) -> str:
    return "photo"


def _negative_keywords(value: Any) -> list[str]:
    defaults = ["logo", "text overlay", "animation", "cartoon", "celebrity"]
    if not isinstance(value, list):
        return defaults
    merged = [str(item).strip().lower() for item in value if str(item).strip()]
    return list(dict.fromkeys(merged + defaults))[:8]


def _default_query(topic: str, visual_profile: dict, level: int) -> str:
    subject = visual_profile.get("main_subject", "African person")
    environment = visual_profile.get("environment", "urban Senegal")
    if level == 0:
        return f"{subject} {topic} {environment}"
    if level == 1:
        return f"African person practical advice {topic}"
    return f"realistic documentary {topic}"


def fallback_video_plan(topic: str) -> dict:
    visual_profile = {
        "style": "realistic documentary",
        "main_subject": "young African adult",
        "environment": "urban Senegal and practical everyday settings",
        "lighting": "warm natural light",
        "mood": "useful, trustworthy and practical",
        "dominant_topic": topic,
        "preferred_media_type": "photo",
    }
    script = (
        f"Avant de te lancer sur {topic}, prends une minute pour éviter les erreurs. "
        "Commence par clarifier ton besoin réel, puis compare plusieurs options. "
        "Regarde les détails visibles, pose des questions simples et ne te laisse pas presser. "
        "Au Sénégal, le bon choix vient souvent d'une vérification calme et directe. "
        "Demande une preuve quand c'est possible, teste ce qui peut être testé, et garde une trace. "
        "Si une offre semble trop belle, prends du recul. "
        "L'objectif, c'est de choisir quelque chose qui respecte ton budget et te laisse tranquille après. "
        "Garde cette vidéo et partage-la avec quelqu'un qui en a besoin."
    )
    subtitles = [
        "Clarifie ton besoin",
        "Compare plusieurs options",
        "Vérifie les détails",
        "Pose des questions simples",
        "Ne paie pas sous pression",
        "Demande une preuve",
        "Teste avant de décider",
        "Observe l'environnement",
        "Regarde les frais cachés",
        "Prends ton temps",
        "Évite les promesses faciles",
        "Demande conseil",
        "Protège ton budget",
        "Garde une trace",
        "Choisis le plus fiable",
        "Pense au long terme",
        "Reste prudent",
        "Partage ce conseil",
    ]
    scenes = []
    for index, subtitle in enumerate(subtitles, start=1):
        scenes.append(
            {
                "scene_number": index,
                "voice_segment": subtitle,
                "subtitle": subtitle,
                "duration_seconds": 3.4,
                "preferred_media_type": "photo",
                "subject": "young African adult making a practical decision",
                "shot_type": "medium shot" if index % 2 else "close up",
                "action": "checking details and comparing options",
                "environment": "urban Senegal, shop, desk or everyday street setting",
                "search_queries": [
                    f"African person practical advice {topic}",
                    f"young African adult checking details {topic}",
                    f"realistic documentary everyday decision {topic}",
                ],
                "negative_keywords": ["logo", "text overlay", "animation", "cartoon", "celebrity"],
            }
        )
    return {
        "title": f"Conseil pratique : {topic[:55]}",
        "hook": f"Avant de te lancer sur {topic}, regarde ça.",
        "script": script,
        "hashtags": ["#Senegal", "#Conseils", "#TikTokSenegal"],
        "target_duration_seconds": 62,
        "visual_profile": visual_profile,
        "scenes": scenes,
    }
