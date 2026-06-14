import asyncio
import logging
from pathlib import Path
import uuid

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import settings
from app.queue_manager import GenerationJob, generation_queue
from app.utils import (
    cleanup_old_outputs,
    ensure_directories,
    extract_topic,
    find_background_music,
    is_topic_too_long,
)
from services.gemini_service import generate_video_plan
from services.media_processing_service import cleanup_job_files, prepare_selected_media
from services.media_search_service import MediaSearchClient
from services.media_selection_service import select_best_media_for_scenes
from services.video_service import create_tiktok_video
from services.voice_service import generate_voice

logger = logging.getLogger(__name__)

application: Application | None = None


async def initialize_bot() -> None:
    app = get_application()
    await app.initialize()
    await app.start()
    generation_queue.start(_generate_and_send_video)
    await app.bot.set_webhook(settings.webhook_url, drop_pending_updates=True)
    logger.info("Telegram webhook set to %s", settings.webhook_url)


async def shutdown_bot() -> None:
    if application is None:
        return
    try:
        await generation_queue.stop()
        await application.stop()
        await application.shutdown()
    except Exception:
        logger.exception("Telegram application shutdown failed.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Bonjour 👋\n"
        "Envoie-moi un sujet comme ceci :\n\n"
        "Sujet : comment choisir un bon ordinateur portable d’occasion au Sénégal\n\n"
        "Je vais créer une vidéo TikTok verticale d’environ 1 min 02 s avec des visuels cohérents, une voix française et des sous-titres."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    raw_text = update.message.text or ""

    if generation_queue.is_user_active(user_id):
        await update.message.reply_text(
            "⏳ Une vidéo est déjà en cours de génération. Attends la fin avant d’envoyer un nouveau sujet."
        )
        return

    if is_topic_too_long(raw_text):
        await update.message.reply_text("Le sujet est trop long. Envoie un sujet de 250 caractères maximum.")
        return

    topic = extract_topic(raw_text)
    if not topic:
        await update.message.reply_text("Envoie-moi un sujet valide, par exemple : Sujet : acheter un PC au Sénégal")
        return

    await update.message.reply_text("✅ Sujet reçu. Je prépare la vidéo...")
    if generation_queue.has_running_job():
        await update.message.reply_text("⏳ Une autre vidéo est en cours de génération. Ton sujet a été ajouté à la file d’attente.")
    chat_id = update.effective_chat.id if update.effective_chat else user_id
    await generation_queue.enqueue(GenerationJob(user_id=user_id, chat_id=chat_id, topic=topic, context=context))


async def _generate_and_send_video(job: GenerationJob) -> None:
    context = job.context
    chat_id = job.chat_id
    job_id = uuid.uuid4().hex
    audio_path: Path | None = None
    output_path: Path | None = None
    job_media_dir = settings.MEDIA_DIR / job_id

    try:
        ensure_directories()
        cleanup_old_outputs()

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await context.bot.send_message(chat_id=chat_id, text="📝 Génération du script et du plan visuel...")
        video_plan = await asyncio.to_thread(generate_video_plan, job.topic)

        await context.bot.send_message(chat_id=chat_id, text="🔎 Recherche des médias cohérents...")
        candidate_results = await asyncio.to_thread(_search_candidates, video_plan)

        await context.bot.send_message(chat_id=chat_id, text="🎞️ Sélection des visuels 1/18...")
        selected_media = await asyncio.to_thread(select_best_media_for_scenes, video_plan, candidate_results)
        total = len(selected_media)
        for checkpoint in [5, 10, 15]:
            if total >= checkpoint:
                await context.bot.send_message(chat_id=chat_id, text=f"🎞️ Sélection des visuels {checkpoint}/{total}...")

        await context.bot.send_message(chat_id=chat_id, text="⬇️ Téléchargement et préparation des médias...")
        prepared_media = await asyncio.to_thread(prepare_selected_media, selected_media, job_id)

        await context.bot.send_message(chat_id=chat_id, text="🎙️ Génération de la voix...")
        audio_path = settings.AUDIO_DIR / f"{job_id}.mp3"
        await asyncio.to_thread(generate_voice, video_plan["script"], str(audio_path))

        await context.bot.send_message(chat_id=chat_id, text="📝 Préparation des sous-titres...")

        await context.bot.send_message(chat_id=chat_id, text="🎬 Montage de la vidéo 1 min 02 s...")
        output_path = settings.VIDEO_DIR / f"{job_id}.mp4"
        await asyncio.to_thread(
            create_tiktok_video,
            video_plan,
            prepared_media,
            str(audio_path),
            str(output_path),
            find_background_music(),
        )

        await context.bot.send_message(chat_id=chat_id, text="📤 Envoi de la vidéo...")
        with output_path.open("rb") as video_file:
            await context.bot.send_video(
                chat_id=chat_id,
                video=video_file,
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=60,
            )

        hashtags = " ".join(video_plan.get("hashtags") or [])
        await context.bot.send_message(chat_id=chat_id, text=f"{video_plan['title']}\n\n{hashtags}".strip())
    finally:
        cleanup_job_files([str(job_media_dir), str(audio_path) if audio_path else None, str(output_path) if output_path else None])


def _search_candidates(video_plan: dict) -> dict[int, list[dict]]:
    client = MediaSearchClient()
    results: dict[int, list[dict]] = {}
    for scene in video_plan.get("scenes", []):
        scene_number = int(scene.get("scene_number") or len(results) + 1)
        results[scene_number] = client.search_scene_candidates(scene)
    return results


def get_application() -> Application:
    global application
    if application is None:
        settings.validate_required()
        application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN or "").build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application
