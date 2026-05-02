# 📄 План Scheduler Bot (Планировщик контента)

## 1. Цель

Создать второго Telegram-бота, который планирует 15–30 видео вперёд по одной теме,
проходит через всех ИИ-агентов и создаёт готовые `project.json` на диске для рендера
основным ботом.

**Ключевые возможности:**
- Мульти-канальные конфиги — разные темы/тональности для разных каналов
- Форматные шаблоны — структура видео (интро + N статичных сцен + динамическая сцена)
- Система персонажей — AI-персонажи с consistent-визуалом, persist через всю серию
- Переиспользование ассетов — общий пул медиа между видео
- Параметризованные динамические сцены — один пресет, разные параметры (фото, текст)

---

## 2. Архитектурная схема

```
┌──────────────────────────────────────────────────────────────────┐
│                    SCHEDULER BOT (новый экземпляр)                 │
│                    bot/scheduler_app.py                            │
│                    Токен: SCHEDULER_BOT_TOKEN                      │
├──────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ ChannelManager    │  │ CharacterGenerator│  │ SeriesPlanner  │  │
│  │ (конфиги каналов) │  │ (персонажи на     │  │ (план серии)   │  │
│  │ channels.json     │  │  всю серию)       │  │                │  │
│  └────────┬─────────┘  └────────┬─────────┘  └───────┬────────┘  │
│           │                     │                     │            │
│  ┌────────┴─────────────────────┴─────────────────────┴────────┐  │
│  │                    FORMAT ENGINE                             │  │
│  │   config/schedule_formats.json → структура сцен для видео    │  │
│  └──────────────────────────────┬───────────────────────────────┘  │
│                                 │                                  │
│  ┌──────────────────────────────┴───────────────────────────────┐  │
│  │                    BATCH SCRIPT WRITER                       │  │
│  │   ai/batch_script_writer.py                                  │  │
│  │   Для каждого эпизода:                                        │  │
│  │     script_writer.generate_script()   ← переиспользует       │  │
│  │     storyboarder.generate_storyboard() ← переиспользует      │  │
│  └──────────────────────────────┬───────────────────────────────┘  │
│                                 │                                  │
│  ┌──────────────────────────────┴───────────────────────────────┐  │
│  │                    ASSET POOL MANAGER                        │  │
│  │   ai/asset_pool_manager.py                                   │  │
│  │   config/asset_pools.json → общие ассеты для всех видео      │  │
│  └──────────────────────────────┬───────────────────────────────┘  │
│                                 │                                  │
│  ┌──────────────────────────────┴───────────────────────────────┐  │
│  │                    PROJECT FACTORY                           │  │
│  │   core/project_factory.py                                    │  │
│  │   Создаёт project.json для каждого видео на диске            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼  (projects/ на диске)
┌──────────────────────────────────────────────────────────────────┐
│                    ОСНОВНОЙ BOT (без изменений)                   │
│                    bot/bot_app.py                                 │
│   Видит projects со статусом "scheduled" → рендерит по очереди   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Новые файлы и модули

### 3.1 Новые AI-агенты

| # | Агент | Файл | Модель | Назначение |
|---|-------|------|--------|------------|
| 14 | **SeriesPlanner** | `ai/series_planner.py` | DeepSeek-V3 | Разбивает тему на N подтем (эпизодов) с логическими связями |
| 15 | **CharacterGenerator** | `ai/character_generator.py` | DeepSeek-V3 + Imagen 3 | Создаёт персонажа: имя, внешность, seed-фото. Генерирует промпты для consistent-изображений |
| 16 | **BatchScriptWriter** | `ai/batch_script_writer.py` | DeepSeek-V3 | Массово генерирует сценарии для N видео, переиспользуя существующие script_writer + storyboarder |
| 17 | **AssetPoolManager** | `ai/asset_pool_manager.py` | Логика (без AI) | Управляет пулом общих ассетов: маппинг «роль сцены → файл», переиспользование |

### 3.2 Новые модули Core

| Файл | Назначение |
|------|------------|
| `core/project_factory.py` | Создаёт project.json для одного видео: скрипт → раскадровка → ассеты → метаданные → сохранение |
| `core/channel_manager.py` | Загружает `config/channels.json`, управляет переключением контекста между каналами |
| `core/format_engine.py` | Разбирает `config/schedule_formats.json`, генерирует структуру сцен с типами и ролями |

### 3.3 Новый бот

| Файл | Назначение |
|------|------------|
| `bot/scheduler_app.py` | Точка входа второго бота. Отдельный Bot + Dispatcher, свой токен |
| `bot/handlers/scheduler.py` | Хендлеры: `/schedule`, `/characters`, `/formats`, `/channels` |

### 3.4 Новые конфиги

| Файл | Назначение |
|------|------------|
| `config/channels.json` | Мульти-канальные контексты (тема, тон, стиль, формат, пул персонажей) |
| `config/schedule_formats.json` | Форматные шаблоны: структура видео (типы сцен, роли, длительности, дин. пресеты с параметрами) |
| `config/asset_pools.json` | Пулы переиспользуемых ассетов с маппингом ролей |
| `config/character_pools/{pool_id}.json` | Пулы персонажей (один JSON на пул) |

### 3.5 Новые директории

| Путь | Назначение |
|------|------------|
| `local_assets/characters/` | Seed-фото и референсы персонажей |
| `local_assets/pools/` | Общие ассеты для переиспользования между видео |

---

## 4. Детальное описание новых агентов

### 4.1 SeriesPlanner (`ai/series_planner.py`)

**Задача:** Разбить глобальную тему на N логически связанных эпизодов.

**Сигнатура:**
```python
async def plan_series(
    topic: str,
    count: int,
    channel_config: dict,
    format_template: dict
) -> dict
```

**Промпт (передаётся в chat_json):**
```
You are a YouTube series planner.
TOPIC: {topic}
CHANNEL: {channel_config.topic}, tone: {channel_config.tone}, target: {channel_config.platform}
TARGET: {count} episodes, each ~60 seconds
FORMAT: {format_template.description}, total scenes per video: {total_scenes}

