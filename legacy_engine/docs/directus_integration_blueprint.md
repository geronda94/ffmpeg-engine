# 🏗 Blueprint: Интеграция FFmpeg Engine с Directus CMS

Данный документ описывает архитектуру микросервиса для локального рендеринга видео с использованием Directus в качестве хранилища исходников и результатов.

---

## 1. Архитектура Docker (Shared Volumes)

Для исключения интернет-трафика и максимальной скорости чтения/записи, контейнеры должны иметь доступ к общей папке с файлами.

**docker-compose.yml (фрагмент):**
```yaml
services:
  directus:
    image: directus/directus
    volumes:
      - ./uploads:/directus/uploads

  ffmpeg-api:
    build: .
    volumes:
      - ./uploads:/mnt/directus_uploads:ro # Доступ к исходникам только на чтение
      - ./render_output:/mnt/render_output  # Папка для временных и готовых видео
    environment:
      - DIRECTUS_URL=http://directus:8055
      - DIRECTUS_TOKEN=your_static_token_here
      - LOCAL_UPLOADS_PATH=/mnt/directus_uploads
```

---

## 2. Логика Resolver (Умное чтение)

Модификация `engine/resolver.py` должна позволять движку перехватывать запросы к ассетам Директуса.

**Алгоритм:**
1. Получаем URL ресурса (например, `http://my-domain.com/assets/87ff231c...`).
2. Если URL содержит `/assets/`, извлекаем UUID файла.
3. Проверяем наличие файла `/mnt/directus_uploads/UUID` (Директус хранит файлы именно так, без расширений в папке uploads).
4. Если файл найден — возвращаем путь к нему. Если нет — качаем по HTTP (fallback).

---

## 3. Регистрация результата (Локальный Upload)

После завершения рендеринга, файл нужно «легализовать» в Директусе через API на `localhost`.

**Python-логика (FastAPI):**
```python
import httpx

async def register_video_in_directus(file_path, original_name):
    url = f"{os.getenv('DIRECTUS_URL')}/files"
    headers = {"Authorization": f"Bearer {os.getenv('DIRECTUS_TOKEN')}"}
    
    with open(file_path, "rb") as f:
        files = {"file": (original_name, f, "video/mp4")}
        # Добавляем метаданные, чтобы файл сразу попал в нужную папку или Workarea
        data = {"title": original_name, "folder": "uuid_of_your_renders_folder"}
        
        async with httpx.AsyncClient() as client:
            r = await client.post(url, headers=headers, files=files, data=data)
            return r.json()["data"]["id"] # Возвращает ID нового файла в Директусе
```

---

## 4. Схема взаимодействия (Sequence)

1. **Vue Frontend**: Отправляет JSON-конфиг в FastAPI.
2. **FastAPI**: 
   - Вызывает `filter_builder` для создания графа.
   - `resolver` подхватывает исходники из `/mnt/directus_uploads/`.
   - Запускает FFmpeg.
3. **FFmpeg**: Рендерит видео в локальную папку.
4. **FastAPI**: 
   - Через локальный API Директуса загружает готовое видео.
   - Получает ID нового файла.
   - Обновляет статус таски в Директусе (записывает ID видео в нужное поле).
5. **Directus**: Через вебсокеты или опрос сообщает Vue-фронтенду, что видео готово.

---

---

## 6. Гибридный режим (CLI vs FastAPI Wrapper)

Движок (Core Engine) остается универсальным и не знает о существовании Директуса. Всю логику пересылки берет на себя внешняя обертка.

### Режим A: Локальная песочница (CLI)
- **Инициатор**: Разработчик через терминал.
- **Команда**: `python main.py --task tasks/test.json`.
- **Поведение**:
  - Читает конфиг из локального файла.
  - Рендерит видео.
  - **Результат**: Файл сохраняется в `output/`. 
  - **Связь с сетью**: Отсутствует. Никаких вызовов API.

### Режим B: Продакшн-конвейер (FastAPI Service)
- **Инициатор**: Пользователь через Vue UI (кнопка "Рендерить").
- **Команда**: POST запрос с JSON на эндпоинт `/render`.
- **Поведение**:
  - FastAPI принимает JSON в теле запроса.
  - Запускает Core Engine.
  - **Результат**: Как только движок выдает файл, FastAPI запускает **Post-Render Hook**.
  - **Post-Render Hook**:
    1. Загружает файл в Директус по локальной сети (`localhost`).
    2. Получает от Директуса `file_id`.
    3. Обновляет запись в коллекции "Tasks" или "Workspaces", привязывая `file_id` к результату.
- **Связь с сетью**: Локальный API Директуса (Zero Internet Traffic).

---

## 7. Безопасность и .gitignore
- Файл `docs/directus_integration_blueprint.md` добавлен в `.gitignore`, чтобы архитектурные особенности системы не попали в публичный доступ.
- Ключи доступа (`DIRECTUS_TOKEN`) хранятся строго в `.env` и не передаются в коде.
