import os
import sys
import asyncio
import logging
from pathlib import Path

# Настройка путей
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from dotenv import load_dotenv

# Импорт роутеров
from bot.handlers import common, scripting, assets, production

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Регистрация роутеров в правильном порядке
dp.include_router(common.router)
dp.include_router(scripting.router)
dp.include_router(assets.router)
dp.include_router(production.router)

async def set_main_menu(bot: Bot):
    await bot.set_my_commands([BotCommand(command='/start', description='🚀 Начать новый проект')])

async def main():
    logger.info("Starting bot v3.1 (Modular Edition)...")
    await set_main_menu(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