Generate a series plan as JSON:
{
  "series_title": "overall series name",
  "episodes": [
    {
      "episode": 1,
      "title": "catchy episode title",
      "subtopic": "specific subtopic for this episode",
      "hook": "opening hook sentence (3-5 seconds)",
      "connection": "how this connects to previous/next episode (null for first)"
    },
    ...
  ]
}
```

**Выход:** JSON с планом всей серии — `{series_title, episodes[{episode, title, subtopic, hook, connection}]}`.

**Связь с другими агентами:** Выход `SeriesPlanner` подаётся в `BatchScriptWriter` как контекст.
Каждый эпизод содержит `subtopic`, который `BatchScriptWriter` использует как `topic`
для вызова `script_writer.generate_script()`.

---

### 4.2 CharacterGenerator (`ai/character_generator.py`)

**Задача:** Создать персонажа, который будет фигурировать во всех эпизодах серии,
с consistent визуальным представлением.

**Сигнатура:**
```python
async def generate_character(
    brief: str,                          # "православный святой", "учёный-физик"
    reference_photo_path: str = None,    # путь к реальному фото
    pool_id: str = None                  # ID пула персонажей
) -> dict
```

**Процесс (2 этапа):**

**Этап 1 — LLM генерирует описание:**
```
Generate a detailed character description for a video series.
Character type: {brief}

