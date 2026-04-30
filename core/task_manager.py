import asyncio
import logging
import time
from typing import Callable, Any, Dict
from bot.pipeline_manager import render_project_video

logger = logging.getLogger(__name__)

class RenderTaskManager:
    """Менеджер фоновых задач рендеринга (Singleton)."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RenderTaskManager, cls).__new__(cls)
            cls._instance.queue = asyncio.Queue()
            cls._instance.active_tasks = {}
            cls._instance.worker_task = None
            cls._instance.bot = None
        return cls._instance

    def start(self, bot):
        """Запуск фонового воркера."""
        self.bot = bot
        if self.worker_task is None:
            self.worker_task = asyncio.create_task(self._worker())
            logger.info("Render Task Manager started.")

    async def add_task(self, project_id: str, audio_path: str, user_id: str, callback_on_done: Callable = None):
        """Добавление проекта в очередь на рендер."""
        task_id = f"task_{project_id}_{int(time.time())}"
        task_info = {
            "task_id": task_id,
            "project_id": project_id,
            "audio_path": audio_path,
            "user_id": user_id,
            "status": "in_queue",
            "added_at": time.time(),
            "callback": callback_on_done
        }
        self.active_tasks[project_id] = task_info
        await self.queue.put(task_info)
        logger.info(f"Task added to queue: {project_id}. Queue size: {self.queue.qsize()}")
        return task_id

    def get_task_status(self, project_id: str):
        return self.active_tasks.get(project_id)

    async def _worker(self):
        """Бесконечный воркер, обрабатывающий очередь."""
        while True:
            task = await self.queue.get()
            project_id = task['project_id']
            audio_path = task['audio_path']
            
            logger.info(f"Worker: Starting render for project {project_id}")
            task['status'] = "rendering"
            task['started_at'] = time.time()
            
            try:
                # Вызываем рендер из pipeline_manager
                video_path = await render_project_video(project_id, audio_path)
                
                if video_path:
                    task['status'] = "completed"
                    task['video_path'] = video_path
                    logger.info(f"Worker: Render success for {project_id}")
                else:
                    task['status'] = "failed"
                    logger.error(f"Worker: Render failed for {project_id}")
                
                # Вызываем коллбэк (например, для отправки видео пользователю)
                if task['callback']:
                    await task['callback'](task)
                    
            except Exception as e:
                logger.error(f"Worker Critical Error in task {project_id}: {e}", exc_info=True)
                task['status'] = "error"
                task['error'] = str(e)
            finally:
                # Очищаем из активных после завершения (опционально)
                # del self.active_tasks[project_id] 
                self.queue.task_done()
                logger.info(f"Worker: Task {project_id} finished. Waiting for next...")

# Синглтон для импорта
task_manager = RenderTaskManager()
