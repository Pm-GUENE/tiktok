import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


@dataclass
class GenerationJob:
    user_id: int
    chat_id: int
    topic: str
    context: ContextTypes.DEFAULT_TYPE


WorkerCallback = Callable[[GenerationJob], Awaitable[None]]


class GenerationQueue:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[GenerationJob] = asyncio.Queue()
        self.active_users: dict[int, str] = {}
        self.worker_task: asyncio.Task | None = None
        self.worker_callback: WorkerCallback | None = None

    def start(self, callback: WorkerCallback) -> None:
        self.worker_callback = callback
        if not self.worker_task or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if not self.worker_task:
            return
        self.worker_task.cancel()
        try:
            await self.worker_task
        except asyncio.CancelledError:
            pass

    def is_user_active(self, user_id: int) -> bool:
        return user_id in self.active_users

    def has_running_job(self) -> bool:
        return any(status == "running" for status in self.active_users.values())

    async def enqueue(self, job: GenerationJob) -> None:
        self.active_users[job.user_id] = "queued"
        await self.queue.put(job)

    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            self.active_users[job.user_id] = "running"
            try:
                if not self.worker_callback:
                    raise RuntimeError("Generation queue worker callback is not configured.")
                await self.worker_callback(job)
            except Exception:
                logger.exception("Generation job failed for user_id=%s", job.user_id)
                try:
                    await job.context.bot.send_message(
                        chat_id=job.chat_id,
                        text="❌ Une erreur est survenue pendant la génération de la vidéo. Réessaie avec un sujet plus court ou plus simple.",
                    )
                except Exception:
                    logger.exception("Could not send generation error message to user.")
            finally:
                self.active_users.pop(job.user_id, None)
                self.queue.task_done()


generation_queue = GenerationQueue()