Return JSON:
{
  "name": "character name",
  "appearance": "detailed physical description — face, hair, clothing, age, build",
  "style_keywords": "art style keywords for consistent image generation",
  "seed_prompt": "detailed image generation prompt for the character's portrait photo",
  "scene_context": "how to describe this character in various scenes"
}
```

**Этап 2 — Генерация seed-фото:**
```python
from ai.image_generator import generate_image
seed_path = f"local_assets/characters/{character_id}_seed.png"
generate_image(description["seed_prompt"], seed_path)
```

**Интеграция в сцены:**
Когда `BatchScriptWriter` генерирует сцены для эпизода, для каждой сцены где нужен персонаж,
в `image_prompt` добавляется префикс:
```
"{style_keywords}. {seed_prompt}. Character MUST look exactly like: {appearance}. {scene_context}. {scene_specific_description}"
```

Это обеспечивает визуальную консистентность персонажа через все сцены и эпизоды.

**Выход:** `{id, name, appearance, style_keywords, seed_prompt, seed_photo_path}`

---

### 4.3 BatchScriptWriter (`ai/batch_script_writer.py`)

**Задача:** Массово сгенерировать сценарии и раскадровки для всех эпизодов серии,
переиспользуя существующих агентов `script_writer` и `storyboarder`.

**Сигнатура:**
```python
async def generate_batch(
    series_plan: dict,           # выход SeriesPlanner
    channel_config: dict,        # конфиг канала
    format_template: dict,       # форматный шаблон
    characters: list = None,     # список персонажей
    language: str = "Russian"
) -> list[dict]                  # список project_data для каждого эпизода
```

**Процесс (для каждого эпизода):**

```python
for episode in series_plan["episodes"]:
    # 1. Генерируем сценарий
    script_data = await asyncio.to_thread(
        script_writer.generate_script,
        topic=episode["subtopic"],
        language=language,
        duration=60
    )
    
    # 2. Генерируем раскадровку
    storyboard_data = await asyncio.to_thread(
        storyboarder.generate_storyboard,
        script=script_data["script"],
        language=language
    )
    
    # 3. Обогащаем сцены персонажами
    if characters:
        for scene in storyboard_data["scenes"]:
            char = characters[0]  # или выбор по роли
            scene["image_prompt"] = (
                f"{char['style_keywords']}. {char['seed_prompt']}. "
                f"MUST look exactly like: {char['appearance']}. "
                f"{scene['image_prompt']}"
            )
    
    # 4. Применяем форматный шаблон
    scenes = apply_format_template(storyboard_data["scenes"], format_template)
    
    # 5. Собираем данные проекта
    project_data = {
        "script": script_data["script"],
        "scenes": scenes,
        "visual_style": format_template.get("visual_style", "v_no_effects"),
        "metadata_style": format_template.get("metadata_style", "edu"),
        "tts_preset_id": format_template.get("tts_preset"),
        "characters": [c["id"] for c in characters] if characters else []
    }
    
    results.append(project_data)
```

**Выход:** Список словарей `project_data`, готовых для `ProjectFactory`.

---

### 4.4 AssetPoolManager (`ai/asset_pool_manager.py`)

**Задача:** Управлять переиспользованием ассетов между видео в серии.

**Конфиг:** `config/asset_pools.json`
```json
{
  "pool_science_bg": {
    "name": "🔬 Научные фоны",
    "assets": {
      "hook": "local_assets/pools/science/lab_bg.mp4",
      "body": "local_assets/pools/science/dna_helix.jpg",
      "outro": "local_assets/pools/science/stars_bg.mp4"
    }
  },
  "pool_orthodox_bg": {
    "name": "☦️ Православные фоны",
    "assets": {
      "hook": "local_assets/pools/orthodox/church_bg.mp4",
      "body": "local_assets/pools/orthodox/icon_bg.jpg",
      "outro": "local_assets/pools/orthodox/candles_bg.mp4"
    }
  }
}
```

**Сигнатура:**
```python
class AssetPoolManager:
    def __init__(self):
        self.pools = {}  # загружается из config/asset_pools.json
    
    def get_asset(self, pool_id: str, role: str) -> str | None:
        """Возвращает путь к ассету для указанной роли из пула."""
        pool = self.pools.get(pool_id, {})
        return pool.get("assets", {}).get(role)
    
    def assign_to_project(self, project_id: str, scenes: list, pool_id: str, format_template: dict):
        """Назначает ассеты из пула сценам проекта на основе их ролей."""
