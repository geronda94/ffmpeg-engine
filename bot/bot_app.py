import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession

# Добавляем корень проекта в путь поиска модулей
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

from bot.handlers import common, scripting, production, metadata, localization
from bot.handlers import scene_builder
from bot.handlers.assets import router as assets_router
from bot.middlewares.errors import ErrorHandlingMiddleware
from core.task_manager import task_manager

# Загружаем переменные окружения
load_dotenv(root_dir / ".env")
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main():
    if not API_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN не найден в .env файле!")
        return

    session = AiohttpSession()
    # Увеличиваем таймаут для работы с большими видео файлами (300 секунд = 5 минут)
    bot = Bot(token=API_TOKEN, session=session)
    # В aiogram 3.x таймаут на скачивание задается через session или в методах, 
    # но самый надежный способ - прокинуть его в Bot
    bot.default_request_timeout = 300 
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем мидлвари
    dp.update.outer_middleware(ErrorHandlingMiddleware())

    dp.include_router(common.router)
    dp.include_router(scripting.router)
    dp.include_router(assets_router)
    dp.include_router(production.router)
    dp.include_router(metadata.router)
    dp.include_router(localization.router)
    dp.include_router(scene_builder.router)

    # Запускаем менеджер задач
    task_manager.start(bot)

    # Устанавливаем команды в меню бота
    commands = [
        BotCommand(command="start",         description="Начать новый видеопроект"),
        BotCommand(command="scene",          description="Создать динамическую сцену"),
        BotCommand(command="render",         description="Повторить рендер текущего проекта"),
        BotCommand(command="clean",          description="Очистить старый мусор в чате"),
        BotCommand(command="clear_projects", description="Удалить все проекты с диска"),
        BotCommand(command="render_audio",   description="Озвучить текст и продолжить монтаж")
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        logging.warning(f"Failed to set bot commands: {e}")

    logging.info("Starting bot v3.7.1 (Localization & Queue Edition)...")
    await dp.start_polling(bot, request_timeout=120)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Polling stopped")
