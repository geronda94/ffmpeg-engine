import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession

# Добавляем корень проекта в путь поиска модулей
root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

from bot.handlers import common, scripting, assets, production, metadata

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

    # ФИКС: Используем простое число секунд вместо ClientTimeout
    # Это позволит aiogram корректно вычислять время опроса (polling)
    session = AiohttpSession()
    # Устанавливаем таймаут напрямую в секундах, чтобы избежать TypeError
    session.timeout = 900 
    
    bot = Bot(token=API_TOKEN, session=session)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(common.router)
    dp.include_router(scripting.router)
    dp.include_router(assets.router)
    dp.include_router(production.router)
    dp.include_router(metadata.router)

    logging.info("Starting bot v3.2.3 (Stability-Fix Edition)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Polling stopped")