```

**Логика:**
- Для каждой сцены смотрит её `role` (из форматного шаблона)
- Если в пуле есть ассет для этой роли → копирует его в `projects/{id}/assets/`
- Если нет → оставляет пустым (пользователь загрузит сам или AI сгенерирует)
- Один и тот же файл может копироваться в несколько проектов

---

## 5. Новые модули Core

### 5.1 ProjectFactory (`core/project_factory.py`)

**Задача:** Создать один `project.json` со всеми данными, пройдя через всех агентов.

**Сигнатура:**
```python
async def create_project(
    episode_data: dict,         # из SeriesPlanner.episodes[i]
    channel_config: dict,       # из channels.json
    format_template: dict,      # из schedule_formats.json
    batch_result: dict,         # из BatchScriptWriter (script + scenes)
    characters: list = None,    # из CharacterGenerator
    asset_pool_id: str = None,  # ID пула ассетов
) -> str:                       # возвращает project_id
```

**Процесс:**
```python
async def create_project(episode_data, channel_config, format_template, batch_result, characters=None, asset_pool_id=None):
    # 1. Создаём базовый проект
    pm = ProjectManager()
    project_id = f"proj_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{episode_data['episode']:03d}"
    proj = pm.create_project(project_id, user_id="scheduler")
    
    # 2. Заполняем сценарий и сцены
    proj["script"] = batch_result["script"]
    proj["scenes"] = batch_result["scenes"]
    
    # 3. Применяем форматный шаблон
    proj["visual_style"] = format_template.get("visual_style", "v_no_effects")
    proj["video_format"] = format_template.get("video_format", "vertical")
    proj["language"] = channel_config.get("language", "Russian")
    
    # 4. Назначаем ассеты из пула
    if asset_pool_id:
        pool_mgr = AssetPoolManager()
        pool_mgr.assign_to_project(project_id, proj["scenes"], asset_pool_id, format_template)
    
    # 5. Сохраняем параметры динамических сцен
    for scene in proj["scenes"]:
        if scene.get("type") == "dynamic":
            scene["preset_id"] = scene.get("preset")
            scene["preset_params"] = scene.get("params", {})
    
    # 6. Генерируем SEO-метаданные
    meta = await generate_metadata(
        proj["script"],
        proj["language"],
        user_instruction=format_template.get("metadata_style_instruction", "")
    )
    proj["metadata"] = meta
    
    # 7. Сохраняем TTS-пресет
    proj["tts_preset_id"] = format_template.get("tts_preset", "edge_male_fast")
    
    # 8. Ставим статус
    proj["status"] = "scheduled"
    proj["parent_series"] = episode_data.get("series_title")
    proj["episode_number"] = episode_data["episode"]
    
    pm.save_project(project_id, proj)
    return project_id
```

### 5.2 ChannelManager (`core/channel_manager.py`)

```python
class ChannelManager:
    def __init__(self, config_path="config/channels.json"):
        self.config = get_config("channels")  # нужно добавить в CONFIG_PATHS
    
    def get_channel(self, channel_id: str) -> dict:
        for ch in self.config.get("channels", []):
            if ch["id"] == channel_id:
                return ch
        return None
    
    def list_channels(self) -> list:
        return self.config.get("channels", [])
    
    def get_context_for_llm(self, channel_id: str) -> str:
        ch = self.get_channel(channel_id)
        if not ch:
            return ""
        return (
            f"CHANNEL: {ch['topic']}\n"
            f"TONE: {ch['tone']}\n"
            f"PLATFORM: {ch['platform']}\n"
            f"STYLE: {ch.get('script_style', 'narrative')}"
        )
```

### 5.3 FormatEngine (`core/format_engine.py`)

```python
class FormatEngine:
    def __init__(self, config_path="config/schedule_formats.json"):
        self.config = get_config("schedule_formats")  # нужно добавить
    
    def get_format(self, format_id: str) -> dict:
        for fmt in self.config.get("formats", []):
            if fmt["id"] == format_id:
                return fmt
        return None
    
    def expand_scenes(self, format_template: dict, storyboard_scenes: list) -> list:
        """
        Превращает форматный шаблон в конкретные сцены.
        
        Вход:
          format_template.scenes = [
            {"type": "static", "count": 8, "role": "body"},
            {"type": "dynamic", "preset": "text_reveal", "role": "cta", "params": {...}}
          ]
          storyboard_scenes = [сцены от storyboarder]
        
        Выход: список сцен с проставленными type, role, preset
        """
        expanded = []
        static_idx = 0
        
        for segment in format_template.get("scenes", []):
            if segment["type"] == "static":
                for _ in range(segment.get("count", 1)):
                    if static_idx < len(storyboard_scenes):
                        scene = storyboard_scenes[static_idx].copy()
                        scene["role"] = segment["role"]
                        scene["type"] = "static"
                        expanded.append(scene)
                        static_idx += 1
            elif segment["type"] == "dynamic":
                expanded.append({
                    "type": "dynamic",
                    "role": segment["role"],
                    "preset": segment["preset"],
                    "params": segment.get("params", {}),
                    "text_segment": "",
                    "estimated_duration": segment.get("duration_range", [4, 6])[1]
                })
        
        return expanded
    
    def resolve_params(self, params: dict, context: dict) -> dict:
        """
        Разрешает переменные в params динамических сцен.
        {character_name} → context["character_name"]
        {episode_title} → context["episode_title"]
        """
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                for var_name, var_value in context.items():
                    value = value.replace(f"{{{var_name}}}", str(var_value))
            resolved[key] = value
        return resolved
