import logging
import math
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.utils import unique_file_path
from services.subtitle_service import split_script_into_subtitles

logger = logging.getLogger(__name__)


def create_tiktok_video(
    video_plan: dict,
    prepared_media: list[dict],
    audio_path: str,
    output_path: str,
    music_path: str | None = None,
) -> str:
    if not prepared_media:
        raise RuntimeError("Aucun média disponible pour créer la vidéo.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    work_dir = settings.VIDEO_DIR / f"render_{output.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = _ffmpeg_exe()
    duration = _probe_duration(audio_path) or settings.TARGET_DURATION_SECONDS
    scene_duration = duration / len(prepared_media)
    width, height = settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT

    segment_paths: list[Path] = []
    concat_path = work_dir / "concat.txt"
    video_only_path = work_dir / "video_only.mp4"
    subtitle_path = work_dir / "subtitles.ass"

    try:
        for index, media in enumerate(prepared_media, start=1):
            segment_path = work_dir / f"segment_{index:02d}.mp4"
            _render_segment(ffmpeg, media, segment_path, scene_duration, width, height)
            segment_paths.append(segment_path)

        _write_concat_file(concat_path, segment_paths)
        _run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c",
                "copy",
                str(video_only_path),
            ]
        )

        _write_ass_subtitles(
            subtitle_path,
            title=video_plan.get("title", "Vidéo TikTok"),
            script=video_plan.get("script", ""),
            audio_duration=duration,
            width=width,
            height=height,
        )
        _mux_audio_and_subtitles(ffmpeg, video_only_path, subtitle_path, audio_path, output, duration, music_path)
    except Exception as exc:
        logger.exception("FFmpeg video export failed.")
        raise RuntimeError("Le montage vidéo a échoué.") from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return str(output)


def _render_segment(ffmpeg: str, media: dict, output_path: Path, duration: float, width: int, height: int) -> None:
    source = media.get("prepared_path")
    if not source or not Path(source).exists():
        raise RuntimeError("Prepared media path is missing.")

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={settings.VIDEO_FPS},format=yuv420p"
    )

    if media.get("prepared_type") == "video":
        cmd = [
            ffmpeg,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            source,
            "-t",
            f"{duration:.3f}",
            "-an",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-threads",
            "1",
            str(output_path),
        ]
    else:
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            f"{duration:.3f}",
            "-i",
            source,
            "-an",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "30",
            "-threads",
            "1",
            str(output_path),
        ]
    _run(cmd)


def _mux_audio_and_subtitles(
    ffmpeg: str,
    video_path: Path,
    subtitle_path: Path,
    audio_path: str,
    output_path: Path,
    duration: float,
    music_path: str | None,
) -> None:
    subtitle_filter = f"ass={_ffmpeg_filter_path(subtitle_path)}"
    if music_path and Path(music_path).exists():
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-i",
            audio_path,
            "-stream_loop",
            "-1",
            "-i",
            music_path,
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            f"[0:v]{subtitle_filter}[v];[2:a]volume=0.09[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-threads",
            "1",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-i",
            audio_path,
            "-t",
            f"{duration:.3f}",
            "-vf",
            subtitle_filter,
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-threads",
            "1",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    _run(cmd)


def _write_concat_file(path: Path, segment_paths: list[Path]) -> None:
    lines = []
    for segment in segment_paths:
        safe = str(segment.resolve()).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{safe}'")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_ass_subtitles(path: Path, title: str, script: str, audio_duration: float, width: int, height: int) -> None:
    subtitles = split_script_into_subtitles(script, audio_duration, max_words=7)
    title_font = max(34, int(width * 0.062))
    subtitle_font = max(30, int(width * 0.052))
    subtitle_margin_v = int(height * 0.22)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,DejaVu Sans,{title_font},&H00FFFFFF,&H000000FF,&H90000000,&H90000000,1,0,0,0,100,100,0,0,3,1,0,8,60,60,110,1
Style: Subtitle,DejaVu Sans,{subtitle_font},&H00FFFFFF,&H000000FF,&H90000000,&H90000000,1,0,0,0,100,100,0,0,3,1,0,2,56,56,{subtitle_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [f"Dialogue: 0,0:00:00.00,{_ass_time(min(2.8, audio_duration))},Title,,0,0,0,,{_ass_escape(title)}"]
    for subtitle in subtitles:
        events.append(
            "Dialogue: 0,"
            f"{_ass_time(subtitle['start'])},{_ass_time(subtitle['end'])},"
            f"Subtitle,,0,0,0,,{_ass_escape(subtitle['text'])}"
        )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def _probe_duration(path: str) -> float | None:
    ffprobe = _ffprobe_exe()
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return float(result.stdout.strip())
        except Exception:
            logger.debug("ffprobe duration failed for %s", path, exc_info=True)
    try:
        result = subprocess.run([_ffmpeg_exe(), "-i", path], capture_output=True, text=True, timeout=30)
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception:
        logger.debug("ffmpeg duration parse failed for %s", path, exc_info=True)
    return None


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _ffprobe_exe() -> str | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe
    ffmpeg = _ffmpeg_exe()
    candidate = str(Path(ffmpeg).with_name("ffprobe.exe" if ffmpeg.endswith(".exe") else "ffprobe"))
    return candidate if Path(candidate).exists() else None


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        logger.error("FFmpeg command failed: %s", _redact_cmd(cmd))
        logger.error("FFmpeg stderr: %s", (result.stderr or "")[-1200:])
        raise RuntimeError("FFmpeg command failed.")


def _redact_cmd(cmd: list[str]) -> str:
    return " ".join(str(part) for part in cmd if "api" not in str(part).lower())


def _ffmpeg_filter_path(path: Path) -> str:
    escaped = str(path.resolve()).replace("\\", "/").replace(":", "\\:")
    return escaped.replace("'", "\\'")


def _ass_time(seconds: float) -> str:
    seconds = max(0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _ass_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def create_text_overlay(
    text: str,
    width: int | None = None,
    height: int | None = None,
    position: str = "bottom",
) -> str:
    width = width or settings.VIDEO_WIDTH
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
    draw.rounded_rectangle([0, 0, block_width, block_height], radius=34, fill=(0, 0, 0, 150))
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
