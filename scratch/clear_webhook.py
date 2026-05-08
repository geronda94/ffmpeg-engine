import asyncio
import os
from aiogram import Bot
from dotenv import load_dotenv

async def main():
    load_dotenv(".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Token not found")
        return
    bot = Bot(token=token)
    print("Deleting webhook...")
    await bot.delete_webhook(drop_pending_updates=True)
    print("Webhook deleted and updates dropped.")
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
