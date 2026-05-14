# 🎬 Content Factory — Автоматизированная фабрика контента

**Content Factory** — экосистема для создания короткометражного видео (Shorts, Reels, TikTok)
через Telegram-бота. Генерация от идеи до готового MP4 с эффектами, музыкой и субтитрами.

## Быстрый старт

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # добавить DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN
python3 bot/bot_app.py
```

**Требования:** Python 3.10+, ffmpeg, ffprobe в PATH

## Документация

Вся документация в папке `docs/`:

| Файл | Описание |
|------|----------|
| `docs/CURRENT_ARCHITECTURE.md` | Полная архитектура, пайплайн, агенты, конфиги |
| `docs/ROADMAP.md` | План развития, техдолг, приоритеты |
| `docs/VIDEO_ENGINE_ARCH.md` | Внутренности видео-движка (MoviePy) |
| `docs/MOVIEPY_V2_GUIDE.md` | Шпаргалка по MoviePy 2.x для AI |
| `docs/SCHEDULER_BOT_PLAN.md` | План планировщика контента |
| `docs/montage_instructions.txt` | Системный промпт для AI-монтажёра |

## Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Telegram Bot | aiogram 3.x (FSM, middleware, async) |
| LLM | DeepSeek-V3 через OpenAI SDK |
| TTS | Edge-TTS (free) + Gemini Pro (premium) |
| Video | MoviePy v2 + FFmpeg |
| Search | Pexels + Pixabay + Pollinations AI |
| Storage | Disk-first JSON (`projects/{id}/project.json`) |

## Лицензия

MIT
