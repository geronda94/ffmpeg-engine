import numpy as np
from PIL import Image as _PILImage
from moviepy import ColorClip, vfx
from core.media_engine import MediaEngine

# Replace frame_function and astype
import core.media_engine
with open('core/media_engine.py', 'r') as f:
    content = f.read()
content = content.replace('img = _PILImage.fromarray(cropped)', 'img = _PILImage.fromarray(cropped.astype(np.uint8))')
with open('core/media_engine.py', 'w') as f:
    f.write(content)

import importlib
importlib.reload(core.media_engine)
from core.media_engine import MediaEngine

engine = MediaEngine()
clip = ColorClip(size=(100, 100), color=(255, 0, 0)).with_duration(1.0)
effects = [{"type": "ken_burns", "zoom_from": 1.0, "zoom_to": 1.25}]

new_clip = engine.apply_preset_effects(clip, effects)
frame = new_clip.get_frame(0.5)
print("Frame shape:", frame.shape)
print("Frame dtype:", frame.dtype)
print("Frame max value:", np.max(frame))
print("Frame min value:", np.min(frame))
print("Has size?", hasattr(new_clip, 'size'), new_clip.size if hasattr(new_clip, 'size') else "No")
