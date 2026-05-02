# 📄 Текущая архитектура AI Video Factory (v15.0)

## 1. Обзор проекта

**AI Video Factory** — автоматизированный конвейер создания короткометражного видеоконтента
(YouTube Shorts, Reels, TikTok) от идеи до готового MP4-файла. Управляется через Telegram-бота на aiogram 3.

**Технологический стек:**
| Компонент | Технология |
|-----------|-----------|
| Язык | Python 3.10+ |
| Telegram Bot | aiogram 3.x (FSM, MemoryStorage, middleware) |
| LLM-логика | DeepSeek-V3 через OpenAI SDK (единый клиент `ai/llm_client.py`) |
| Транскрипция | Whisper (openai-whisper, модель base) |
| TTS | Edge-TTS (бесплатно) + Gemini Pro TTS (премиум) |
| Видеомонтаж | MoviePy v2.2+ (CompositeVideoClip, vfx) |
| FFmpeg | Вшивание субтитров, видеоутилиты (через subprocess) |
| Генерация изображений | Imagen 3 (Google Gemini) |
| Хранение проектов | JSON-based (disk-first, `projects/{id}/project.json`) |

---

## 2. Структура директорий

```
├── ai/                        # ИИ-агенты (мозг системы)
│   ├── __init__.py
│   ├── llm_client.py          # Единый клиент DeepSeek (sync + async)
│   ├── script_writer.py       # Генерация сценария
│   ├── storyboarder.py        # Раскадровка (сцены + промпты)
│   ├── timing_agent.py        # Whisper — синхронизация текста с аудио
│   ├── metadata_agent.py      # SEO: заголовки, описания, хештеги
│   ├── montage_agent.py       # Финальная сборка видео (MoviePy)
│   ├── dynamic_scene_agent.py # Рендеринг динамических сцен
│   ├── sound_design_agent.py  # Карта звуковых эффектов (DeepSeek)
│   ├── subtitle_agent.py      # SRT-субтитры + вшивание через FFmpeg
│   ├── localization_agent.py  # Перевод проектов на другие языки
│   ├── tts_edge.py            # Озвучка Microsoft Edge TTS (бесплатно)
│   ├── tts_gemini.py          # Озвучка Gemini Pro TTS (премиум)
│   ├── image_generator.py     # Генерация изображений Imagen 3
│   ├── deepseek_writer.py     # Устаревший (legacy)
│   └── syncer.py              # Устаревший синхронизатор таймингов
│
├── bot/                       # Telegram-интерфейс
│   ├── __init__.py
│   ├── bot_app.py             # Точка входа: Bot, Dispatcher, middleware, routers
│   ├── pipeline_manager.py    # Оркестратор: связывает агентов в конвейер
│   ├── navigation.py          # Навигация между этапами (переходы)
│   ├── states.py              # FSM-состояния (aiogram StatesGroup)
│   ├── middlewares/
│   │   └── errors.py          # Глобальный перехватчик ошибок
│   └── handlers/
│       ├── __init__.py
│       ├── common.py          # /start, /clean, выбор языка/формата
│       ├── scripting.py       # Сценарий + раскадровка
│       ├── assets.py          # Сбор материалов (загрузка/ИИ/URL/динам.сцены)
│       ├── production.py      # Озвучка, стиль монтажа, рендер, субтитры
│       ├── metadata.py        # SEO-метаданные
│       └── localization.py    # Перевод на другие языки
│
├── core/                      # Низкоуровневые движки
│   ├── media_engine.py        # Унифицированный видео-движок (resize, blur, эффекты)
│   ├── project_manager.py     # Disk-first управление проектами (JSON)
│   ├── task_manager.py        # Очередь рендеринга (Singleton + asyncio.Queue)
│   ├── video_utils.py         # FFmpeg-обёртки (инфо, раскадровка, кадры)
│   ├── config_loader.py       # Кешированная загрузка JSON-конфигов
│   ├── animation_utils.py     # Easing-функции и анимационные хелперы
│   └── layer_renderer.py      # Data-driven рендерер слоёв для дин. сцен
│
├── config/                    # JSON-пресеты (data-driven)
│   ├── rendering_presets.json # Стили монтажа: 4 vertical + 3 wide
│   ├── dynamic_scenes.json    # Шаблоны динамических сцен: 7 пресетов
│   ├── script_presets.json    # Режимы и стили сценариев
│   ├── audio_presets.json     # TTS-движки и голосовые пресеты
│   ├── channel_context.json   # Контекст канала (тема, тон, платформа)
│   ├── audio_library.json     # Библиотека звуков и музыки
│   └── ui_plates.json         # Плашки для UI динамических сцен
│
├── tools/                     # CLI-утилиты
│   ├── generate_ui.py         # Генератор PNG-плашек
│   ├── render_dynamic.py      # Автономный рендер дин. сцен
│   ├── render_only.py         # Автономный рендер полного проекта
│   ├── montage_tool.py        # Отладка визуальных эффектов
│   └── tts_test.py            # Тестирование озвучки
│
├── local_assets/ui/           # Предсгенерированные UI-элементы (плашки)
├── projects/                  # Данные проектов (project.json + assets + audio)
├── legacy_engine/             # Старый FFmpeg-движок (не используется)
├── docs/                      # Документация
└── temp/                      # Временные файлы
```

