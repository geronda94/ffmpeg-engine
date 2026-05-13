import os
import logging
import moviepy.audio.fx as afx
from moviepy import AudioFileClip, CompositeVideoClip, ColorClip, AudioClip, concatenate_audioclips
from proglog import ProgressBarLogger
from core.media_engine import MediaEngine
from core.transitions import apply as apply_transition
from core.effects import collect_overlays

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

            if not active_bars:
                return
            bar_data = active_bars[-1]

        percent = int((bar_data['index'] / bar_data['total']) * 100)

        if percent != self.last_percent and (percent % 5 == 0 or percent == 100):
            self.last_percent = percent
            self.tg_callback(percent)


def _build_bg_music(sound_map, video_duration):
    if not sound_map:
        return None

    bg = sound_map.get("bg_music")
    if not bg or not bg.get("path"):
        return None

    path = bg["path"]
    volume = bg.get("volume", 0.30)
    loopable = bg.get("loopable", True)
    dur_sec = bg.get("duration_sec", 30)

    if not os.path.exists(path):
        logger.warning(f"Music file not found: {path}")
        return None

    track = AudioFileClip(path)
    track_dur = track.duration

    if track_dur <= 0:
        return None

    if not loopable or track_dur >= video_duration:
        clip = track.with_duration(min(video_duration, track_dur))
        return clip.with_volume_scaled(volume)

    segments = []
    remaining = video_duration
    fade_out = 2.0
    fade_in = 1.5
    gap = 1.0

    loop_count = 0
    while remaining > 0 and loop_count < 50:
        loop_count += 1
        is_first = len(segments) == 0

        if not is_first:
            silence = AudioClip(lambda t: 0, duration=gap)
            segments.append(silence)
            remaining -= gap

        if remaining <= 0:
            break

        is_last = remaining <= track_dur + fade_out
        seg_dur = min(track_dur, remaining + fade_out) if is_last else track_dur
        seg = track.subclipped(0, seg_dur).with_duration(seg_dur)

        if is_first and is_last:
            seg = seg.with_effects([afx.AudioFadeOut(min(fade_out, seg_dur * 0.5))])
        elif is_last:
            fi = min(fade_in, seg_dur * 0.3)
            fo = min(fade_out, seg_dur * 0.5)
            seg = seg.with_effects([afx.AudioFadeIn(fi), afx.AudioFadeOut(fo)])
        elif is_first:
            seg = seg.with_effects([afx.AudioFadeOut(min(fade_out, seg_dur * 0.5))])
        else:
            fi = min(fade_in, seg_dur * 0.3)
            fo = min(fade_out, seg_dur * 0.5)
            seg = seg.with_effects([afx.AudioFadeIn(fi), afx.AudioFadeOut(fo)])

        segments.append(seg)
        remaining -= seg_dur

    if not segments:
        return None

    result = concatenate_audioclips(segments) if len(segments) > 1 else segments[0]
    return result.with_volume_scaled(volume)


