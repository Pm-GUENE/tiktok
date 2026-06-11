import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


class GeminiRateLimiter:
    def __init__(self, interval_seconds: float = 13.0, max_retries: int = 3) -> None:
        self.interval_seconds = interval_seconds
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def call(self, func: Callable[[], T], fallback: Callable[[], T] | None = None) -> T:
        for attempt in range(1, self.max_retries + 1):
            self._wait_turn()
            try:
                return func()
            except Exception as exc:
                if self._is_rate_limit_error(exc):
                    logger.warning("Gemini rate limit error on attempt %s/%s: %s", attempt, self.max_retries, exc)
                    time.sleep(60)
                    continue
                logger.exception("Gemini request failed.")
                if fallback:
                    return fallback()
                raise

        logger.error("Gemini request failed after rate-limit retries.")
        if fallback:
            return fallback()
        raise RuntimeError("Gemini rate limit retries exhausted.")

    def _wait_turn(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            wait_seconds = self.interval_seconds - elapsed
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request_at = time.monotonic()

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "429" in text or "rate limit" in text or "resource exhausted" in text or "quota" in text


gemini_rate_limiter = GeminiRateLimiter()
