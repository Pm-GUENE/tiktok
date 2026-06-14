import logging
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.utils import unique_file_path
from services.subtitle_service import split_script_into_subtitles

logger = logging.getLogger(__name__)
_MP = None


def create_tiktok_video(
    video_plan: dict,
    prepared_media: list[dict],
    audio_path: str,
    output_path: str,
    music_path: str | None = None,
) -> str:
    if not prepared_media:
        raise RuntimeError("Aucun média disponible pour créer la vidéo.")

    mp = _load_moviepy()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    voice = mp.AudioFileClip(audio_path)
    duration = float(voice.duration or settings.TARGET_DURATION_SECONDS)
    width, height = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT
    script = video_plan.get("script", "")
    title = video_plan.get("title", "Vidéo TikTok")

    clips = []
    scene_duration = duration / len(prepared_media)
    for index, media in enumerate(prepared_media):
        clip = _make_media_clip(mp, media, scene_duration, width, height, index)
        clips.append(clip)

    video = _with_duration(mp.concatenate_videoclips(clips, method="compose"), duration)

    overlays = []
    title_overlay = create_text_overlay(title, width=width, height=height, position="title")
    title_clip = mp.ImageClip(title_overlay)
    title_clip = _with_position(title_clip, ("center", 180))
    title_clip = _with_start(_with_duration(title_clip, min(2.6, duration)), 0)
    overlays.append(title_clip)

    for subtitle in split_script_into_subtitles(script, duration, max_words=7):
        overlay_path = create_text_overlay(subtitle["text"], width=width, height=height, position="bottom")
        overlay = mp.ImageClip(overlay_path)
        overlay = _with_position(overlay, ("center", int(height * 0.68)))
        overlay = _with_start(overlay, subtitle["start"])
        overlay = _with_duration(overlay, max(0.5, subtitle["end"] - subtitle["start"]))
        overlays.append(overlay)

    final = _with_duration(mp.CompositeVideoClip([video, *overlays], size=(width, height)), duration)

    audio_tracks = [_with_volume(voice, 1.0)]
    audio_clips_to_close = []
    if music_path and Path(music_path).exists():
        try:
            music = _with_volume(mp.AudioFileClip(music_path), 0.1)
            if music.duration < duration:
                music = _loop_audio(music, duration, mp)
            else:
                music = _subclip(music, 0, duration)
            music = _audio_fadeout(music, 1.0)
            audio_tracks.append(music)
            audio_clips_to_close.append(music)
        except Exception:
            logger.exception("Background music could not be loaded. Continuing without music.")

    mixed_audio = _with_duration(mp.CompositeAudioClip(audio_tracks), duration)
    final = _with_audio(final, mixed_audio)

    try:
        final.write_videofile(
            output_path,
            fps=settings.VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            preset="veryfast",
            bitrate="1200k",
            audio_bitrate="128k",
            threads=1,
            logger=None,
            temp_audiofile=str(Path(output_path).with_suffix(".temp-audio.m4a")),
            remove_temp=True,
        )
    except Exception as exc:
        logger.exception("MoviePy video export failed.")
        raise RuntimeError("Le montage vidéo a échoué.") from exc
    finally:
        _close_clips([final, mixed_audio, *audio_clips_to_close, video, *overlays, *clips, voice])

    return output_path


def _load_moviepy():
    global _MP
    if _MP is not None:
        return _MP
    try:
        import moviepy.editor as moviepy_module
    except ModuleNotFoundError:
        import moviepy as moviepy_module
    _MP = moviepy_module
    return _MP


def _make_media_clip(mp, media: dict, scene_duration: float, width: int, height: int, index: int):
    path = media.get("prepared_path")
    if not path:
        raise RuntimeError("Prepared media path is missing.")

    if media.get("prepared_type") == "video":
        clip = mp.VideoFileClip(path)
        clip = _without_audio(clip)
        if float(clip.duration or 0) > scene_duration:
            start = 0
            if clip.duration and clip.duration > scene_duration + 1:
                start = min((index % 3) * 0.7, max(0, clip.duration - scene_duration))
            clip = _subclip(clip, start, start + scene_duration)
        else:
            clip = _with_duration(clip, scene_duration)
    else:
        clip = mp.ImageClip(path)
        clip = _with_duration(clip, scene_duration)
        clip = _resized(clip, lambda t: 1.0 + 0.03 * (t / max(scene_duration, 0.1)))

    clip = _cover_resize_crop(clip, width, height)
    return _with_duration(clip, scene_duration)


def _with_duration(clip, duration: float):
    if hasattr(clip, "with_duration"):
        return clip.with_duration(duration)
    return clip.set_duration(duration)