---

## 3. Полный пайплайн (конвейер создания видео)

```
/start
  │
  ├─ Выбор языка (Russian / English / Romanian / Georgian)
  ├─ Выбор формата (vertical 9:16 / wide 16:9)
  │
  ├─ РЕЖИМ СЦЕНАРИЯ
  │   ├─ auto     → AI придумывает сам по теме
  │   ├─ manual   → пользователь даёт готовый текст
  │   └─ hybrid   → AI пишет на основе тезисов
  │
  ├─ СТИЛЬ СЦЕНАРИЯ (news / scientific / narrative / hype)
  ├─ ТЕМА → ScriptWriter (DeepSeek) → script + title + target_duration
  ├─ УТВЕРЖДЕНИЕ текста (можно править → регенерация)
  │
  ├─ РАСКАДРОВКА
  │   ├─ auto  → Storyboarder (DeepSeek) → scenes[]
  │   └─ ideas → пользователь описывает идеи → AI уточняет
  ├─ УТВЕРЖДЕНИЕ раскадровки (можно править → регенерация)
  │
  ├─ СБОР МАТЕРИАЛОВ (покадрово)
  │   ├─ 🤖 Сгенерировать ИИ → Imagen 3
  │   ├─ 🎬 Динамическая сцена → выбор пресета → сбор элементов → рендер
  │   ├─ 📁 Загрузить своё → фото/видео/URL
  │   │   └─ Для видео: выбор стартового момента через раскадровку
  │   └─ ✅ Подтвердить → следующая сцена
  │
  ├─ ОЗВУЧКА
  │   ├─ Выбор TTS-движка (Edge-TTS / Gemini Pro)
  │   ├─ Выбор голосового пресета
  │   ├─ TTS Agent → генерация WAV + ИИ-оптимизация текста
  │   └─ 🎧 Прослушать → утвердить / переделать
  │
  ├─ СТИЛЬ МОНТАЖА
  │   ├─ 4 пресета vertical: Без эффектов / Сторителлинг / Динамичный / Кинематографичный
  │   └─ 3 пресета wide: Без эффектов / Кинематографичный / Влог
  │
  ├─ SEO-МЕТАДАННЫЕ
  │   ├─ Стиль: Виральный / Экспертный / Shorts / Свой промпт
  │   └─ MetadataAgent (DeepSeek) → title, description, hashtags, slug
  │
  ├─ ОЧЕРЕДЬ РЕНДЕРА
  │   ├─ TaskManager ставит проект в asyncio.Queue
  │   ├─ Фоновый воркер обрабатывает по одному
  │   └─ Этапы внутри рендера:
  │       1. SEO-метаданные (если ещё не сгенерированы)
  │       2. TimingAgent (Whisper) — пословная синхронизация
  │       3. SoundDesignAgent — карта звуков
  │       4. MontageAgent (MoviePy) — сборка с эффектами и переходами
  │       5. Опционально: SubtitleAgent (FFmpeg) — субтитры
  │
  └─ ГОТОВОЕ ВИДЕО → отправка пользователю
       └─ Кнопки: 🔥 Субтитры, 🌍 Перевести
```

