# MoviePy v2.x Migration Guide for AI Agents

This project uses **MoviePy v2.x**. Standard v1.0.3 syntax will cause errors. 
Use this guide to generate compatible code.

## 1. Import Structure
```python
# CORRECT
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, TextClip
import moviepy.video.fx as vfx

# INCORRECT (Do not use .editor)
# from moviepy.editor import * 
```

## 2. Method Renaming Table
| Feature | v1.x (Legacy) | v2.x (Current) |
| :--- | :--- | :--- |
| Duration | `set_duration(d)` | `with_duration(d)` |
| Audio | `set_audio(a)` | `with_audio(a)` |
| Position | `set_position(p)` | `with_position(p)` |
| Start Time | `set_start(s)` | `with_start(s)` |
| Resize | `resize(w, h)` | `resized(width=w, height=h)` |
| Crop | `crop(center=...)` | `cropped(x_center=..., y_center=...)` |
| Volume | `volumex(0.5)` | `with_effects([vfx.MultiplyVolume(0.5)])` |

## 3. Applying Effects & Transitions
Effects are now objects passed to `with_effects()`.

**Crossfade In:**
```python
clip = clip.with_effects([vfx.CrossFadeIn(1.0)])
```

**Crossfade Out:**
```python
clip = clip.with_effects([vfx.CrossFadeOut(1.0)])
```

**Dynamic Zoom:**
```python
clip = clip.with_effects([vfx.Resize(lambda t: 1 + 0.05 * t)])
```

## 4. Rendering
```python
final_video.write_videofile(
    "output.mp4", 
    fps=30, 
    codec="libx264", 
    threads=4,
    preset="ultrafast"
)
```
