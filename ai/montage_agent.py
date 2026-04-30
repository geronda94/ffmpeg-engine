import os
import logging
import moviepy.video.fx as vfx
from moviepy import ImageClip, VideoFileClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
from proglog import ProgressBarLogger
from core.media_engine import MediaEngine

logger = logging.getLogger(__name__)

class TelegramProgressLogger(ProgressBarLogger):
    """
    Кастомный логгер для передачи прогресса в Telegram.
    Наследуемся от ProgressBarLogger, но не мешаем ему работать с барами (tqdm/chunk).
    """
    def __init__(self, callback=None):
        super().__init__()
        self.tg_callback = callback
        self.last_percent = -1

    def callback(self, **kwargs):
        """Этот метод вызывается proglog при любом обновлении любого бара."""
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

class BaseMontageEngine:
    def __init__(self, width=1080, height=1920, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        self.media_engine = MediaEngine(width, height, fps)
        os.makedirs("temp", exist_ok=True)

    def render(self, scenes, audio_path, output_path, preset, progress_callback=None):
        try:
            audio = AudioFileClip(audio_path)
            final_clips = []
            trans_cfg = preset.get('transition', {})
            cross_dur = trans_cfg.get('duration', 0) if trans_cfg.get('type') == 'crossfade' else 0

            for i, scene in enumerate(scenes):
                start_time = scene['start']
                
                if i < len(scenes) - 1:
                    next_start = scenes[i+1]['start']
                    total_dur = (next_start - start_time) + cross_dur
                else:
                    total_dur = audio.duration - start_time
                
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
                
                if cross_dur > 0 and i > 0:
                    clip = clip.with_effects([vfx.CrossFadeIn(cross_dur)])
                
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
                threads=4,
                preset="veryfast",
                logger=render_logger
            )
            return True
        except Exception as e:
            logger.error(f"Render failed: {e}", exc_info=True)
            return False

class VerticalMontageEngine(BaseMontageEngine):
    """Движок для вертикальных видео (TikTok/Reels)"""
    def __init__(self, fps=30):
        super().__init__(1080, 1920, fps)

class WideMontageEngine(BaseMontageEngine):
    """Движок для горизонтальных видео (YouTube)"""
    def __init__(self, fps=30):
        super().__init__(1920, 1080, fps)

def run_montage(scenes, audio_path, output_path, preset, progress_callback=None, sound_map=None, width=1080, height=1920):
    """Единая точка входа для запуска монтажа."""
    if width > height:
        engine = WideMontageEngine()
    else:
        engine = VerticalMontageEngine()
        
    # Примечание: sound_map пока просто принимается, интеграция саунд-дизайна будет в Спринте 2
    return engine.render(scenes, audio_path, output_path, preset, progress_callback)