```

---

## 6. Конфигурационные файлы

### 6.1 `config/channels.json`

```json
{
  "channels": [
    {
      "id": "science_facts",
      "name": "🔬 Научные Факты",
      "topic": "Удивительные научные факты, открытия и исследования",
      "tone": "Увлекательный, экспертный, с элементами вау-эффекта",
      "platform": "YouTube Shorts",
      "avoid": ["политика", "религия", "эзотерика"],
      "language": "Russian",
      "script_style": "scientific",
      "default_format": "science_weekly",
      "character_pool": null,
      "asset_pool": "pool_science_bg"
    },
    {
      "id": "orthodox_stories",
      "name": "☦️ Жития Святых",
      "topic": "Истории из жизни православных святых, чудеса, духовные наставления",
      "tone": "Благоговейный, повествовательный, вдохновляющий",
      "platform": "YouTube / TikTok",
      "avoid": ["политика", "критика церкви", "сенсации"],
      "language": "Russian",
      "script_style": "narrative",
      "default_format": "saint_life_series",
      "character_pool": "saints_pool",
      "asset_pool": "pool_orthodox_bg"
    },
    {
      "id": "product_reviews",
      "name": "🛍 Обзоры товаров",
      "topic": "Обзоры и сравнения товаров для дома и кухни",
      "tone": "Энергичный, рекомендательный, честный",
      "platform": "TikTok / Reels",
      "avoid": ["ложные заявления", "медицинские советы"],
      "language": "Russian",
      "script_style": "hype",
      "default_format": "product_showcase",
      "character_pool": null,
      "asset_pool": "pool_product_bg"
    }
  ]
}
```

### 6.2 `config/schedule_formats.json`

```json
{
  "formats": [
    {
      "id": "science_weekly",
      "name": "📅 Научный еженедельник",
      "description": "10 статичных сцен + динамическая заставка в конце",
      "video_format": "vertical",
      "total_duration_target": 60,
      "visual_style": "v_smooth_story",
      "tts_preset": "edge_male_fast",
      "metadata_style": "edu",
      "scenes": [
        {
          "type": "static",
          "count": 1,
          "role": "hook",
          "duration_range": [3, 5],
          "asset_pool_key": "hook"
        },
        {
          "type": "static",
          "count": 8,
          "role": "body",
          "duration_range": [4, 7],
          "asset_pool_key": "body"
        },
        {
          "type": "static",
          "count": 1,
          "role": "outro",
          "duration_range": [3, 5],
          "asset_pool_key": "outro"
        },
        {
          "type": "dynamic",
          "preset": "text_reveal",
          "role": "cta",
          "params": {
            "title": "🔔 Подпишись на канал!",
            "subtitle": "Новые научные факты каждую неделю"
          }
        }
      ]
    },
    {
      "id": "saint_life_series",
      "name": "🕊 Серия Житие святого",
      "description": "100 эпизодов про одного святого. Интро с иконой + 6 сцен истории + аутро.",
      "video_format": "vertical",
      "total_duration_target": 55,
      "visual_style": "v_cinematic_vert",
      "tts_preset": "edge_female_soft",
      "metadata_style": "edu",
      "scenes": [
        {
          "type": "dynamic",
          "preset": "icon_presentation",
          "role": "intro",
          "params": {
            "icon": "{character_seed_photo}",
            "title": "{character_name}",
            "description": "{episode_subtopic}"
          }
        },
        {
          "type": "static",
          "count": 6,
          "role": "story",
          "duration_range": [5, 8],
          "asset_pool_key": "story"
        },
        {
          "type": "static",
          "count": 1,
          "role": "outro",
          "duration_range": [4, 6],
          "asset_pool_key": "outro"
        },
        {
          "type": "dynamic",
          "preset": "text_reveal",
          "role": "cta",
          "params": {
            "title": "🙏 Спаси Господи!",
            "subtitle": "Подпишись на канал о вере"
          }
        }
      ]
    },
    {
      "id": "product_showcase",
      "name": "🛍 Обзор товара",
      "description": "8 статичных сцен + динамическая карточка товара в конце.",
      "video_format": "vertical",
      "total_duration_target": 50,
      "visual_style": "v_dynamic_shorts",
      "tts_preset": "edge_announcer",
      "metadata_style": "viral",
      "scenes": [
        {
          "type": "static",
          "count": 1,
          "role": "hook",
          "duration_range": [3, 4],
          "asset_pool_key": "hook"
        },
        {
          "type": "static",
          "count": 6,
          "role": "body",
          "duration_range": [4, 6],
          "asset_pool_key": "body"
        },
        {
          "type": "static",
          "count": 1,
          "role": "outro",
          "duration_range": [3, 4],
          "asset_pool_key": "outro"
        },
        {
          "type": "dynamic",
          "preset": "product_card",
          "role": "cta",
          "params": {
            "title": "{episode_title}",
            "desc": "{episode_subtopic}",
            "price_new": "2990",
            "discount": "30"
          }
        }
      ]
    }
  ]
}
```

### 6.3 `config/asset_pools.json`

```json
{
  "pool_science_bg": {
    "name": "🔬 Научные фоны",
    "assets": {
      "hook": "local_assets/pools/science/lab_bg.mp4",
      "body": "local_assets/pools/science/microscope.jpg",
      "outro": "local_assets/pools/science/stars_bg.mp4"
    }
  },
  "pool_orthodox_bg": {
    "name": "☦️ Православные фоны",
    "assets": {
      "story": "local_assets/pools/orthodox/temple_bg.jpg",
      "outro": "local_assets/pools/orthodox/candles_bg.mp4"
    }
  }
}
```

---

## 7. Scheduler Bot (`bot/scheduler_app.py`)

### 7.1 Точка входа

```python
# bot/scheduler_app.py
import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession

