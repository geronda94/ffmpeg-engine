from aiogram.fsm.state import State, StatesGroup

class ProjectStates(StatesGroup):
    choosing_language = State()
    choosing_format = State()
    choosing_visual_style = State() # НОВОЕ: Стиль монтажа (Зум, Динамика и т.д.)
    choosing_script_mode = State()
    choosing_script_style = State()
    writing_topic = State()
    writing_manual_script = State()
    approving_script = State()
    approving_scenes = State()
    collecting_assets = State()
    waiting_for_asset = State()
    approving_asset = State()
    choosing_tts_engine = State()
    choosing_tts_preset = State()
    approving_audio = State()
    processing = State()
