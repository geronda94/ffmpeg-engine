# Руководство разработчика: Система Экшенов (Action System)

Этот документ объясняет как работает модульная система обработки видео-эффектов и как создавать новые.

---

## Архитектура

Система организована по принципу **Chain of Responsibility** + **Factory Pattern**:

```
JSON Task
   └─► filter_builder.py  (высокоуровневая сборка пайплайна)
          └─► factory.py   (реестр → выбор нужного билдера)
                 └─► ConcreteBuilder.build() (генерация FFmpeg-строки)
```

### Файловая структура

```
engine/
├── filter_builder.py   # Сборщик пайплайна
└── actions/
    ├── __init__.py
    ├── base.py          # BaseActionBuilder (абстрактный)
    ├── factory.py       # Реестр и get_builder()
    ├── utils.py         # Общие утилиты (шрифты, текст, expr)
    ├── geometry.py      # scale, crop, setsar
    ├── text.py          # drawtext
    ├── plates.py        # plate (Glassmorphism)
    ├── animation.py     # zoom, zoom_blur, fade_in, fade_out, dissolve
    └── misc.py          # blur, custom
```

---

## Как работает построение фильтра

### 1. `filter_builder.build_pipeline()`
Итерирует по `pipeline` из JSON и для каждого шага:
1. Применяет `trim` (обрезку по времени с `setpts=PTS-STARTPTS`)
2. Для каждого action вызывает `build_action(action, in_label, out_label)`
3. Восстанавливает PTS (`setpts=PTS+start/TB`) для позиционирования в финальном видео

### 2. `build_action()`
Делегирует построение нужному билдеру через фабрику:
```python
builder = factory.get_builder(a.type)  # → ConcreteBuilder
return builder.build(a, in_label, out_label, fps, duration=step_dur)
```

### 3. Лейблы (`[in_label]` → `[out_label]`)
Каждый экшен получает входной и выходной лейбл и строит строку вида:
```
[in_label]filter1,filter2,...[out_label]
```
Для сложных экшенов (plate) возвращается цепочка через `;`:
```
[inv]split[a][b];[a]crop...[mask];[inv][mask]overlay=x:y[outv]
```

---

## Создание нового экшена

### Шаг 1: Создайте файл в `engine/actions/`

```python
# engine/actions/sepia.py
from engine.actions.base import BaseActionBuilder
from engine.schema import Action

class SepiaBuilder(BaseActionBuilder):
    def build(self, a: Action, in_label: str, out_label: str, fps: int = 30, duration: float = 0) -> str:
        intensity = a.sigma or 1.0  # переиспользуем существующие поля
        f = (
            f"colorchannelmixer="
            f"rr={0.393*intensity}:rg={0.769*intensity}:rb={0.189*intensity}:"
            f"gr={0.349*intensity}:gg={0.686*intensity}:gb={0.168*intensity}:"
            f"br={0.272*intensity}:bg={0.534*intensity}:bb={0.131*intensity}"
        )
        return self.simple(in_label, f, out_label)
```

**Правила:**
- `self.simple(in, filter_str, out)` → `[in]filter_str[out]` — для простых однострочных фильтров
- Для сложных (multi-step) возвращайте строку с `;` между подграфами
- Лейблы промежуточных потоков: используйте `f"{out_label}_имя"` для уникальности

### Шаг 2: Зарегистрируйте в фабрике

```python
# engine/actions/factory.py
from engine.actions.sepia import SepiaBuilder

def _register_all():
    ...
    sepia = SepiaBuilder()
    _BUILDERS["sepia"] = sepia
```

### Шаг 3: Добавьте поля в схему (если нужны новые параметры)

```python
# engine/schema.py — класс Action
sepia_intensity: Optional[float] = None
```

> **Совет**: Сначала переиспользуйте существующие поля (`sigma`, `duration`, `x`, `y`, `filter`). Добавляйте новые только когда семантически необходимо.

### Шаг 4: Используйте в JSON

```json
{
  "type": "sepia",
  "sigma": 0.8
}
```

---

## Правила написания FFmpeg-выражений

### ⚠️ Проблема с кавычками в `filter_complex`
При передаче через Python subprocess (без shell), FFmpeg парсит `filter_complex` напрямую. Правила:

| Символ | Контекст | Поведение |
|--------|----------|-----------|
| `;` | filter_complex | Разделитель подграфов |
| `,` | filter chain | Разделитель фильтров в цепочке |
| `:` | filter options | Разделитель параметров фильтра |
| `'...'` | значение параметра | Защищает `,` и `:` внутри |

**Ограничение FFmpeg 6.x**: Вложенные одинарные кавычки внутри `geq=a='...'` могут не работать если выражение содержит функции с запятыми (например `lum(X,Y)`). Используйте простые арифметические выражения без функций.

### Безопасные паттерны для сложных выражений:
```python
# ✅ Простая арифметика — работает всегда
f"geq=lum=255*X/W"

# ✅ Сравнения — работают
f"geq=lum=255*(X>100)"

# ✅ Произведение булевых — работает (И без запятых)
f"geq=lum=255*(X>100)*(Y<200)"

# ❌ Функции с запятыми в значениях 'quoted' — не работает в FFmpeg 6
f"geq=lum='lum(X,Y)':a='if(cond,0,255)'"
```

---

## Отладка

### Dry-run
```bash
python main.py --task tasks/my_task.json --dry-run
```
Выводит полную команду FFmpeg без запуска рендера.

### Сохранение кэша при ошибке
При неудачном рендере, временные файлы в `temp_render/` **не удаляются** — можно спокойно итерировать код.

### Логи
```bash
python main.py --task tasks/my_task.json -v  # DEBUG уровень
```
