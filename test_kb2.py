import numpy as np
from PIL import Image as _PILImage
from moviepy import ColorClip, vfx
from core.media_engine import MediaEngine

engine = MediaEngine()
clip = ColorClip(size=(100, 100), color=(255, 0, 0)).with_duration(1.0)
effects = [{"type": "ken_burns", "zoom_from": 1.0, "zoom_to": 1.25}]

# Replace make_frame with frame_function
import core.media_engine
with open('core/media_engine.py', 'r') as f:
    content = f.read()
content = content.replace('make_frame=frame_fn', 'frame_function=frame_fn').replace('make_frame=mask_fn', 'frame_function=mask_fn')
with open('core/media_engine.py', 'w') as f:
    f.write(content)

import importlib
importlib.reload(core.media_engine)
from core.media_engine import MediaEngine

engine = MediaEngine()
new_clip = engine.apply_preset_effects(clip, effects)
frame = new_clip.get_frame(0.5)
print("Frame shape:", frame.shape)
print("Has size?", hasattr(new_clip, 'size'), new_clip.size if hasattr(new_clip, 'size') else "No")
