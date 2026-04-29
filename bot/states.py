from aiogram.fsm.state import State, StatesGroup

class ProjectStates(StatesGroup):
    # Настройка проекта
    choosing_language = State()
    choosing_format = State()
    
    # Работа со сценарием
    choosing_script_mode = State()
    choosing_script_style = State()
    writing_topic = State()
    writing_manual_script = State()
    approving_script = State()
    
    # Работа с раскадровкой (Диалог с Агентом Сцен)
    choosing_storyboard_mode = State()
    refining_storyboard = State()
    
    # Сбор материалов
    approving_scenes = State()
    collecting_assets = State()
    waiting_for_asset = State()
    approving_asset = State()
    
    # Финал (Озвучка и Рендер)
    choosing_visual_style = State()
    choosing_tts_engine = State()
    choosing_tts_preset = State()
    approving_audio = State() # Восстановлено!
    rendering = State()
