# 📄 Текущая архитектура Content Factory (v16.0)

## 1. Обзор проекта

**Content Factory** — автоматизированный конвейер создания короткометражного видеоконтента
(YouTube Shorts, Reels, TikTok) от идеи до готового MP4. Управляется через Telegram-бота на aiogram 3.

**Технологический стек:**
| Компонент | Технология |
|-----------|-----------|
| Язык | Python 3.10+ |
| Telegram Bot | aiogram 3.x (FSM, MemoryStorage, ErrorHandlingMiddleware) |
| LLM-логика | DeepSeek-V3 через OpenAI SDK (единый клиент `ai/llm_client.py`) |
| Транскрипция | Whisper (openai-whisper, модель base) |
| TTS | Edge-TTS (бесплатно) + Gemini Pro TTS (премиум) |
| Видеомонтаж | MoviePy v2.2+ (CompositeVideoClip, vfx, AudioClip) |
| FFmpeg | Выжигание субтитров, видеоутилиты (subprocess) |
| Поиск изображений | Pexels API + Pixabay API + Pollinations AI |
| Генерация изображений | Imagen 3 (Google Gemini) |
| Хранение проектов | JSON-based (disk-first, `projects/{id}/project.json`) |

---

## 2. Структура директорий

```
├── ai/                        # ИИ-агенты (мозг системы)
│   ├── llm_client.py          # Единый клиент DeepSeek (sync + async)
│   ├── script_writer.py       # Генерация сценария
│   ├── script_reviewer.py     # Проверка сценария (4-бальная оценка)
│   ├── storyboarder.py        # Раскадровка (сцены + промпты)
│   ├── timing_agent.py        # Whisper — синхронизация текста с аудио
│   ├── llm_aligner.py         # LLM-выравнивание слов с Whisper-сегментами
│   ├── metadata_agent.py      # SEO: заголовки, описания, хештеги
│   ├── montage_agent.py       # Финальная сборка видео (MoviePy)
│   ├── montage_director_agent.py # ИИ-режиссёр (распределяет эффекты по сценам)
│   ├── dynamic_scene_agent.py # Рендеринг динамических сцен
│   ├── sound_design_agent.py  # Карта звуков + фоновая музыка (DeepSeek)
│   ├── subtitle_agent.py      # ASS/SRT-субтитры + вшивание через FFmpeg
│   ├── localization_agent.py  # Перевод проектов на другие языки
│   ├── preview_agent.py       # Генерация превью-текста (2-4 слова)
│   ├── preview_designer_agent.py # Подбор цветовой палитры для превью
│   ├── image_search_agent.py  # Поиск картинок (Pexels + Pixabay + AI)
│   ├── tts_edge.py            # Озвучка Microsoft Edge TTS (бесплатно)
│   ├── tts_gemini.py          # Озвучка Gemini Pro TTS (премиум)
│   ├── image_generator.py     # Генерация изображений Imagen 3
│   ├── whisper_agent.py       # Обёртка Whisper с word_timestamps
│   └── syncer.py              # Устаревший (legacy)
│
├── bot/                       # Telegram-интерфейс
│   ├── bot_app.py             # Точка входа: Bot, Dispatcher, middleware, routers
│   ├── pipeline_manager.py    # Оркестратор: связывает агентов в конвейер
│   ├── navigation.py          # Навигация между этапами (переходы)
│   ├── states.py              # FSM-состояния (aiogram StatesGroup)
│   ├── middlewares/errors.py  # Глобальный перехватчик ошибок
│   └── handlers/
│       ├── common.py          # /start, /render_audio, /clean, выбор языка/формата
│       ├── scripting.py       # Сценарий + раскадровка + рецензент
│       ├── production.py      # Озвучка, стиль монтажа, рендер, субтитры
│       ├── metadata.py        # SEO-метаданные
│       ├── localization.py    # Перевод на другие языки
│       ├── scene_builder.py   # Автономный конструктор сцен (/scene)
│       └── assets/            # Сбор материалов
│           ├── ai_gen.py      # AI-генерация изображений
│           ├── dynamic.py     # Динамические сцены
│           ├── manual.py      # Ручная загрузка файлов
│           └── web_search.py  # Веб-поиск по стокам
│
├── core/                      # Низкоуровневые движки
│   ├── media_engine.py        # Унифицированный видео-движок (resize, blur, эффекты)
│   ├── effects.py             # Dispatch-таблица эффектов (plugin-архитектура)
│   ├── transitions.py         # Dispatch-таблица переходов (plugin-архитектура)
│   ├── preview_renderer.py    # Рендеринг превью-оверлея
│   ├── project_manager.py     # Disk-first управление проектами (JSON)
│   ├── task_manager.py        # Очередь рендеринга (Singleton + asyncio.Queue)
│   ├── video_utils.py         # FFmpeg-обёртки
│   ├── config_loader.py       # Кешированная загрузка JSON-конфигов
│   ├── animation_utils.py     # Easing-функции и анимационные хелперы
│   └── layer_renderer.py      # Data-driven рендерер слоёв
│
├── config/                    # JSON-пресеты (data-driven)
│   ├── rendering_presets.json # Стили монтажа
│   ├── effects_registry.json  # Реестр эффектов (14 эффектов)
│   ├── transitions_registry.json # Реестр переходов (10 переходов)
│   ├── music_library.json     # Библиотека фоновой музыки
│   ├── audio_presets.json     # TTS-движки и голосовые пресеты
│   ├── audio_library.json     # Библиотека звуковых эффектов
│   ├── script_presets.json    # Режимы и стили сценариев
│   ├── dynamic_scenes.json    # Шаблоны динамических сцен
│   ├── channel_context.json   # Контекст канала (тема, тон, платформа)
│   ├── preview_presets.json   # Настройки превью
│   └── ui_plates.json         # Плашки для UI динамических сцен
│
├── tools/                     # CLI-утилиты
│   ├── tts_test.py            # Тестирование озвучки
│   ├── tts_generator.py       # Gemini TTS генератор
│   ├── render_only.py         # Автономный рендер полного проекта
│   ├── local_render.py        # Локальный рендер с прогрессом
│   ├── montage_tool.py        # Отладка визуальных эффектов
│   ├── render_dynamic.py      # Автономный рендер дин. сцен
│   ├── generate_ui.py         # Генератор PNG-плашек
│   ├── init_assets.py         # Инициализация ассетов
│   ├── populate_audio.py      # Загрузчик CC0 аудио
│   └── populate_v3.py         # yt-dlp аудио-загрузчик
│
└── docs/                      # Документация
```