---

## 4. Система AI-агентов

### 4.1 Полный список агентов

| # | Агент | Файл | Модель | Вход | Выход | Режим |
|---|-------|------|--------|------|-------|-------|
| 1 | **ScriptWriter** | `script_writer.py` | DeepSeek-V3 | topic, language, style | `{title, script, target_duration}` | sync, `asyncio.to_thread` |
| 2 | **Storyboarder** | `storyboarder.py` | DeepSeek-V3 | script, language | `{global_visual_style, scenes[]}` | sync, `asyncio.to_thread` |
| 3 | **TimingAgent** | `timing_agent.py` | Whisper base | audio_path, scenes[] | `scenes[start, end]` | sync thread |
| 4 | **MetadataAgent** | `metadata_agent.py` | DeepSeek-V3 | script, lang, instruction | `{title, description, hashtags, slug}` | async |
| 5 | **MontageAgent** | `montage_agent.py` | MoviePy | scenes[], audio, preset | `.mp4` file | sync thread |
| 6 | **DynamicScene** | `dynamic_scene_agent.py` | MoviePy | preset_id, elements | `.mp4` file | sync thread |
| 7 | **LayerRenderer** | `layer_renderer.py` | MoviePy | layers JSON, elements | `.mp4` file | sync (через d.s.agent) |
| 8 | **SoundDesign** | `sound_design_agent.py` | DeepSeek-V3 | script, scenes[], library | `{bg_music, sfx_placements}` | async |
| 9 | **SubtitleAgent** | `subtitle_agent.py` | FFmpeg | scenes[], whisper_segments | `.srt`, `.mp4` (burned) | sync thread |
| 10 | **Localization** | `localization_agent.py` | DeepSeek-V3 | script, scenes[], metadata, lang | `{script, scenes[], metadata}` | async |
| 11 | **TTS Edge** | `tts_edge.py` | Edge-TTS API | text, voice, rate, pitch | `.wav` file | async |
| 12 | **TTS Gemini** | `tts_gemini.py` | Gemini Pro TTS | task JSON | `.wav` file | sync |
| 13 | **ImageGenerator** | `image_generator.py` | Imagen 3 | prompt | `.png` file | sync |

### 4.2 Детали каждого агента

#### ScriptWriter (`ai/script_writer.py`)
- **Промпт:** Динамический system prompt с контекстом канала (`channel_context.json`)
- **Структура ответа:** `{title, script, target_duration, language_code}`
- **Особенности:** Hook → Context → Fact → Outro структура. ~140 слов/мин. Макс удержание с первых 3 секунд.

#### Storyboarder (`ai/storyboarder.py`)
- **Промпт:** Требует единый визуальный стиль, цветовую палитру, консистентное освещение
- **Структура ответа:** `{global_visual_style, scenes[{scene_id, text_segment, visual_description, image_prompt, ui_caption, estimated_duration}]}`
- **Пост-обработка:** `estimated_duration = max(2.5, len(text)/13.0 + 0.5)`
- **Важно:** `image_prompt` каждой сцены включает style keywords + lighting + hex-цвета палитры

#### TimingAgent (`ai/timing_agent.py`)
- **Модель:** Whisper base, загружается один раз (lazy singleton)
- **Логика:** Сравнивает текст сцен с Whisper-сегментами посегментно. Ищет вхождение через accumulated строки.
- **Особенности:** При ошибке — fallback на равномерное распределение времени (3 сек/сцена)

