# Content Factory — AI-Powered Automated Video Content Pipeline

> Multi-agent system for generating, assembling, and publishing short-form video content across Telegram channels — fully automated from script to final video.

## Overview

Content Factory is a production-grade AI pipeline that transforms text scripts into vertical short-form videos with AI-generated storyboards, automated image search/scoring, Text-to-Speech, subtitles, translations, and multi-channel publishing to Telegram topics.

**Key metrics:**
- 4 content channels (Orthodox, News, Tech/Business, Lifestyle)
- 25+ specialized AI agents working in orchestration
- Russian, English, Romanian, Georgian language support
- Automatic translation pipeline (RU → RO, RU → EN)
- ~$0.01–0.02 per video (DeepSeek API, heavily optimized)

## Architecture

```
/auto "script text" in Telegram topic
    │
    ├─ Command Handler (bot/handlers/common.py)
    │   ├─ Media Parser — extract URLs & attachments from message
    │   └─ Topic → Channel Router — determine channel by message_thread_id
    │
    └─ Auto Pipeline (bot/handlers/auto_pipeline.py)
        │
        ├─ 1. Storyboard Agent (ai/storyboarder.py)
        │   └─ LLM breaks script into timed scenes with visual descriptions
        │
        ├─ 2. Knowledge Base Layer 1 (core/query_knowledge.py)
        │   └─ Entity matching by aliases — 0 LLM for known entities
        │   └─ Context injection — scene-specific keywords → queries
        │
        ├─ 3. Auto-Select Pipeline (bot/handlers/assets/auto_select.py)
        │   ├─ Phase 1: Parallel stock search + sequential DDG/SearXNG search
        │   ├─ Phase 2: Batch scoring via LLM (5 scenes per call)
        │   ├─ Phase 3: Download + dedup (normalized URLs, 4-day TTL)
        │   └─ Phase 4: Individual fallback chain (Pexels → Pixabay → AI Gen → SearXNG)
        │
        ├─ 4. Image Scorer (ai/image_scoring_agent.py)
        │   └─ LLM scores images 0–10 with channel-specific rules
        │   └─ Pre-filters: watermarks, people (for Orthodox), non-Christian content
        │   └─ Score cache — same scene/URLs not re-evaluated
        │
        ├─ 5. TTS Engine (ai/tts_edge.py)
        │   └─ Microsoft Edge TTS with AI-optimized text preprocessing
        │   └─ Channel-specific audio post-processing (bass, echo, reverb)
        │
        ├─ 6. Preview Designer (ai/preview_agent.py, ai/preview_designer_agent.py)
        │   └─ LLM generates attention-grabbing preview text
        │   └─ Color palette extraction from first frame
        │
        ├─ 7. Montage Renderer (ai/montage_agent.py)
        │   └─ MoviePy-based video assembly with effects, transitions, preview overlay
        │   └─ Background music from channel-tagged library
        │   └─ Whisper-based subtitle alignment with karaoke word highlighting
        │
        ├─ 8. Post-Render Callback (auto_pipeline.py)
        │   ├─ Video compression for Telegram (ffmpeg)
        │   ├─ Send to channel-specific output topics
        │   └─ Auto-translation pipeline trigger
        │
        └─ 9. Translation Pipeline (auto_pipeline.py + ai/localization_agent.py)
            └─ Clone project → AI translate scenes/metadata → new TTS → new render
```

## Project Structure