---

## 3. Полный пайплайн (конвейер создания видео)

```
/start
  │
  ├─ Выбор языка
  ├─ Выбор профиля канала
  ├─ Выбор формата (vertical / wide)
  │
  ├─ РЕЖИМ СЦЕНАРИЯ
  │   ├─ auto     → AI придумывает сам по теме
  │   ├─ manual   → пользователь даёт готовый текст
  │   └─ hybrid   → AI пишет на основе тезисов
  │
  ├─ СТИЛЬ СЦЕНАРИЯ (theology_architect / sacred_storyteller / it_b2b_architect)
  ├─ ТЕМА → ScriptWriter (DeepSeek) → script + title + target_duration
  ├─ ScriptReviewer → оценка (0-20), автоперегенерация при <14
  ├─ УТВЕРЖДЕНИЕ текста
  │
  ├─ ВЫБОР ТЕМПА (super_dynamic / normal / slow)
  ├─ Storyboarder (DeepSeek) → scenes[] с estimated_duration
  ├─ УТВЕРЖДЕНИЕ раскадровки
  │
  ├─ СБОР МАТЕРИАЛОВ (покадрово)
  │   ├─ 🤖 Веб-поиск по стокам (Pexels + Pixabay + AI)
  │   ├─ 🎬 Динамическая сцена
  │   ├─ 📁 Загрузить своё
  │   └─ ✅ Подтвердить → следующая сцена
  │
  ├─ ОЗВУЧКА
  │   ├─ Выбор TTS-движка + голоса
  │   ├─ TTS Edge/Gemini → генерация WAV
  │   └─ 🎧 Прослушать → утвердить / переделать
  │
  ├─ ГЕНЕРАЦИЯ ПРЕВЬЮ
  │   ├─ PreviewAgent (DeepSeek) → 2-4 слова
  │   ├─ PreviewDesigner → цветовая палитра из кадра
  │   └─ УТВЕРЖДЕНИЕ превью / регенерация
  │
  ├─ СТИЛЬ МОНТАЖА (авто-подбор под канал + AI-режиссёр)
  ├─ SEO-МЕТАДАННЫЕ
  │
  ├─ РЕНДЕР (TaskManager → фоновый воркер)
  │   1. SEO-метаданные
  │   2. Whisper → LLM-aligner → точные тайминги слов
  │   3. AI Director → per-scene эффекты + переходы
  │   4. SoundDesign → фоновая музыка + SFX
  │   5. MontageAgent (MoviePy) → сборка
  │   6. SubtitleAgent (FFmpeg) → выжигание субтитров
  │
  └─ ГОТОВОЕ ВИДЕО → отправка пользователю
```

