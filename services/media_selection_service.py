import logging

logger = logging.getLogger(__name__)


def select_best_media_for_scenes(video_plan: dict, candidate_results: dict[int, list[dict]]) -> list[dict]:
    selected: list[dict] = []
    used_ids: set[tuple[str, str]] = set()
    contributor_counts: dict[str, int] = {}

    for scene in video_plan.get("scenes", []):
        scene_number = int(scene.get("scene_number") or len(selected) + 1)
        candidates = candidate_results.get(scene_number, [])
        scored = [
            (_score_candidate(candidate, scene, video_plan.get("visual_profile", {}), used_ids, contributor_counts), candidate)
            for candidate in candidates
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        chosen = scored[0][1] if scored and scored[0][0] > -50 else _reuse_previous(selected, scene)
        if chosen:
            media_id = (chosen.get("provider", ""), chosen.get("id", ""))
            used_ids.add(media_id)
            contributor = chosen.get("photographer") or ""
            contributor_counts[contributor] = contributor_counts.get(contributor, 0) + 1
            selected.append({**chosen, "scene": scene})
        else:
            selected.append({"media_type": "fallback", "scene": scene})

    return selected


def _score_candidate(candidate: dict, scene: dict, visual_profile: dict, used_ids: set, contributor_counts: dict) -> int:
    score = 0
    query = (candidate.get("query_used") or "").lower()
    subject = (scene.get("subject") or "").lower()
    environment = (scene.get("environment") or "").lower()
    visual_text = " ".join(
        [
            query,
            str(candidate.get("source_url") or "").lower(),
            str(candidate.get("photographer") or "").lower(),
        ]
    )

    score += 30 if any(word in query for word in _keywords(subject)) else 10
    score += 20 if _is_portrait(candidate) else -15
    score += 12 if candidate.get("media_type") == "photo" else -80
    score += min((int(candidate.get("width") or 0) * int(candidate.get("height") or 0)) // 120_000, 10)
    score += _profile_score(visual_text, visual_profile, environment)
    score += _duration_score(candidate)
    score += 5 if candidate.get("provider") == "pexels" else 3
    score += _file_size_score(candidate)

    media_id = (candidate.get("provider", ""), candidate.get("id", ""))
    if media_id in used_ids:
        score -= 100
    contributor = candidate.get("photographer") or ""
    score -= contributor_counts.get(contributor, 0) * 8
    if any(bad in visual_text for bad in scene.get("negative_keywords", [])):
        score -= 25
    return score


def _keywords(text: str) -> list[str]:
    return [word for word in text.replace("-", " ").split() if len(word) > 3]


def _is_portrait(candidate: dict) -> bool:
    return int(candidate.get("height") or 0) >= int(candidate.get("width") or 0)


def _profile_score(text: str, profile: dict, environment: str) -> int:
    score = 0
    for field in ["main_subject", "environment", "mood", "dominant_topic"]:
        score += 4 if any(word in text for word in _keywords(str(profile.get(field, "")).lower())) else 0
    score += 4 if any(word in text for word in _keywords(environment)) else 0
    return min(score, 15)


def _duration_score(candidate: dict) -> int:
    return 4


def _file_size_score(candidate: dict) -> int:
    size = int(candidate.get("file_size") or 0)
    if not size:
        return 0
    if candidate.get("media_type") == "photo" and size > 6 * 1024 * 1024:
        return -30
    return 4


def _reuse_previous(selected: list[dict], scene: dict) -> dict | None:
    if len(selected) < 4:
        return None
    for previous in reversed(selected[:-3]):
        if previous.get("media_type") == "photo":
            return {**previous, "reuse": True, "scene": scene}
    return None
