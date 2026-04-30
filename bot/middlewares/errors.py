import logging
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

logger = logging.getLogger(__name__)

class ErrorHandlingMiddleware(BaseMiddleware):
    """
    Глобальный перехватчик ошибок для бота.
    Уведомляет пользователя о сбое и записывает детали в лог.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"Unhandled exception during update processing: {e}", exc_info=True)
            
            error_text = (
                "⚠️ **Произошла внутренняя ошибка.**\n\n"
                "Команда разработки уже уведомлена. Попробуйте нажать /start или /render, "
                "чтобы восстановить текущий проект."
            )
            
            if isinstance(event, Message):
                await event.answer(error_text)
            elif isinstance(event, CallbackQuery):
                await event.message.answer(error_text)
                await event.answer()
            
            return None