### Альтернативный вход: `/render_audio` (аудио-first)

```
/render_audio
  ├─ Выбор языка
  ├─ Принять текст от пользователя
  ├─ TTS → генерация аудио → утверждение
  ├─ Выбор профиля канала
  ├─ Выбор формата
  ├─ Выбор темпа → раскадровка → сбор → стиль → рендер
```

### Перевод (локализация)

```
1. translate_project_content (DeepSeek) → перевод script + scenes + metadata
2. clone_project → создание копии с mirror_assets: true
3. recalc_scene_durations → пересчёт длительностей под новый язык
4. PreviewAgent → генерация превью на целевом языке
5. Одобрение превью → TTS → рендер (с новым Whisper + LLM-aligner)
```

---

## 4. Система AI-агентов

### 4.1 Полный список агентов

| # | Агент | Файл | Модель | Режим |
|---|-------|------|--------|-------|
| 1 | **ScriptWriter** | `script_writer.py` | DeepSeek-V3 | sync thread |
| 2 | **ScriptReviewer** | `script_reviewer.py` | DeepSeek-V3 | async |
| 3 | **Storyboarder** | `storyboarder.py` | DeepSeek-V3 | sync thread |
| 4 | **PreviewAgent** | `preview_agent.py` | DeepSeek-V3 | async |
| 5 | **PreviewDesigner** | `preview_designer_agent.py` | DeepSeek-V3 | async |
| 6 | **MontageDirector** | `montage_director_agent.py` | DeepSeek-V3 | async |
| 7 | **ImageSearch** | `image_search_agent.py` | DeepSeek-V3 + Pexels/Pixabay | async |
| 8 | **WhisperAgent** | `whisper_agent.py` | Whisper + word_timestamps | sync thread |
| 9 | **LLMAligner** | `llm_aligner.py` | DeepSeek-V3 | async |
| 10 | **TimingAgent** | `timing_agent.py` | Whisper base | sync thread |
| 11 | **MetadataAgent** | `metadata_agent.py` | DeepSeek-V3 | async |
| 12 | **SoundDesign** | `sound_design_agent.py` | DeepSeek-V3 | async |
| 13 | **Localization** | `localization_agent.py` | DeepSeek-V3 | async |
| 14 | **MontageAgent** | `montage_agent.py` | MoviePy v2 | sync thread |
| 15 | **DynamicScene** | `dynamic_scene_agent.py` | MoviePy v2 | sync thread |
| 16 | **SubtitleAgent** | `subtitle_agent.py` | FFmpeg | sync thread |
| 17 | **TTS Edge** | `tts_edge.py` | Edge-TTS API | async |
| 18 | **TTS Gemini** | `tts_gemini.py` | Gemini Pro TTS | sync |

### 4.2 Plugin-архитектура эффектов и переходов

**Эффекты** (`core/effects.py`):
- Dispatch-таблица `CONTENT_EFFECTS` + `OVERLAY_EFFECTS`
- Регистрация через декоратор `@register`
- Список в `config/effects_registry.json` (14 эффектов)
- Категории: zoom, glitch, color, motion, atmosphere

**Переходы** (`core/transitions.py`):
- Dispatch-таблица `TRANSITIONS`
- Регистрация через декоратор `@register`
- Список в `config/transitions_registry.json` (10 переходов)
- Категории: standard, cinematic, dynamic, glitch

**AI Director** (`montage_director_agent.py`):
- Генерирует промпт динамически из реестров + channel_profile + pacing
- Фильтрует эффекты по channel_tags и min_scene_duration
- Пост-валидация: не более 3 одинаковых переходов подряд, минимум разных типов

---

## 5. Система пресетов (data-driven)

### 5.1 Конфиги (11 файлов)

| Файл | Назначение |
|------|-----------|
| `rendering_presets.json` | Стили монтажа с mode="ai" для AI-управляемых |
| `effects_registry.json` | Реестр 14 visual-эффектов с параметрами, channel_tags |
| `transitions_registry.json` | Реестр 10 переходов с параметрами, channel_tags |
| `music_library.json` | 8 фоновых треков с mood, tempo, channel_tags, blacklist |
| `audio_presets.json` | TTS-движки и голосовые пресеты Edge + Gemini |
| `audio_library.json` | SFX-библиотека по категориям |
| `script_presets.json` | 3 стиля сценариев + 3 режима pacing |
| `channel_context.json` | 4 профиля канала (educational, orthodox, tech_business, entertainment) |
| `dynamic_scenes.json` | 7 шаблонов динамических сцен |
| `preview_presets.json` | Стилизация превью (font_size, glass, text_colors, gradient) |
| `ui_plates.json` | PNG-плашки для UI |

