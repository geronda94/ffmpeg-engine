# 🧭 Content Factory — План развития (Roadmap)

## Архитектурный аудит — состояние на 2026-05-14

### Что хорошо

| Компонент | Почему |
|-----------|--------|
| `core/effects.py` + `core/transitions.py` | Уже plugin-архитектура через `@register`. Добавить эффект = 1 функция + 1 строка в JSON. |
| `core/animation_utils.py` | Чистые математические функции. Идеальный reusable-компонент. |
| `core/config_loader.py` | Кеширующий JSON-загрузчик с TTL. Используется всеми. |
| `ai/subtitle_agent.py`, `ai/metadata_agent.py` | Близки к чистым функциям — минимум побочных эффектов. |

### Что плохо (технический долг)

| Проблема | Где | Приоритет |
|----------|-----|-----------|
| `ProjectManager` создаётся **6 раз** в разных модулях | common, scripting, metadata, pipeline, navigation, task_manager | Высокий |
| `eval()` на значениях из JSON | `storyboarder.py`, `project_manager.py` | **Критичный** (безопасность) |
| Хардкодные промпты (300+ строк) | `script_writer.py:_BASE_OUTPUT_RULES` | Средний |
| `channel_to_style` маппинг в коде | `production.py` | Низкий |
| MontageEngine нельзя переключить | `montage_agent.py:MediaEngine` hardcoded | Средний |
| Нет singleton для ProjectManager | 6 инстансов | Высокий |

---

## Этап 1: Архитектурное ядро (текущий спринт)

### 1.1 Убрать `eval()` из кода
- `storyboarder.py:57` — заменить на `ast.literal_eval` или простой расчёт
- `project_manager.py:169` — то же
- **Приоритет: 🔴 Критичный** (безопасность)

### 1.2 ProjectManager → Singleton
- Убрать 6 независимых инстансов
- Сделать `ProjectManager` синглтоном (как `TaskManager`)
- **Приоритет: 🟡 Средний**

### 1.3 Plugin-архитектура для монтажного движка
- `class MontageEngine(ABC)` — абстрактный класс
- `StandardMontage` — текущий (blur bg + FG)
- `FullFrameMontage` — для полноэкранных сюжетов
- `CarouselMontage` — карусель изображений
- **Приоритет: 🟢 Низкий** (для будущих расширений)

---

## Этап 2: Расширение форматов контента

### 2.1 Полноэкранные сюжеты
- `FullFrameMontage` — без размытого фона, изображение на весь экран
- Сценарии: сторителлинг, документальные, интервью
- Новый пресет: `v_fullframe` / `w_fullframe`
- **Файлы:** `core/montage_engine.py` (новый), `config/rendering_presets.json`

### 2.2 Карусель изображений (TikTok-style)
- 40+ изображений в секунду под основным объектом
- `CarouselRenderLayer` — слой карусели
- Интеграция с `effects.py` как overlay-эффект
- **Файлы:** `core/carousel_layer.py` (новый), `config/carousel_presets.json`

### 2.3 Мульти-формат субтитров
- Plugin-архитектура: `@register_subtitle(name)` как у эффектов
- Текущий: KaraokeSubtitle (2-строчный с заполнением)
- Новые: StandardSubtitle (1 строка), ThreeLineSubtitle (3 строки старые)
- **Файлы:** `ai/subtitle_agent.py` → рефакторинг под plugin

---

## Этап 3: Планировщик контента (Scheduler Bot)

### 3.1 Архитектура (из `docs/SCHEDULER_BOT_PLAN.md`)
- Отдельный Telegram-бот для пакетного планирования
- 4 новых агента: SeriesPlanner, VisualArchitect, ContentCalendar, PerformanceAnalyst
- 3 новых модуля: `core/project_factory.py`, `core/plan_manager.py`, `core/topic_generator.py`

### 3.2 Мастер-конфиг канала
- Единый JSON для полного описания почерка монтажа
- Поля: script_style, pacing, visual_style, music_prefs, subtitle_style, color_palette
- При создании проекта: выбор мастера → всё настроено автоматом
- **Файл:** `config/channel_master.json`

---

## Этап 4: Умные LLM-агенты

### 4.1 Улучшение поискового агента
- Глубокая нарративная связность (учёт предыдущих/следующих сцен)
- Авто-переключение источников при ошибках
- Улучшенная "reality check" для запросов

### 4.2 Скрипт-агент с планированием
- Генерация не просто сценария, а контент-плана на неделю
- Понимание аудитории канала (age, interests, platform)
- Анализ предыдущих видео + performance метрики

---

## Приоритеты

| # | Задача | Влияние | Сложность |
|---|--------|---------|-----------|
| 🔴 | Убрать `eval()` | Безопасность | Низкая |
| 🟡 | ProjectManager → Singleton | Стабильность | Низкая |
| 🟡 | Plugin-архитектура субтитров | Расширяемость | Средняя |
| 🟢 | Мастер-конфиг канала | Автоматизация | Средняя |
| 🟢 | FullFrame + Carousel montage | Новые форматы | Высокая |
