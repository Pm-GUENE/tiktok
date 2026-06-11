import logging
from pathlib import Path

from gtts import gTTS

logger = logging.getLogger(__name__)


def generate_voice(script: str, output_path: str) -> str:
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tts = gTTS(text=script, lang="fr", slow=False)
        tts.save(output_path)
        return output_path
    except Exception as exc:
        logger.exception("gTTS voice generation failed.")
        raise RuntimeError("La génération de la voix a échoué.") from exc