#### MetadataAgent (`ai/metadata_agent.py`)
- **Промпт:** Включает channel_context + языковую привязку + критичное правило для грузинского (только ქართული, не кириллица)
- **Пост-валидация:** `_validate_language()` проверяет алфавит, `_normalize_hashtags_in_result()` гарантирует что hashtags — массив строк (не одиночная строка)
- **Экспорт:** `format_hashtags()` и `normalize_hashtags()` используются в handlers

#### MontageAgent (`ai/montage_agent.py`)
- **Движки:** `VerticalMontageEngine(1080, 1920)`, `WideMontageEngine(1920, 1080)`
- **Процесс:** Для каждой сцены: `process_asset()` → `with_start()` → `_apply_transition()`
- **Эффекты:** Применяются через `media_engine.apply_preset_effects()` (ken_burns, ken_burns_fast, parallax, pulse)
- **Переходы:** `_apply_transition()` — crossfade, fade_black, blur_dissolve, slide_left/right, zoom_in_out
- **Рендер:** `write_videofile(fps=30, codec="libx264", audio_codec="aac", threads=2-4, preset="veryfast")`

#### DynamicSceneAgent (`ai/dynamic_scene_agent.py`)
- **Два режима:**
  1. **Процедурный** (без `layers`): hardcoded if/elif для `logo_float`, `price_tag`, `split_compare`
  2. **Data-driven** (с `layers`): делегирует в `core/layer_renderer.render_from_layers()`
- **Анимации:** `create_animation_slide()` с ease-out cubic, `logo_pulse_zoom()` с затуханием

#### LayerRenderer (`core/layer_renderer.py`)
- **Типы слоёв:** `media`, `text`, `overlay`, `overlay_with_bg`
- **Анимации:** `fade_in`, `fade_in_up`, `slide_up/down/left/right`, `reveal_from_top`, `scale_in`, `pulse`
- **Позиции:** `"center"`, `{"x": "center", "y": "h*0.65"}`, проценты, пиксели
- **Резолвинг позиций:** `_pos_to_pixels()` + `_resolve_axis()` — конвертирует строки в пиксели

#### SubtitleAgent (`ai/subtitle_agent.py`)
- **Генерация SRT:** `generate_srt_from_project()` — сопоставляет оригинальный текст из сцен с Whisper-таймингами
- **Вшивание:** `burn_subtitles()` — FFmpeg subtitles filter с Arial/Bold/White/Shadow
- **Пропуск дин. сцен:** `if not scene.get('allow_montage_effects', True): continue`

#### LocalizationAgent (`ai/localization_agent.py`)
- **Процесс:** Получает script + scenes + metadata → DeepSeek переводит всё → возвращает структуру
- **Особенности:** Критичное правило для грузинского (без кириллицы). Сбрасывает start/end тайминги.

#### TTS Edge (`ai/tts_edge.py`)
- **Оптимизация текста:** `optimize_text_for_tts()` через DeepSeek — расстановка пауз, ударений, учёт темпа
- **Голоса:** ru-RU-DmitryNeural, en-US-AndrewNeural, ro-RO-EmilNeural, ka-GE-GiorgiNeural
- **Параметры:** rate (+20% / -10%), pitch (+5Hz / -5Hz)

---

## 5. Система пресетов (data-driven)

### 5.1 Пресеты монтажа (`config/rendering_presets.json`)

**Структура пресета:**
```json
{
  "id": "v_smooth_story",
  "name": "📖 Плавный сторителлинг",
  "description": "...",
  "resize_mode": "fit",
  "effects": [
    {"type": "ken_burns", "zoom_from": 1.0, "zoom_to": 1.12, "start_frac": 0.15, "end_frac": 0.75}
  ],
  "transition": {"type": "crossfade", "duration": 0.5}
}
```