root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

from bot.middlewares.errors import ErrorHandlingMiddleware
from bot.handlers import scheduler

load_dotenv(root_dir / ".env")
API_TOKEN = os.getenv("SCHEDULER_BOT_TOKEN")

async def main():
    if not API_TOKEN:
        logging.error("SCHEDULER_BOT_TOKEN не найден в .env!")
        return

    session = AiohttpSession()
    session.timeout = 900

    bot = Bot(token=API_TOKEN, session=session)
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.outer_middleware(ErrorHandlingMiddleware())
    dp.include_router(scheduler.router)

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Scheduler Bot stopped")
```

### 7.2 Handlers (`bot/handlers/scheduler.py`)

**Команды и их назначение:**

| Команда | Описание | Процесс |
|---------|----------|---------|
| `/schedule` | Начать планирование серии | Выбор канала → формата → ввод темы + кол-ва → SeriesPlanner → показ плана → утверждение → BatchScriptWriter → ProjectFactory → статус |
| `/characters` | Управление персонажами | Создать / просмотреть / привязать к каналу |
| `/channels` | Просмотр каналов | Список + возможность переключить дефолтный |
| `/formats` | Просмотр форматов | Список доступных форматов с описанием |
| `/status` | Статус последней генерации | Сколько проектов создано, сколько в очереди |

**FSM-состояния (отдельный StatesGroup):**

```python
class SchedulerStates(StatesGroup):
    choosing_channel = State()          # Выбор канала
    choosing_format = State()           # Выбор формата
    entering_topic = State()            # Ввод темы + кол-ва
    choosing_character = State()        # Выбор/создание персонажа
    reviewing_plan = State()            # Просмотр плана серии
    generating_batch = State()          # Генерация сценариев
    completed = State()                 # Завершено
