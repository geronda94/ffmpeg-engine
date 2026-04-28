# Архитектура "Контент-Завод v3.1" 🏭🎬

Система представляет собой мульти-агентную фабрику видеоконтента, управляемую через Telegram-бота.

## 🏗 Структура проекта

### 1. Бот-интерфейс (`bot/`)
Использует **Aiogram 3.x** с модульной системой роутеров.
- `bot_app.py`: Точка входа. Регистрирует модули и запускает Polling.
- `states.py`: Определение состояний FSM (Finite State Machine). Гарантирует строгую последовательность этапов.
- `handlers/`:
    - `common.py`: Старт, сброс состояний, выбор языка.
    - `scripting.py`: Агент-Сценарист и Агент-Корректор. Работа с DeepSeek API.
    - `storyboard.py`: Агент-Раскадровщик. Разбивка текста на визуальные сцены.
    - `assets.py`: Коллектор материалов. Обработка ИИ-генерации, прямых ссылок и файлов.
    - `production.py`: Финальный этап. Выбор озвучки и запуск рендера.

### 2. ИИ-Агенты (`ai/`)
- `script_writer.py`: Генерация сценария с учетом заданного хронометража.
- `storyboarder.py`: Анализ текста и создание `visual_description` и `image_prompt` для каждой сцены.
- `image_generator.py`: Интеграция с ИИ для создания уникальных визуалов.
- `tts_edge.py`: Бесплатная качественная озвучка через Edge-TTS (нейросети Microsoft).
- `syncer.py`: **"Мозг" синхронизации**. Рассчитывает время появления каждой сцены пропорционально количеству слов в её тексте относительно длины аудио.

### 3. Видео-Движок (`bot/pipeline_manager.py`)
Оркестратор **FFmpeg**.
- Автоматически приводит все ассеты (фото/видео) к формату **1080x1920 (9:16)**.
- Применяет эффект **Zoompan** (плавный наплыв) для оживления статичных картинок.
- Накладывает динамические субтитры с подложкой.
- Склеивает видео с аудиодорожкой в финальный MP4.

## 🔄 Жизненный цикл проекта (Workflow)

1. **Phase: Creative**
   - User -> Topic -> Agent:ScriptWriter -> Script -> Approval.
2. **Phase: Visual Planning**
   - Script -> Agent:Storyboarder -> Scenes (Descriptions) -> Iterative Approval.
3. **Phase: Asset Collection**
   - For each Scene: User provides File/URL OR triggers Agent:ImageGen.
   - Visual Confirmation: User sees the result before it goes to montage.
4. **Phase: Assembly**
   - TTS Generation -> Timing Calculation (Syncer) -> FFmpeg Render -> Ready Video.

## 🛠 Технологический стек
- **Python 3.12+**
- **Aiogram 3.x** (Telegram API)
- **DeepSeek API** (LLM - Разум системы)
- **FFmpeg** (Монтаж)
- **Edge-TTS** (Озвучка)
- **Aiohttp** (Загрузка файлов)

## ⚠️ Правила для разработчика
- При изменении логики этапов — проверять `bot/states.py`.
- При добавлении новых эффектов — редактировать `bot/pipeline_manager.py`.
- Все временные файлы должны сохраняться в `local_assets/`.