**Vertical пресеты (4):**
| ID | Название | Эффекты | Переход |
|----|---------|---------|---------|
| `v_no_effects` | 🚫 Без эффектов | нет | cut |
| `v_smooth_story` | 📖 Плавный сторителлинг | ken_burns (1.0→1.12, 15-75%) | crossfade 0.5s |
| `v_dynamic_shorts` | ⚡ Динамичный Shorts | ken_burns_fast (1.0→1.25, 10-50%) | slide_left 0.3s |
| `v_cinematic_vert` | 🎬 Кинематографичный | ken_burns + parallax | blur_dissolve 0.6s |

**Wide пресеты (3):**
| ID | Название | Эффекты | Переход |
|----|---------|---------|---------|
| `w_no_effects` | 🚫 Без эффектов | нет | cut |
| `w_cinematic` | 🎬 Кинематографичный | ken_burns (1.0→1.12) | crossfade 1.0s |
| `w_vlog_wide` | 📺 Влог / Обзор | нет | crossfade 0.3s |

### 5.2 Динамические сцены (`config/dynamic_scenes.json`)

**7 пресетов:**

| ID | Название | Режим | Элементы |
|----|---------|-------|----------|
| `logo_float` | 🚀 Плавающий логотип | Процедурный | bg, logo |
| `price_tag` | 💎 Акцент на цену | Процедурный | bg, title, price_new, price_old, discount |
| `split_compare` | 🌓 Сравнение Split | Процедурный | left, right |
| `text_reveal` | 🔤 Текстовое раскрытие | Data-driven | bg, title, subtitle |
| `icon_presentation` | 🕊 Иконная презентация | Data-driven | bg, icon, title, description |
| `footage_intro` | 🎬 Футажное интро | Data-driven | bg, logo, headline |
| `product_card` | 🛍 Карточка товара | Data-driven + plate_select | bg, product, title, desc, price_new, discount, plate |

**Все пресеты имеют `allow_montage_effects: false`** — запрещает наложение эффектов монтажа, переходов и субтитров поверх динамических сцен.

### 5.3 Типы эффектов в `media_engine.py`

| Эффект | Тип | Параметры | Описание |
|--------|-----|-----------|----------|
| `ken_burns` | Resize + Position | zoom_from, zoom_to, start_frac, end_frac | Плавный наезд камеры с easing |
| `ken_burns_fast` | Resize + Position | то же, быстрее и резче | Резкий наезд (1.0→1.25 за 10-50% длительности) |
| `parallax` | Resize + Position | direction, strength, start_frac, end_frac | Горизонтальное панорамирование увеличенного кадра |
| `pulse` | LumContrast | frequency, amplitude | Синусоидальная пульсация яркости |

### 5.4 Типы переходов в `montage_agent.py`

| Переход | Тип | Параметры | Описание |
|---------|-----|-----------|----------|
| `crossfade` | CrossFadeIn | duration | Плавное наложение сцен |
| `fade_black` | FadeIn | duration | Появление из чёрного |
| `blur_dissolve` | Blur + FadeIn | duration, blur_strength | Размытие → проявление |
| `slide_left` | Position | duration | Выезд справа налево |
| `slide_right` | Position | duration | Выезд слева направо |
| `zoom_in_out` | Resize + Position | duration, zoom_strength | Зум-переход |
| `cut` | — | — | Мгновенная смена (без перехода) |

---

## 6. Ключевые архитектурные принципы

### 6.1 Disk-First (Единый источник истины)
- `project.json` — единственное хранилище состояния проекта
- FSM-стейты используются только для навигации по меню
- Все handler'ы читают данные из `project.json`, а не из FSM
- `ProjectManager` — единственная точка чтения/записи проектов

### 6.2 Авто-восстановление
- При `/start` бот сканирует `projects/`, находит последний незавершённый проект
- Предлагает пользователю продолжить или создать новый
- Перезагрузка сервера или сброс FSM не приводят к потере прогресса