```
ffmpeg/
├── ai/                          # 25+ AI agent modules
│   ├── storyboarder.py          # Scene decomposition agent
│   ├── script_writer.py         # Script generation with style presets
│   ├── image_search_agent.py    # Multi-source search (Pexels, Pixabay, AI Gen, DDG)
│   ├── image_scoring_agent.py   # LLM-based image scoring with pre-filters
│   ├── timing_agent.py          # Needleman-Wunsch DP word alignment
│   ├── subtitle_agent.py        # ASS subtitle generation with karaoke
│   ├── montage_agent.py         # MoviePy video compositing
│   ├── llm_client.py            # DeepSeek API client (sync + async, retries, JSON mode)
│   ├── llm_aligner.py           # LLM-based word-level timing alignment
│   ├── preview_agent.py         # Preview text generation
│   ├── preview_designer_agent.py # Color palette extraction
│   ├── metadata_agent.py        # SEO metadata (title, description, hashtags)
│   ├── sound_design_agent.py    # Background music SFX selection
│   ├── localization_agent.py    # Full-project translation
│   ├── tts_edge.py              # Edge TTS with AI-optimized text
│   ├── query_reviewer.py        # Post-asset batch reviewer (false positive guard)
│   ├── duckduckgo_search.py     # DDG + SearXNG search with retries
│   └── media_parser.py          # URL scraping + og:image extraction
│
├── core/                        # Infrastructure
│   ├── query_knowledge.py       # Self-populating entity KB with word-boundary matching
│   ├── project_manager.py       # Disk-based project state (single source of truth)
│   ├── task_manager.py          # Async render queue (singleton, 1 worker)
│   ├── url_deduplicator.py      # 4-day URL dedup with normalization
│   ├── config_loader.py         # Cached JSON config loader (5-min TTL)
│   └── media_library.py         # Local media index for saints/icons
│
├── config/                      # JSON-driven configuration
│   ├── channel_context.json     # 6 channel profiles with visual rules
│   ├── channel_topics.json      # Telegram topic ID mappings
│   ├── auto_presets.json        # Per-channel auto pipeline presets
│   ├── script_presets.json      # Writing styles + pacing configs
│   ├── audio_presets.json       # TTS engines + voice presets
│   ├── rendering_presets.json   # Video effects + transitions
│   └── query_knowledge/         # Entity knowledge base (per-channel JSON)
│       ├── orthodox.json        # 19 saint/icon entities with aliases
│       ├── news.json            # 10 event entities
│       ├── tech_business.json   # 10 tech/business entities
│       └── lifestyle.json       # 10 lifestyle entities
│
├── bot/                         # Telegram bot application
│   ├── auto_bot_app.py          # Auto bot entry point
│   ├── bot_app.py               # Manual/interactive bot entry point
│   ├── navigation.py            # Reusable menu navigation (FSM)
│   ├── pipeline_manager.py      # TTS + render orchestration
│   ├── states.py                # FSM state definitions (~30 states)
│   └── handlers/                # Bot command handlers
│       ├── common.py            # /start, /auto, /full_automat
│       ├── auto_pipeline.py     # Full auto orchestration
│       ├── scripting.py         # Script generation flow
│       ├── production.py        # TTS, preview, visual style, render queue
│       ├── localization.py      # Translation flow
│       └── assets/              # Asset collection sub-system
│           ├── auto_select.py   # Batch auto image selection
│           ├── manual.py        # Manual file upload
│           ├── web_search.py    # Stock photo carousel
│           ├── ai_gen.py        # AI image generation
│           └── dynamic.py       # Dynamic scene presets
│
└── media_library/
    └── index.json               # Static media catalog (saints, holidays)
```

## Key Technical Decisions

### 1. Single Source of Truth — Disk, not FSM

Projects are stored as `projects/{project_id}/project.json`. The FSM state is secondary — it can be lost (MemoryStorage), but the project is always recoverable from disk. This enables `/start` → "Continue" after bot restart.

### 2. Self-Learning Knowledge Base

`query_knowledge.json` matches scene descriptions to entities via word-boundary regex on aliases. When an entity is NOT found, the LLM generates queries, caches them, and optionally creates a new entity template with aliases, filters, and queries. From 19 hand-crafted entities, the system grows organically (currently 23 Orthodox entities).

### 3. Batch Scoring for Cost Optimization

Instead of calling the LLM scorer once per scene (36 calls for a 36-scene video), results are collected and scored in batches of 5 scenes with a single LLM call. This cuts scoring costs by ~75%.

### 4. URL Deduplication with Normalization

All downloaded image URLs are stored with a 4-day TTL. Query parameters are stripped before hashing to prevent `?size=large` and `?size=medium` from counting as different images.

