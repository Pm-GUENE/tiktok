import re


def split_script_into_subtitles(script: str, audio_duration: float, max_words: int = 7) -> list[dict]:
    words = re.findall(r"\S+", script.strip())
    if not words or audio_duration <= 0:
        return []

    max_words = max(4, min(max_words, 8))
    chunks = [" ".join(words[index : index + max_words]) for index in range(0, len(words), max_words)]
    duration_per_chunk = audio_duration / len(chunks)

    subtitles = []
    for index, text in enumerate(chunks):
        start = round(index * duration_per_chunk, 2)
        end = round(min(audio_duration, (index + 1) * duration_per_chunk), 2)
        if end - start < 0.8:
            end = min(audio_duration, start + 0.8)
        subtitles.append({"text": text, "start": start, "end": end})

    return subtitles