### 6.3 Очередь рендера (TaskManager)
- Singleton с `asyncio.Queue`
- Один фоновый воркер, обрабатывающий задачи последовательно
- Рендер через `asyncio.to_thread()` — не блокирует event loop
- `MAX_RENDER_THREADS = min(max(2, CPU*0.5), 4)` — макс 4 потока FFmpeg
- Коллбэк после рендера отправляет видео пользователю

### 6.4 Единый LLM-клиент
- `ai/llm_client.py` — все агенты используют его
- `chat_json()` — синхронный вызов + JSON-режим + авто-очистка markdown
- `achat_json()` — асинхронный вариант
- `get_client()` / `get_async_client()` — ленивая инициализация

### 6.5 Кеширование конфигов
- `core/config_loader.py` — in-memory кеш с TTL 300 секунд
- `get_config(name)` — возвращает закешированный или свежий JSON
- `reload_config(name)` — принудительное обновление
- `CONFIG_PATHS` — маппинг имён на пути к файлам

### 6.6 Библиотека анимаций
- `core/animation_utils.py` — easing-функции и анимационные хелперы
- `ease_in_out_cubic`, `ease_out_cubic`, `ease_in_cubic` — easing для плавности
- `ken_burns_zoom()` — зум с easing и окном эффекта
- `parallax_pan_x()` — горизонтальное панорамирование
- `smooth_pulse_lum()` — синусоидальная пульсация яркости
- `logo_pulse_zoom()` — затухающая пульсация для логотипов

---

## 7. Процесс рендеринга (детально)

### 7.1 `render_project_video()` в `pipeline_manager.py`

```
1. Загружает project.json
2. Генерирует SEO-метаданные (если ещё нет)
3. Запускает Whisper для таймингов (если ещё нет)
4. Загружает rendering_presets.json → находит пресет по visual_style
5. Подготавливает scenes_for_agent:
   - Для каждой сцены: проверяет ассет на диске, allow_montage_effects
   - Пропускает сцены без ассетов
6. Запускает SoundDesignAgent (генерирует карту звуков)
7. Вызывает run_montage(scenes, audio, output, preset)
```

### 7.2 `run_montage()` в `montage_agent.py`

```
Для каждой сцены:
  1. process_asset(asset_path, duration, mode, offset, allow_effects, effects)
     ├─ Загрузка VideoFileClip / ImageClip
     ├─ Подрезка / замедление под длительность
     ├─ smart_resize_stable(raw, mode) → CompositeVideoClip[bg, fg]
     │   ├─ mode="fit":  размытый фон + вписанный передний план
     │   └─ mode="cover": заполнение экрана с обрезкой
     ├─ apply_preset_effects(processed, effects)
     │   ├─ ken_burns: pad + Resize(zoom_func) + Position(center_func)
     │   ├─ parallax: pad + Resize + Position(px, center_y)
     │   └─ pulse: LumContrast(sin_func)
     └─ CompositeVideoClip([base, processed])
  2. with_start(start_time) — позиция на таймлайне
  3. _apply_transition() — переход (если не первая сцена)

Финально: CompositeVideoClip([all_clips]) → with_audio(audio) → write_videofile()
```

### 7.3 `render_dynamic_scene()` в `dynamic_scene_agent.py`

```
1. Загружает dynamic_scenes.json → находит пресет
2. Если есть layers → render_from_layers()
   ├─ Для каждого слоя: render_layer()
   │   ├─ Создаёт MoviePy-клип (TextClip / ImageClip / VideoFileClip / ColorClip)
   │   ├─ Применяет анимацию (_animate_position)
   │   └─ Устанавливает позицию (_pos_to_pixels)
   └─ CompositeVideoClip → write_videofile (ultrafast, 30fps)
3. Если нет layers → процедурный рендер (hardcoded)
```

---

## 8. FSM-состояния (`bot/states.py`)

