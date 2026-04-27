from engine.actions.base import BaseActionBuilder
from engine.actions.geometry import GeometryBuilder
from engine.actions.text import TextBuilder
from engine.actions.plates import PlateBuilder
from engine.actions.animation import AnimationBuilder
from engine.actions.misc import MiscBuilder

_BUILDERS: dict[str, BaseActionBuilder] = {}

def _register_all():
    global _BUILDERS
    geom = GeometryBuilder()
    text = TextBuilder()
    plate = PlateBuilder()
    anim = AnimationBuilder()
    misc = MiscBuilder()
    
    # Регистрация типов
    for t in ["scale", "scale_and_crop", "scale_contain", "setsar"]:
        _BUILDERS[t] = geom
    
    _BUILDERS["drawtext"] = text
    _BUILDERS["plate"] = plate
    
    for t in ["zoom", "zoom_blur", "fade_in", "fade_out", "dissolve"]:
        _BUILDERS[t] = anim
        
    for t in ["blur", "custom"]:
        _BUILDERS[t] = misc

_register_all()

def get_builder(action_type: str) -> BaseActionBuilder:
    return _BUILDERS.get(action_type, MiscBuilder())
