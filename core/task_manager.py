import asyncio
import logging
import os
import time
import multiprocessing
from typing import Callable, Any, Dict
from bot.pipeline_manager import render_project_video

logger = logging.getLogger(__name__)

CPU_COUNT = multiprocessing.cpu_count()
MAX_RENDER_THREADS = min(max(1, int(CPU_COUNT * 0.3)), 2)

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

    async def add_task(self, project_id: str, audio_path: str, user_id: str, callback_on_done: Callable = None, extra_data: dict = None):
        """Добавление проекта в очередь на рендер."""
        task_id = f"task_{project_id}_{int(time.time())}"
        task_info = {
            "task_id": task_id,
            "project_id": project_id,
            "audio_path": audio_path,
            "user_id": user_id,
            "status": "in_queue",
            "added_at": time.time(),
            "callback": callback_on_done,
            "extra_data": extra_data or {}
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
                logger.info(f"Worker: Starting render for {project_id} (threads={MAX_RENDER_THREADS})")
                video_path = await render_project_video(project_id, audio_path, render_threads=MAX_RENDER_THREADS)
                await asyncio.sleep(0)  # отдаём управление event loop для обработки апдейтов состояний
                
                if video_path:
                    from core.project_manager import ProjectManager
                    import os
                    pm_local = ProjectManager()
                    proj_data = pm_local.load_project(project_id)
                    
                    if proj_data and proj_data.get('burn_subtitles', False):
                        logger.info(f"Worker: Burning subtitles for {project_id}...")
                        from ai.subtitle_agent import generate_ass_from_project, burn_subtitles
                        
                        if 'whisper_segments' not in proj_data:
                            logger.info("Worker: Generating missing Whisper segments...")
                            from ai.timing_agent import get_model
                            model = get_model()
                            whisper_res = await asyncio.to_thread(model.transcribe, audio_path, verbose=False, word_timestamps=True)
                            proj_data['whisper_segments'] = whisper_res.get('segments', [])
                            pm_local.save_project(project_id, proj_data)
                            
                        project_path = pm_local.get_project_path(project_id)
                        ass_path = str(project_path / "subtitles.ass")
                        output_path = str(project_path / "video_with_subtitles.mp4")
                        
                        scenes_for_srt = proj_data['scenes']
                        assets = proj_data.get('assets', {})
                        for i, s in enumerate(scenes_for_srt):
                            s['allow_montage_effects'] = assets.get(str(i), {}).get('allow_montage_effects', True)
                        
                        # Определяем длительность превью для скрытия субтитров
                        m_start = 0.0
                        has_preview = proj_data.get('preview_text') or (
                            proj_data.get('scenes') and proj_data['scenes'][0].get('preview_text')
                        )
                        if has_preview:
                            from core.config_loader import get_config
                            m_start = get_config("preview_presets", ttl=0).get('display_duration', 2.0)
                            logger.info(f"Worker: Preview active — subtitles before {m_start}s will be invisible in ASS")

                        ass_res = generate_ass_from_project(scenes_for_srt, proj_data['whisper_segments'], ass_path,
                                                               min_start_time=m_start,
                                                               aligned_words=proj_data.get('aligned_words'),
                                                               language=proj_data.get('language', ''))
                        if ass_res:
                            res_path = await asyncio.to_thread(burn_subtitles, video_path, ass_path, output_path)
                            if res_path and os.path.exists(res_path):
                                video_path = res_path
                                logger.info(f"Worker: Subtitles burned successfully: {res_path}")
                            else:
                                logger.error("Worker: Failed to burn subtitles")
                        else:
                            logger.error("Worker: Failed to generate ASS")

                    task['status'] = "completed"
                    task['video_path'] = video_path
                    logger.info(f"Worker: Render success for {project_id}")
                else:
                    task['status'] = "failed"
                    logger.error(f"Worker: Render failed for {project_id}")
                
                # Вызываем коллбэк (отправка видео) в отдельной задаче, 
                # чтобы не блокировать воркер для следующего рендеринга.
                if task['callback']:
                    logger.info(f"Worker: Launching background callback for {project_id}")
                    asyncio.create_task(self._safe_callback(task))
                else:
                    logger.warning(f"Worker: No callback defined for {project_id}")
                    
            except Exception as e:
                logger.error(f"Worker Critical Error in task {project_id}: {e}", exc_info=True)
                task['status'] = "error"
                task['error'] = str(e)
            finally:
                self.queue.task_done()
                logger.info(f"Worker: Task {project_id} rendering cycle finished. Moving to next queue item...")

    async def _safe_callback(self, task: dict):
        """Безопасный запуск коллбэка в фоне (чтобы не уронить основной цикл)."""
        try:
            await task['callback'](task)
        except Exception as e:
            logger.error(f"Error in background callback for {task['project_id']}: {e}")

# Синглтон для импорта
task_manager = RenderTaskManager()