class BaseMontageEngine:
    def __init__(self, width=1080, height=1920, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        self.media_engine = MediaEngine(width, height, fps)
        os.makedirs("temp", exist_ok=True)

    def render(self, scenes, audio_path, output_path, preset, progress_callback=None, sound_map=None, render_threads=4):
        try:
            voice = AudioFileClip(audio_path).with_volume_scaled(2.0)
            video_duration = voice.duration
            final_clips = []
            trans_cfg = preset.get('transition', {})
            preset_effects = preset.get('effects', [])

            for i, scene in enumerate(scenes):
                start_time = scene['start']

                if i < len(scenes) - 1:
                    next_scene = scenes[i+1]
                    next_trans = next_scene.get('transition', trans_cfg)
                    next_start = next_scene['start']
                    total_dur = next_start - start_time
                    overhang = next_trans.get('duration', 0.5)
                else:
                    total_dur = video_duration - start_time
                    overhang = 0

                total_dur += overhang
                total_dur = max(0.5, total_dur)

                logger.info(f"--- Processing Scene {i} ---")
                logger.info(f"Asset: {scene['asset_path']} | Duration: {total_dur}s")

                effects_list = scene.get('effects', preset_effects)

                clip = self.media_engine.process_asset(
                    scene['asset_path'],
                    total_dur,
                    mode=scene.get("resize_mode", preset.get("resize_mode", "fit")),
                    offset=scene.get('start_offset', 0),
                    allow_effects=scene.get('allow_montage_effects', True),
                    effects=effects_list,
                    mirror=scene.get('mirror', False),
                )

                clip = clip.with_start(start_time)

                scene_trans = scene.get('transition', trans_cfg)
                clip = apply_transition(clip, scene_trans, i == 0, self.width, self.height)

                final_clips.append(clip)

                # --- NEW: ПРЕВЬЮ ОВЕРЛЕЙ ДЛЯ ПЕРВОГО КАДРА ---
                if i == 0 and scene.get('preview_text'):
                    try:
                        from core.preview_renderer import create_preview_overlay
                        from core.config_loader import get_config
                        p_config = get_config("preview_presets")
                        p_dur = p_config.get("display_duration", 3.0)
                        
                        p_overlay = create_preview_overlay(
                            scene['asset_path'],
                            scene['preview_text'],
                            scene.get('preview_highlight', ''),
                            p_config,
                            self.width,
                            self.height,
                            color_scheme=scene.get('preview_colors'),
                            duration=p_dur,
                            logo_path=scene.get('preview_logo'),
                            bg_color=scene.get('preview_bg_color'),
                            text_color=scene.get('preview_text_color'),
                            secondary_color=scene.get('preview_secondary_color'),
                            custom_font_path=scene.get('preview_font_path')
                        )
                        # Добавляем в конец списка клипов, чтобы был поверх всех
                        final_clips.append(p_overlay.with_start(0))
                        logger.info(f"✨ Preview overlay added to final stack (duration: {p_dur}s)")
                    except Exception as e:
                        logger.error(f"Failed to create preview overlay: {e}", exc_info=True)

                overlay_clips = collect_overlays(effects_list, self.width, self.height, total_dur)
                for ocl in overlay_clips:
                    final_clips.append(ocl.with_start(start_time))

                logger.info(f"Scene {i} added successfully. Overlays: {len(overlay_clips)}")

            bg_base = ColorClip(
                size=(self.width, self.height), color=(0, 0, 0)
            ).with_duration(video_duration)

            video_track = CompositeVideoClip([bg_base] + final_clips, size=(self.width, self.height), use_bgclip=True)

            bg_music = _build_bg_music(sound_map, video_duration)
            if bg_music:
                from moviepy import CompositeAudioClip
                import random
                music_offset = 0
                if any(s.get('mirror') for s in scenes):
                    music_offset = round(random.uniform(1.0, 3.0), 1)
                    logger.info(f"Mirrored project: applying music offset {music_offset}s")
                final_audio = CompositeAudioClip([voice, bg_music.with_start(music_offset)])
                logger.info(f"Background music applied at volume {sound_map.get('bg_music', {}).get('volume', 0.30)}")
            else:
                final_audio = voice
                logger.info("No background music, using voice-only audio.")

            final_video = video_track.with_audio(final_audio)

            temp_audio = os.path.join("temp", f"temp_audio_{os.path.basename(output_path)}.m4a")
            render_logger = TelegramProgressLogger(callback=progress_callback) if progress_callback else "bar"

            final_video.write_videofile(
                output_path,
                fps=self.fps,
                codec="libx264",
                audio_codec="aac",
                audio_bitrate="192k",
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
        finally:
            _clips_to_close = []
            for name in ('voice', 'bg_music', 'final_video', 'video_track'):
                obj = locals().get(name)
                if obj is not None and hasattr(obj, 'close'):
                    _clips_to_close.append(obj)
            if 'final_clips' in locals() and isinstance(final_clips, list):
                for c in final_clips:
                    if c is not None and hasattr(c, 'close'):
                        _clips_to_close.append(c)
            for c in _clips_to_close:
                try:
                    c.close()
                except Exception:
                    pass


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
    return engine.render(scenes, audio_path, output_path, preset, progress_callback, sound_map=sound_map, render_threads=render_threads)
