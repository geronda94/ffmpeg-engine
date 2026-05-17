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

root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

from bot.handlers import common, scripting, production, metadata, localization
from bot.handlers.assets import router as assets_router
from bot.handlers.auto_pipeline import router as auto_pipeline_router
from bot.middlewares.errors import ErrorHandlingMiddleware
from core.task_manager import task_manager

# Загружаем переменные окружения
load_dotenv(root_dir / ".env")
API_TOKEN = os.getenv("TELEGRAM_AUTO_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def main():
    if not API_TOKEN:
        logging.error("TELEGRAM_AUTO_BOT_TOKEN / TELEGRAM_BOT_TOKEN не найден в .env!")
        return

    session = AiohttpSession()
    bot = Bot(token=API_TOKEN, session=session)
    bot.default_request_timeout = 300
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.outer_middleware(ErrorHandlingMiddleware())

    dp.include_router(common.router)
    dp.include_router(scripting.router)
    dp.include_router(assets_router)
    dp.include_router(production.router)
    dp.include_router(metadata.router)
    dp.include_router(localization.router)
    dp.include_router(auto_pipeline_router)

    task_manager.start(bot)

    commands = [
        BotCommand(command="start", description="Начать новый видеопроект"),
        BotCommand(command="render_audio", description="Озвучить текст и продолжить"),
        BotCommand(command="full_automat", description="Полный автомат"),
        BotCommand(command="auto", description="Автомат в топике: /auto текст"),
        BotCommand(command="rebuild_last", description="Перерендерить последнее видео"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        logging.warning(f"Failed to set bot commands: {e}")

    logging.info("🤖 Starting AUTO Content Factory...")
    await dp.start_polling(bot, request_timeout=120)


if __name__ == "__main__":
    try:
        # Преждевременная загрузка assets-роутера для избежания ленивой ошибки
        from bot.handlers.assets import router as assets_router
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Polling stopped")