### 5. Async Render Queue

Rendering is CPU-intensive and blocks the event loop. A singleton `RenderTaskManager` with a single background worker processes the queue sequentially, allowing the bot to keep serving new requests during rendering.

## Setup

### Prerequisites

```bash
# Python 3.12+
# FFmpeg (for video processing)
sudo apt install ffmpeg

# System dependencies for Whisper
pip install openai-whisper
pip install edge-tts

# Install Python dependencies
pip install -r requirements.txt
```

### Environment

```bash
cp .env.example .env
# Edit .env with your actual API keys:
#   DEEPSEEK_API_KEY
#   TELEGRAM_BOT_TOKEN (for manual bot)
#   TELEGRAM_AUTO_BOT_TOKEN (for auto bot)
#   PEXELS_API_KEY
#   PIXABAY_API_KEY (optional)
```

### Telegram Setup

1. Create a Telegram Supergroup with Topics enabled
2. Add your bot as an admin
3. Set up the topic IDs in `config/channel_topics.json`
4. Disable privacy mode for the bot via @BotFather

### Running

```bash
# Auto bot (fully automated pipeline)
python bot/auto_bot_app.py

# Manual bot (interactive step-by-step)
python bot/bot_app.py
```

## Usage

### Auto Mode (in topic)

Send a script to the channel's input topic:
```
/auto Древние патерики рассказывают удивительную историю...
```

The bot:
1. Places a 👍 reaction on your message
2. Generates a storyboard
3. Auto-selects images (icons from web, stock photos)
4. Generates TTS audio
5. Renders the video
6. Sends it to the output topic
7. Auto-translates for configured languages
8. Places a ❤️ reaction when done

### Full Auto from Private Chat

```
/full_automat
[Select channel] → [Send script text]
```

### Manual Mode

```
/start → [Choose language, channel, format, script mode, style, pacing]
      → [Collect assets manually or auto-select]
      → [Choose TTS voice] → [Render]
```

## Configuration

All configuration is JSON-driven. Key files:

- `config/auto_presets.json` — per-channel pipeline presets (style, pacing, TTS voice, etc.)
- `config/channel_context.json` — visual rules (banned keywords, preferred keywords, subtitle styles) per channel
- `config/channel_topics.json` — Telegram topic IDs for input/output per channel + translation targets
- `config/query_knowledge/*.json` — per-channel entity knowledge base

## Translatability & Reusability

The knowledge base, query optimization, and scoring modules are designed to be **extracted as a standalone library** for other projects needing LLM-assisted web image search with entity filtering, caching, and deduplication.

Key reusable modules:
- `core/query_knowledge.py` — entity matching with self-learning
- `ai/image_search_agent.py` — multi-source search optimization
- `ai/image_scoring_agent.py` — LLM scoring with pre-filter chain
- `core/url_deduplicator.py` — normalized URL deduplication

## Tech Stack

- **LLM:** DeepSeek (via OpenAI-compatible API with custom `chat_json` structured output)
- **Bot:** aiogram 3.x (Telegram Bot API)
- **Video:** MoviePy + FFmpeg
- **TTS:** Microsoft Edge TTS + Gemini TTS
- **Speech-to-Text:** OpenAI Whisper (base model)
- **Image Search:** Pexels API, Pixabay API, DuckDuckGo/SearXNG, AI Gen (Pollinations)
- **Storage:** File-based JSON (projects, configs, caches)
- **Async:** asyncio with semaphores, queues, background workers
- **Audio Post-processing:** FFmpeg filters (bass boost, echo, reverb per channel profile)

## Channel Profiles

| Channel | Language | Auto-translate | Content Style |
|---------|----------|---------------|---------------|
| ☦️ Orthodox | Russian | → Romanian | Icons, saints, churches, spiritual content |
| 📰 News | Russian | → English | Breaking news, military, geopolitics |
| 💻 Tech/Business | Russian | — | IT, startups, code, data centers |
| 🌸 Lifestyle | Romanian | — | Beauty, fashion, travel, wellness |