```python
class ProjectStates(StatesGroup):
    choosing_language = State()         # Выбор языка
    choosing_format = State()           # Выбор формата
    choosing_script_mode = State()      # Режим сценария
    choosing_script_style = State()     # Стиль сценария
    writing_topic = State()             # Ввод темы
    writing_manual_script = State()     # Ручной ввод текста
    approving_script = State()          # Утверждение сценария
    choosing_storyboard_mode = State()  # Режим раскадровки
    refining_storyboard = State()       # Правка раскадровки
    approving_scenes = State()          # Утверждение сцен
    collecting_assets = State()         # Сбор материалов
    waiting_for_asset = State()         # Ожидание файла
    selecting_video_offset = State()    # Выбор момента в видео
    approving_asset = State()           # Подтверждение ассета
    choosing_dynamic_preset = State()   # Выбор дин. пресета
    collecting_dynamic_element = State()# Сбор элементов дин. сцены
    approving_dynamic_pre_render = State()# Утверждение рендера дин. сцены
    choosing_visual_style = State()     # Выбор стиля монтажа
    choosing_tts_engine = State()       # Выбор TTS-движка
    choosing_tts_preset = State()       # Выбор голоса
    choosing_metadata_style = State()   # Выбор стиля метаданных
    waiting_for_metadata_prompt = State()# Ввод промпта для SEO
    assembling_video = State()          # Финальная сборка
    approving_audio = State()           # Утверждение озвучки
    rendering = State()                 # Рендеринг
```

---

## 9. Модель данных `project.json`

```json
{
  "project_id": "proj_2026-05-02_22-57-10",
  "user_id": "123456789",
  "created_at": "2026-05-02T22:57:10",
  "updated_at": "2026-05-02T23:15:00",
  "status": "completed",
  "video_format": "vertical",
  "language": "Russian",
  "script": "Полный текст сценария...",
  "scenes": [
    {
      "scene_id": 1,
      "text_segment": "Часть текста для этой сцены",
      "visual_description": "Что показываем на экране",
      "image_prompt": "Детальный промпт для генерации изображения...",
      "ui_caption": "Короткая подпись",
      "estimated_duration": 4.5,
      "start": 0.0,
      "end": 4.5
    }
  ],
  "assets": {
    "0": {
      "path": "projects/proj_.../assets/scene_0.jpg",
      "original_path": "temp/...",
      "type": "image",
      "start_offset": 0,
      "allow_montage_effects": true
    }
  },
  "visual_style": "v_smooth_story",
  "metadata": {
    "title": "Заголовок видео",
    "description": "Описание",
    "hashtags": ["#наука", "#факты"],
    "slug": "video-slug"
  },
  "current_audio_path": "projects/proj_.../audio/voice_Russian.wav",
  "whisper_segments": [
    {"start": 0.0, "end": 1.5, "text": "транскрибированный текст"}
  ],
  "video_result_path": "projects/proj_.../video-slug.mp4",
  "burn_subtitles": false,
  "parent_project_id": null
}
```

---

## 10. Обработка ошибок и отказоустойчивость

- **ErrorHandlingMiddleware** (`bot/middlewares/errors.py`): перехватывает все необработанные исключения в handler'ах, логирует и уведомляет пользователя
- **Download Retries** (`assets.py:download_with_retry`): до 3 попыток скачивания файлов из Telegram с растущей задержкой
- **Safe Edit** (`navigation.py`, `metadata.py`): проверка типа сообщения перед `edit_text`/`edit_caption`
- **Fallback в агентах**: при ошибке API возвращаются значения по умолчанию (MetadataAgent, SoundDesignAgent)
- **process_asset fallback**: при ошибке обработки медиа возвращается чёрный ColorClip вместо краша
- **TimingAgent fallback**: при ошибке Whisper — равномерное распределение времени

---

*Документация актуальна на 2026-05-02. Версия проекта: 15.0*
