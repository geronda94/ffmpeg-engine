import os
import logging
import moviepy.video.fx as vfx
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
from proglog import ProgressBarLogger

logger = logging.getLogger(__name__)

class TelegramProgressLogger(ProgressBarLogger):
    """Логгер с дебагом имен баров для v2.x."""
    def __init__(self, callback=None):
        super().__init__()
        self.callback = callback
        self.last_percent = -1

    def bars_callback(self, bar, attr, value, old_value=None):
        # Включаем логирование всех баров в консоль для отладки
        # print(f"DEBUG MOVIEPY BAR: {bar} | {attr}: {value}")
        
        # В v2.x MoviePy часто использует 't' (время) или 'frame'
        if bar in ['chunk', 't', 'frame']:
            total = self.bars[bar].get('total')
            if total and total > 0:
                percent = int((value / total) * 100)
                if percent % 10 == 0 and percent != self.last_percent:
                    self.last_percent = percent
                    if self.callback:
                        self.callback(percent)

class MontageAgent:
    def __init__(self, width=1080, height=1920, fps=30):
        self.width = width
        self.height = height
        self.fps = fps

    def apply_effects(self, clip, effects):
        new_effects = []
        for effect in effects:
            if effect == "soft_zoom":
                new_effects.append(vfx.Resize(lambda t: 1 + 0.03 * t))
            elif effect == "quick_zoom":
                new_effects.append(vfx.Resize(lambda t: 1 + 0.1 * t))
            elif effect == "slow_pull_back":
                new_effects.append(vfx.Resize(lambda t: 1.1 - 0.03 * t))
        if new_effects:
            return clip.with_effects(new_effects)
        return clip

    def render(self, scenes, audio_path, output_path, preset, progress_callback=None):
        """Рендеринг v9.2: Универсальный логгер прогресса."""
        try:
            audio = AudioFileClip(audio_path)
            clips = []
            
            trans_cfg = preset.get('transition')
            use_crossfade = trans_cfg and trans_cfg['type'] == 'crossfade'
            cross_dur = trans_cfg['duration'] if use_crossfade else 0

            for i, scene in enumerate(scenes):
                dur = scene['end'] - scene['start']
                if dur <= 0: dur = 0.5
                
                img_clip = ImageClip(scene['asset_path']).with_duration(dur)
                aspect_target = self.width / self.height
                aspect_img = img_clip.w / img_clip.h
                
                if aspect_img > aspect_target:
                    clip = img_clip.resized(height=self.height * 1.1)
                else:
                    clip = img_clip.resized(width=self.width * 1.1)
                
                clip = clip.cropped(x_center=clip.w/2, y_center=clip.h/2, width=self.width, height=self.height)
                clip = self.apply_effects(clip, preset.get('effects', []))
                
                if use_crossfade and i > 0:
                    clip = clip.with_effects([vfx.CrossFadeIn(cross_dur)])
                
                clips.append(clip)

            final_video = concatenate_videoclips(clips, method="compose", padding=-cross_dur if use_crossfade else 0)
            final_video = final_video.with_audio(audio)
            
            my_logger = TelegramProgressLogger(callback=progress_callback)
            
            final_video.write_videofile(
                output_path, 
                fps=self.fps, 
                codec="libx264", 
                audio_codec="aac",
                threads=4,
                preset="veryfast",
                logger=my_logger
            )
            
            audio.close()
            for c in clips: c.close()
            return True
        except Exception as e:
            logger.error(f"Montage Agent Critical Error: {e}", exc_info=True)
            return False

def run_montage(scenes, audio_path, output_path, preset, progress_callback=None):
    agent = MontageAgent()
    return agent.render(scenes, audio_path, output_path, preset, progress_callback)
