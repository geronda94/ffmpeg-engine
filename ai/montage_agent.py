import os
import logging
import moviepy.video.fx as vfx
from moviepy import ImageClip, VideoFileClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
from proglog import ProgressBarLogger

logger = logging.getLogger(__name__)

class TelegramProgressLogger(ProgressBarLogger):
    def __init__(self, callback=None):
        super().__init__()
        self.callback = callback
        self.last_percent = -1

    def bars_callback(self, bar, attr, value, old_value=None):
        total = self.bars[bar].get('total')
        if total and total > 0:
            percent = int((value / total) * 100)
            if percent % 5 == 0 and percent != self.last_percent:
                self.last_percent = percent
                if self.callback:
                    self.callback(percent)

class BaseMontageEngine:
    def __init__(self, width, height, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        os.makedirs("temp", exist_ok=True)

    def _smart_resize(self, clip, target_w, target_h, mode="cover"):
        clip_aspect = clip.w / clip.h
        target_aspect = target_w / target_h

        if mode == "cover":
            # Для фона делаем запас +2%, чтобы избежать рамок из-за округления
            work_w, work_h = target_w * 1.02, target_h * 1.02
            if clip_aspect > target_aspect:
                new_clip = clip.resized(height=work_h)
            else:
                new_clip = clip.resized(width=work_w)
            return new_clip.cropped(x_center=new_clip.w/2, y_center=new_clip.h/2, width=work_w, height=work_h)
        else: # mode="fit"
            if clip_aspect > target_aspect:
                return clip.resized(width=target_w)
            else:
                return clip.resized(height=target_h)

    def apply_preset_effects(self, clip, effects_list):
        new_effects = []
        for effect in effects_list:
            if effect == "soft_zoom":
                new_effects.append(vfx.Resize(lambda t: 1.05 + 0.04 * t))
            elif effect == "quick_zoom":
                new_effects.append(vfx.Resize(lambda t: 1.05 + 0.12 * t))
        return clip.with_effects(new_effects) if new_effects else clip

    def render(self, scenes, audio_path, output_path, preset, progress_callback=None):
        try:
            audio = AudioFileClip(audio_path)
            final_clips = []
            trans_cfg = preset.get('transition', {})
            cross_dur = trans_cfg.get('duration', 0) if trans_cfg.get('type') == 'crossfade' else 0

            for i, scene in enumerate(scenes):
                dur = scene['end'] - scene['start']
                clip = self.process_scene_asset(scene['asset_path'], dur, preset.get('effects', []))
                if cross_dur > 0 and i > 0:
                    clip = clip.with_effects([vfx.CrossFadeIn(cross_dur)])
                final_clips.append(clip)

            video_track = concatenate_videoclips(final_clips, method="compose", padding=-cross_dur if cross_dur > 0 else 0)
            final_video = video_track.with_audio(audio)
            
            temp_audio = os.path.join("temp", f"temp_audio_{os.path.basename(output_path)}.m4a")
            final_video.write_videofile(
                output_path, 
                fps=self.fps, 
                codec="libx264", 
                audio_codec="aac",
                temp_audiofile=temp_audio,
                remove_temp=True,
                threads=4,
                preset="veryfast",
                logger=TelegramProgressLogger(callback=progress_callback)
            )
            audio.close()
            for c in final_clips: c.close()
            return True
        except Exception as e:
            logger.error(f"Montage Engine Error: {e}", exc_info=True)
            return False

class VerticalMontageEngine(BaseMontageEngine):
    def process_scene_asset(self, asset_path, duration, effects):
        ext = os.path.splitext(asset_path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            raw = ImageClip(asset_path).with_duration(duration)
        else:
            raw = VideoFileClip(asset_path).subclipped(0, duration).with_duration(duration).without_audio()

        # ФОН: Cover (с запасом 2%) + Blur + Принудительный размер
        bg = self._smart_resize(raw, self.width, self.height, mode="cover")
        # ФИКС: Принудительно возвращаем точный размер кадра после блюра
        bg = bg.resized(0.02).resized(50.0).resized(width=self.width, height=self.height)
        bg = bg.with_effects([vfx.LumContrast(lum=-30)]).with_position("center")
        
        # ПЕРЕДНИЙ ПЛАН
        fg = self._smart_resize(raw, self.width, self.height, mode="fit")
        fg = self.apply_preset_effects(fg, effects)
        fg = fg.with_position("center")

        return CompositeVideoClip([bg, fg], size=(self.width, self.height)).with_duration(duration)

class WideMontageEngine(BaseMontageEngine):
    def process_scene_asset(self, asset_path, duration, effects):
        ext = os.path.splitext(asset_path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            raw = ImageClip(asset_path).with_duration(duration)
        else:
            raw = VideoFileClip(asset_path).subclipped(0, duration).with_duration(duration).without_audio()

        # ФОН: Cover + Blur + Принудительный размер
        bg = self._smart_resize(raw, self.width, self.height, mode="cover")
        bg = bg.resized(0.02).resized(50.0).resized(width=self.width, height=self.height)
        bg = bg.with_effects([vfx.LumContrast(lum=-30)]).with_position("center")
        
        # ПЕРЕДНИЙ ПЛАН
        fg = self._smart_resize(raw, self.width, self.height, mode="fit")
        fg = self.apply_preset_effects(fg, effects)
        fg = fg.with_position("center")

        return CompositeVideoClip([bg, fg], size=(self.width, self.height)).with_duration(duration)

def run_montage(scenes, audio_path, output_path, preset, progress_callback=None, overlays=None, width=1080, height=1920):
    engine = WideMontageEngine(width, height) if width > height else VerticalMontageEngine(width, height)
    return engine.render(scenes, audio_path, output_path, preset, progress_callback)