### 5.2 Типы эффектов

| Эффект | Категория | Слой | Каналы |
|--------|-----------|------|--------|
| `ken_burns` | zoom | content | all |
| `ken_burns_fast` | zoom | content | tech, entertainment |
| `ken_burns_pan` | zoom | content | orthodox, tech, women |
| `snap_zoom` | zoom | content | tech, entertainment |
| `zoom_out_reveal` | zoom | content | orthodox, women |
| `chromatic_aberration` | color | content | orthodox, tech |
| `drift` | motion | content | orthodox, women |
| `parallax` | motion | content | all |
| `pulse` | color | content | tech, entertainment |
| `shake_decay` | motion | content | tech, entertainment |
| `glitch_rgb_split` | glitch | content | tech |
| `glitch_block_shift` | glitch | content | tech, entertainment |
| `light_leak` | atmosphere | overlay | orthodox, women |
| `vignette_breathe` | atmosphere | overlay | orthodox, women |

### 5.3 Типы переходов

| Переход | Категория | Каналы |
|---------|-----------|--------|
| `crossfade`, `fade_black` | standard | all |
| `blur_dissolve` | cinematic | orthodox, women |
| `slide_left/right/up/down` | dynamic | tech, entertainment |
| `zoom_in_out` | dynamic | tech, entertainment |
| `glitch_transition` | glitch | tech, entertainment |
| `whip_pan` | dynamic | tech, entertainment |

---

## 6. FSM-состояния

```python
class ProjectStates(StatesGroup):
    choosing_language = State()
    choosing_channel_profile = State()
    choosing_format = State()
    choosing_script_mode = State()
    choosing_script_style = State()
    writing_topic = State()
    writing_manual_script = State()
    approving_script = State()
    choosing_storyboard_mode = State()
    choosing_scene_pacing = State()
    refining_storyboard = State()
    collecting_assets = State()
    waiting_for_asset = State()
    selecting_video_offset = State()
    approving_asset = State()
    providing_script_for_audio = State()  # для /render_audio
    choosing_dynamic_preset = State()
    collecting_dynamic_element = State()
    approving_dynamic_pre_render = State()
    choosing_visual_style = State()
    approving_preview = State()
    choosing_tts_engine = State()
    choosing_tts_preset = State()
    choosing_metadata_style = State()
    waiting_for_metadata_prompt = State()
    approving_audio = State()
    uploading_audio = State()
    assembling_video = State()
    rendering = State()
```

---

## 7. Ключевые архитектурные принципы

### 7.1 Disk-First
- `project.json` — единственное хранилище состояния проекта
- FSM-стейты используются только для навигации
- `ProjectManager` — единственная точка чтения/записи

### 7.2 Многоязычность
- Script, scenes, metadata переводятся через `localization_agent.py`
- Whisper / Edge TTS поддерживают Russian, English, Romanian, Georgian
- При переводе: clone → mirror_assets → пересчёт таймингов → LLM-aligner

### 7.3 Безопасность контента
- `mirror_assets: true` — горизонтальное зеркалирование для переводов
- `channel_blacklist` в music_library — запрет нерелевантной музыки для каналов
- `script_reviewer` — 4-бальная оценка качества сценария

### 7.4 Очередь рендера
- Singleton `TaskManager` с `asyncio.Queue`
- Один фоновый воркер, задачи последовательно
- `MAX_RENDER_THREADS = min(max(2, CPU*0.5), 4)`
- Коллбэк после рендера отправляет видео

### 7.5 Music Library
- 8 треков с mood, tempo, energy, channel_tags, channel_blacklist
- `priority_for` — рекомендуемый трек для канала
- Циклическое воспроизведение с fade-out → gap → fade-in

---

## 8. История версий

| Версия | Дата | Ключевые изменения |
|--------|------|-------------------|
| v10.0 | — | Базовая версия: скрипт → storyboard → TTS → монтаж |
| v15.0 | 2026-05-02 | Disk-First, Disk persistence, ProjectManager |
| v16.0 | 2026-05-14 | 14 эффектов, 10 переходов, music library, LLM-aligner, |
| | | script reviewer, preview agent, channel profiles, |
| | | audio-first flow, mirror_assets, subtitle karaoke |