```

**Пример flow для `/schedule`:**

```
/schedule
  → "Выберите канал:" (кнопки из channels.json)
  → "Выберите формат видео:" (кнопки из schedule_formats.json)
  → "Введите тему серии:" + "Количество видео (15-30):"
  → "Использовать персонажа?": [Создать нового] [Выбрать из пула] [Пропустить]
  → SeriesPlanner генерирует план
  → "План серии: [список эпизодов]. Утвердить?" [Да] [Переделать]
  → BatchScriptWriter генерирует сценарии
  → ProjectFactory создаёт проекты на диск
  → "✅ Создано N проектов в папке projects/"
```

---

## 8. Интеграция с основным ботом

### 8.1 Связь односторонняя: Scheduler Bot → Основной бот

Scheduler Bot **только создаёт** `project.json` на диске.
Основной бот **читает** их и **рендерит**.

### 8.2 Как основной бот подхватывает проекты планировщика

1. Scheduler Bot создаёт `project.json` с `status: "scheduled"`
2. Основной бот при `/start` сканирует `projects/`
3. Видит проекты со статусом `"scheduled"` и показывает их в списке
4. Пользователь выбирает проект → бот переходит к:
   - **Если ассеты уже на диске** → сразу к озвучке (TTS)
   - **Если ассетов нет** → к сбору материалов (стандартный flow)
5. Далее стандартный пайплайн: озвучка → стиль монтажа → SEO → рендер

### 8.3 Минимальные правки в основном боте

| Файл | Правка | Зачем |
|------|--------|-------|
| `bot/handlers/common.py` | В `cmd_start()` добавить обработку статуса `"scheduled"` | Показывать scheduled-проекты при /start |
| `core/project_manager.py` | Добавить `"scheduled"` в список допустимых статусов | Не ломать валидацию |
| `bot/pipeline_manager.py` | При рендере scheduled-проекта: пропускать шаги, где данные уже есть (SEO, сценарий) | Не перегенерировать готовые данные |
| `config/config_loader.py` | Добавить `"channels"`, `"schedule_formats"`, `"asset_pools"` в CONFIG_PATHS | Чтобы работал get_config() |

---

## 9. Сводная таблица реализации

| Категория | Файл | Тип | Сложность | Зависит от |
|-----------|------|-----|-----------|------------|
| Конфиг | `config/channels.json` | Новый | Низкая | — |
| Конфиг | `config/schedule_formats.json` | Новый | Средняя | — |
| Конфиг | `config/asset_pools.json` | Новый | Низкая | — |
| Core | `core/channel_manager.py` | Новый | Низкая | config_loader |
| Core | `core/format_engine.py` | Новый | Средняя | config_loader |
| AI | `ai/series_planner.py` | Новый | Средняя | llm_client |
| AI | `ai/character_generator.py` | Новый | Средняя | llm_client, image_generator |
| AI | `ai/batch_script_writer.py` | Новый | Высокая | script_writer, storyboarder, format_engine |
| AI | `ai/asset_pool_manager.py` | Новый | Низкая | project_manager |
| Core | `core/project_factory.py` | Новый | Высокая | batch_script_writer, asset_pool_manager, metadata_agent |
| Бот | `bot/scheduler_app.py` | Новый | Средняя | aiogram |
| Handler | `bot/handlers/scheduler.py` | Новый | Средняя | channel_manager, format_engine, project_factory |
| Правка | `bot/handlers/common.py` | Правка | Низкая | — |
| Правка | `bot/pipeline_manager.py` | Правка | Низкая | — |
| Правка | `core/config_loader.py` | Правка | Низкая | — |
| Правка | `.env` | Правка | Низкая | — |

---

## 10. Порядок реализации

```
День 1: config/channels.json + core/channel_manager.py
        config/schedule_formats.json + core/format_engine.py
        config/asset_pools.json
        Правки в config_loader.py (добавить пути)

День 2: ai/series_planner.py + ai/character_generator.py
        local_assets/characters/ + тестовый персонаж

День 3: ai/batch_script_writer.py
        Интеграция с script_writer + storyboarder

День 4: core/project_factory.py + ai/asset_pool_manager.py
        Тест: создание одного проекта через фабрику

День 5: bot/scheduler_app.py + bot/handlers/scheduler.py
        Тест: полный цикл /schedule для одного канала

День 6: Правки в основном боте (статус scheduled, авто-озвучка)
        Интеграционное тестирование
        Документация
```

---

*Документ создан 2026-05-02. Версия плана: 1.0*
