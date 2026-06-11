import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import settings
from app.utils import (
    cleanup_old_outputs,
    ensure_directories,
    extract_topic,
    find_background_music,
    is_topic_too_long,
    unique_file_path,
)
from services.gemini_service import generate_scene_images, generate_video_plan
from services.video_service import create_tiktok_video
from services.voice_service import generate_voice

logger = logging.getLogger(__name__)

application: Application | None = None
active_generations: dict[int, str] = {}
generation_lock = asyncio.Lock()


async def initialize_bot() -> None:
    app = get_application()
    await app.initialize()
    await app.start()
    await app.bot.set_webhook(settings.webhook_url, drop_pending_updates=True)
    logger.info("Telegram webhook set to %s", settings.webhook_url)


async def shutdown_bot() -> None:
    if application is None:
        return
    try:
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
        "Je vais te générer une vidéo TikTok verticale d’environ 1 min 02 s, prête à publier."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    raw_text = update.message.text or ""

    if user_id in active_generations:
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

    active_generations[user_id] = "queued"
    await update.message.reply_text("✅ Sujet reçu. Je prépare la vidéo...")
    asyncio.create_task(_generate_and_send_video(update, context, topic, user_id))


async def _generate_and_send_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    topic: str,
    user_id: int,
) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else user_id

    try:
        async with generation_lock:
            active_generations[user_id] = "running"
            ensure_directories()
            cleanup_old_outputs()

            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await context.bot.send_message(chat_id=chat_id, text="📝 Génération du script long...")
            video_plan = await asyncio.to_thread(generate_video_plan, topic)

            await context.bot.send_message(chat_id=chat_id, text="🎨 Préparation des 15 à 20 scènes visuelles...")

            async def progress_callback(current: int, total: int) -> None:
                await context.bot.send_message(chat_id=chat_id, text=f"🎨 Génération des visuels {current}/{total}...")

            scene_images = await generate_scene_images(
                video_plan,
                str(settings.IMAGE_DIR),
                progress_callback=progress_callback,
            )

            await context.bot.send_message(chat_id=chat_id, text="🎙️ Génération de la voix...")
            audio_path = unique_file_path(settings.AUDIO_DIR, ".mp3")
            await asyncio.to_thread(generate_voice, video_plan["script"], str(audio_path))

            await context.bot.send_message(chat_id=chat_id, text="🎬 Montage de la vidéo 1 min 02 s...")
            output_path = unique_file_path(settings.VIDEO_DIR, ".mp4")
            music_path = find_background_music()
            await asyncio.to_thread(
                create_tiktok_video,
                video_plan["title"],
                video_plan["script"],
                scene_images,
                str(audio_path),
                str(output_path),
                music_path,
            )

            await context.bot.send_message(chat_id=chat_id, text="📤 Envoi de la vidéo...")
            try:
                with Path(output_path).open("rb") as video_file:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=video_file,
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=60,
                    )
            except Exception:
                logger.exception("Telegram video send failed.")
                raise

            hashtags = " ".join(video_plan.get("hashtags") or [])
            await context.bot.send_message(chat_id=chat_id, text=f"{video_plan['title']}\n\n{hashtags}".strip())

    except Exception:
        logger.exception("Video generation failed for user_id=%s", user_id)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Une erreur est survenue pendant la génération de la vidéo. Réessaie avec un sujet plus court ou plus simple.",
            )
        except Exception:
            logger.exception("Could not send user-facing error message.")
    finally:
        active_generations.pop(user_id, None)


def get_application() -> Application:
    global application
    if application is None:
        settings.validate_required()
        application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN or "").build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application