def _with_start(clip, start: float):
    if hasattr(clip, "with_start"):
        return clip.with_start(start)
    return clip.set_start(start)


def _with_audio(clip, audio):
    if hasattr(clip, "with_audio"):
        return clip.with_audio(audio)
    return clip.set_audio(audio)


def _without_audio(clip):
    if hasattr(clip, "without_audio"):
        return clip.without_audio()
    return clip.set_audio(None)


def _with_position(clip, position):
    if hasattr(clip, "with_position"):
        return clip.with_position(position)
    return clip.set_position(position)


def _resized(clip, *args, **kwargs):
    if hasattr(clip, "resized"):
        return clip.resized(*args, **kwargs)
    return clip.resize(*args, **kwargs)


def _cropped(clip, *args, **kwargs):
    if hasattr(clip, "cropped"):
        return clip.cropped(*args, **kwargs)
    return clip.crop(*args, **kwargs)


def _cover_resize_crop(clip, width: int, height: int):
    source_w = getattr(clip, "w", None) or getattr(clip, "size", [width, height])[0]
    source_h = getattr(clip, "h", None) or getattr(clip, "size", [width, height])[1]
    source_ratio = source_w / source_h
    target_ratio = width / height
    if source_ratio > target_ratio:
        clip = _resized(clip, height=height)
    else:
        clip = _resized(clip, width=width)
    return _cropped(clip, x_center=clip.w / 2, y_center=clip.h / 2, width=width, height=height)


def _subclip(clip, start: float, end: float):
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start, end)
    return clip.subclip(start, end)


def _with_volume(clip, factor: float):
    if hasattr(clip, "with_volume_scaled"):
        return clip.with_volume_scaled(factor)
    return clip.volumex(factor)


def _loop_audio(audio, duration: float, mp):
    if not audio.duration or audio.duration <= 0:
        return _with_duration(audio, duration)
    loop_count = max(1, math.ceil(duration / audio.duration))
    looped = mp.concatenate_audioclips([audio] * loop_count)
    return _subclip(looped, 0, duration)


def _audio_fadeout(audio, seconds: float):
    if hasattr(audio, "audio_fadeout"):
        return audio.audio_fadeout(seconds)
    return audio


def create_text_overlay(
    text: str,
    width: int | None = None,
    height: int | None = None,
    position: str = "bottom",
) -> str:
    width = width or settings.VIDEO_WIDTH
    height = height or settings.VIDEO_HEIGHT
    output_path = unique_file_path(settings.OVERLAY_OUTPUT_DIR, ".png")
    is_title = position == "title"
    font_size = max(38, min(64, int(width * (0.084 if is_title else 0.068))))
    font = _load_font(font_size)
    max_width = width - 150
    lines = _wrap_lines(text, font, max_width, max_lines=4 if is_title else 3)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
    line_height = _line_height(font) + 14
    block_width = max(probe.textbbox((0, 0), line, font=font)[2] for line in lines) + 80
    block_width = min(width - 80, max(260, block_width))
    block_height = line_height * len(lines) + 50
    image = Image.new("RGBA", (block_width, block_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        [0, 0, block_width, block_height],
        radius=34,
        fill=(0, 0, 0, 150),
    )

    text_y = 24
    for line in lines:
        line = _fit_line(line, font, block_width - 80)
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        text_x = (block_width - text_width) // 2
        draw.text((text_x + 3, text_y + 3), line, font=font, fill=(0, 0, 0, 190))
        draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
        text_y += line_height

    image.save(output_path, "PNG")
    return str(output_path)


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


def _line_height(font: ImageFont.ImageFont) -> int:
    bbox = font.getbbox("Ay")
    return bbox[3] - bbox[1]


def _wrap_lines(text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    words = text.strip().split()
    if not words:
        return [""]
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break

    if current and len(lines) < max_lines:
        remaining = words[len(" ".join(lines).split()) :]
        final_line = " ".join(remaining) if remaining else current
        while draw.textbbox((0, 0), final_line, font=font)[2] > max_width and len(final_line) > 8:
            final_line = final_line[:-4].rstrip() + "..."
        lines.append(final_line)

    return lines[:max_lines]


def _fit_line(line: str, font: ImageFont.ImageFont, max_width: int) -> str:
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    if draw.textbbox((0, 0), line, font=font)[2] <= max_width:
        return line

    fitted = line
    while len(fitted) > 4 and draw.textbbox((0, 0), fitted + "...", font=font)[2] > max_width:
        fitted = fitted[:-1]
    return fitted.rstrip() + "..."


def _close_clips(clips: list) -> None:
    for clip in clips:
        try:
            clip.close()
        except Exception:
            pass
