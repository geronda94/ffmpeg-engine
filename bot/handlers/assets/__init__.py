"""Пакет обработчиков сбора материалов. Объединяет все суб-роутеры."""
from aiogram import Router

from bot.handlers.assets.ai_gen import router as ai_gen_router
from bot.handlers.assets.dynamic import router as dynamic_router
from bot.handlers.assets.manual import router as manual_router
from bot.handlers.assets.web_search import router as web_search_router
from bot.handlers.assets.auto_select import router as auto_select_router

# Главный роутер пакета — собирает все дочерние
router = Router()
router.include_router(dynamic_router)
router.include_router(ai_gen_router)
router.include_router(manual_router)
router.include_router(web_search_router)
router.include_router(auto_select_router)

__all__ = ["router"]
