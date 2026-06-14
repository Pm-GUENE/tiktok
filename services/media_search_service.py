import logging
import time
from urllib.parse import urlencode

import requests

from app.config import settings

logger = logging.getLogger(__name__)

PEXELS_API_URL = "https://api.pexels.com"
PIXABAY_API_URL = "https://pixabay.com/api"
TIMEOUT = (5, 20)


class MediaSearchClient:
    def __init__(self) -> None:
        self.cache: dict[tuple[str, str, str, int], list[dict]] = {}

    def search_scene_candidates(self, scene: dict) -> list[dict]:
        candidates: list[dict] = []
        for query in scene.get("search_queries", [])[:3]:
            candidates.extend(self.search_provider("pexels", "photo", query))
            candidates.extend(self.search_provider("pixabay", "photo", query))
            if len(candidates) >= 8:
                break
        return candidates

    def search_provider(self, provider: str, media_type: str, query: str, per_page: int = 8) -> list[dict]:
        key = (provider, media_type, query.lower().strip(), per_page)
        if key in self.cache:
            return self.cache[key]
        if media_type != "photo":
            results = []
        elif provider == "pexels":
            results = search_pexels_photos(query, per_page)
        else:
            results = search_pixabay_images(query, per_page)
        self.cache[key] = results
        return results


def search_pexels_photos(query: str, per_page: int = 8) -> list[dict]:
    if not settings.PEXELS_API_KEY:
        return []
    url = f"{PEXELS_API_URL}/v1/search"
    data = _request_json(url, headers={"Authorization": settings.PEXELS_API_KEY}, params={"query": query, "per_page": per_page})
    results = []
    for item in data.get("photos", []) if isinstance(data, dict) else []:
        src = item.get("src") or {}
        results.append(
            {
                "provider": "pexels",
                "media_type": "photo",
                "id": str(item.get("id")),
                "download_url": src.get("large2x") or src.get("large") or src.get("original"),
                "preview_url": src.get("medium"),
                "width": int(item.get("width") or 0),
                "height": int(item.get("height") or 0),
                "duration": 0.0,
                "file_size": 0,
                "photographer": item.get("photographer", ""),
                "source_url": item.get("url", ""),
                "query_used": query,
            }
        )
    return [item for item in results if item.get("download_url")]


def search_pixabay_images(query: str, per_page: int = 8) -> list[dict]:
    if not settings.PIXABAY_API_KEY:
        return []
    params = {
        "key": settings.PIXABAY_API_KEY,
        "q": query,
        "per_page": per_page,
        "image_type": "photo",
        "safesearch": "true",
    }
    data = _request_json(f"{PIXABAY_API_URL}/", params=params)
    results = []
    for item in data.get("hits", []) if isinstance(data, dict) else []:
        results.append(
            {
                "provider": "pixabay",
                "media_type": "photo",
                "id": str(item.get("id")),
                "download_url": item.get("largeImageURL") or item.get("webformatURL"),
                "preview_url": item.get("previewURL", ""),
                "width": int(item.get("imageWidth") or 0),
                "height": int(item.get("imageHeight") or 0),
                "duration": 0.0,
                "file_size": int(item.get("imageSize") or 0),
                "photographer": item.get("user", ""),
                "source_url": item.get("pageURL", ""),
                "query_used": query,
            }
        )
    return [item for item in results if item.get("download_url")]


def _request_json(url: str, headers: dict | None = None, params: dict | None = None, retries: int = 2) -> dict:
    safe_url = f"{url}?{urlencode({k: v for k, v in (params or {}).items() if k != 'key'})}"
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
            if response.status_code in {401, 403}:
                logger.warning("Media provider rejected credentials for %s", url)
                return {}
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                logger.warning("Media provider temporary failure for %s: HTTP %s", safe_url, response.status_code)
                return {}
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            logger.warning("Media search failed for %s: %s", safe_url, exc)
    return {}
