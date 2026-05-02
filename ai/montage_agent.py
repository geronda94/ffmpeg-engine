import os
import logging
import moviepy.video.fx as vfx
from moviepy import ImageClip, VideoFileClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
from proglog import ProgressBarLogger
from core.media_engine import MediaEngine

logger = logging.getLogger(__name__)

class TelegramProgressLogger(ProgressBarLogger):
    def __init__(self, callback=None):
        super().__init__()
        self.tg_callback = callback
        self.last_percent = -1

    def callback(self, **kwargs):
        if not self.tg_callback:
            return
            
        main_bar = self.bars.get('tqdm') or self.bars.get('video')
        
        if main_bar and main_bar.get('total'):
            bar_data = main_bar
        else:
            active_bars = [b for b in self.bars.values() if b.get('total', 0) > 0 and b['index'] < b['total']]
            if not active_bars:
                active_bars = [b for b in self.bars.values() if b.get('total', 0) > 0]
            
            if not active_bars: return
            bar_data = active_bars[-1]

        percent = int((bar_data['index'] / bar_data['total']) * 100)
        
        if percent != self.last_percent and (percent % 5 == 0 or percent == 100):
            self.last_percent = percent
            self.tg_callback(percent)


def _apply_transition(clip, transition_cfg, is_first: bool, engine_width: int, engine_height: int):
    if is_first:
        return clip
    trans_type = transition_cfg.get('type', 'crossfade')
    duration = transition_cfg.get('duration', 0.5)
    if duration <= 0:
        return clip

    if trans_type == 'crossfade':
        return clip.with_effects([vfx.CrossFadeIn(duration)])

    elif trans_type == 'fade_black':
        return clip.with_effects([vfx.FadeIn(duration)])

    elif trans_type == 'blur_dissolve':
        blur_strength = transition_cfg.get('blur_strength', 15)
        fade_in = clip.with_effects([vfx.FadeIn(duration / 2)])
        def _blur_ramp(t):
            if t > duration:
                return 0
            return max(0, blur_strength * (1 - t / duration))
        return fade_in.with_effects([vfx.Blur(sigma=_blur_ramp)])

    elif trans_type == 'slide_left':
        center_x = (engine_width - clip.w) / 2
        center_y = (engine_height - clip.h) / 2
        def _slide_pos(t):
            if t > duration:
                return (center_x, center_y)
            frac = 1 - t / duration
            from core.animation_utils import ease_out_cubic, lerp
            eased = ease_out_cubic(1 - frac)
            return (lerp(engine_width, center_x, eased), center_y)
        return clip.with_position(_slide_pos)

    elif trans_type == 'slide_right':
        center_x = (engine_width - clip.w) / 2
        center_y = (engine_height - clip.h) / 2
        def _slide_pos(t):
            if t > duration:
                return (center_x, center_y)
            frac = 1 - t / duration
            from core.animation_utils import ease_out_cubic, lerp
            eased = ease_out_cubic(1 - frac)
            return (lerp(-clip.w, center_x, eased), center_y)
        return clip.with_position(_slide_pos)

    elif trans_type == 'zoom_in_out':
        zoom_strength = transition_cfg.get('zoom_strength', 0.4)
        orig_w = clip.w
        orig_h = clip.h
        def _zoom_func(t):
            if t > duration:
                return 1.0
            frac = t / duration
            from core.animation_utils import ease_in_out_cubic, lerp
            eased = ease_in_out_cubic(frac)
            return lerp(1.0 + zoom_strength, 1.0, eased)
        zoomed = clip.with_effects([vfx.Resize(_zoom_func)])
        def _center_pos(t):
            z = _zoom_func(t)
            return (-orig_w * (z - 1.0) / 2, -orig_h * (z - 1.0) / 2)
        return zoomed.with_position(_center_pos)

    return clip


class BaseMontageEngine:
    def __init__(self, width=1080, height=1920, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        self.media_engine = MediaEngine(width, height, fps)
        os.makedirs("temp", exist_ok=True)

    def render(self, scenes, audio_path, output_path, preset, progress_callback=None, render_threads=4):
        try:
            audio = AudioFileClip(audio_path)
            final_clips = []
            trans_cfg = preset.get('transition', {})

            for i, scene in enumerate(scenes):
                start_time = scene['start']
                
                if i < len(scenes) - 1:
                    next_start = scenes[i+1]['start']
                    total_dur = next_start - start_time
                else:
                    total_dur = audio.duration - start_time
                
                overhang = trans_cfg.get('duration', 0) if trans_cfg.get('type') == 'crossfade' else 0
                total_dur += overhang

                logger.info(f"--- Processing Scene {i} ---")
                logger.info(f"Asset: {scene['asset_path']} | Duration: {total_dur}s")

                clip = self.media_engine.process_asset(
                    scene['asset_path'], 
                    total_dur, 
                    mode=preset.get("resize_mode", "fit"),
                    offset=scene.get('start_offset', 0),
                    allow_effects=scene.get('allow_montage_effects', True),
                    effects=preset.get('effects', [])
                )
                
                clip = clip.with_start(start_time)
                clip = _apply_transition(clip, trans_cfg, i == 0, self.width, self.height)
                
                final_clips.append(clip)
                logger.info(f"Scene {i} added successfully.")

            video_track = CompositeVideoClip(final_clips, size=(self.width, self.height))
            final_video = video_track.with_audio(audio).with_duration(audio.duration)
            
            temp_audio = os.path.join("temp", f"temp_audio_{os.path.basename(output_path)}.m4a")
            render_logger = TelegramProgressLogger(callback=progress_callback) if progress_callback else "bar"

            final_video.write_videofile(
                output_path, 
                fps=self.fps, 
                codec="libx264", 
                audio_codec="aac",
                temp_audiofile=temp_audio,
                remove_temp=True,
                threads=render_threads,
                preset="veryfast",
                logger=render_logger
            )
            return True
        except Exception as e:
            logger.error(f"Render failed: {e}", exc_info=True)
            return False


class VerticalMontageEngine(BaseMontageEngine):
    def __init__(self, fps=30):
        super().__init__(1080, 1920, fps)


class WideMontageEngine(BaseMontageEngine):
    def __init__(self, fps=30):
        super().__init__(1920, 1080, fps)


def run_montage(scenes, audio_path, output_path, preset, progress_callback=None, sound_map=None, width=1080, height=1920, render_threads=4):
    if width > height:
        engine = WideMontageEngine()
    else:
        engine = VerticalMontageEngine()
    return engine.render(scenes, audio_path, output_path, preset, progress_callback, render_threads=render_threads)
