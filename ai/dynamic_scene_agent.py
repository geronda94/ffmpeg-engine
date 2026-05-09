import os
import logging
from moviepy import CompositeVideoClip, ColorClip
from core.media_engine import MediaEngine
from core.animation_utils import ease_out_cubic

logger = logging.getLogger(__name__)


def create_animation_slide(clip, start_pos, end_pos, duration=1.0):
    def pos_func(t):
        if t > duration:
            return end_pos
        p = t / duration
        eased = ease_out_cubic(p)
        return (
            start_pos[0] + (end_pos[0] - start_pos[0]) * eased,
            start_pos[1] + (end_pos[1] - start_pos[1]) * eased
        )
    return clip.with_position(pos_func)


def _render_split_compare(elements, duration, width, height, video_format):
    clips = []
    left_p, right_p = elements.get('left'), elements.get('right')
    if not left_p or not right_p:
        return clips

    clips.append(ColorClip(size=(width, height), color=(20, 20, 25)).with_duration(duration))

    if video_format == "horizontal":
        part_w, part_h = width // 2, height
        engine_part = MediaEngine(part_w, part_h)
        left = engine_part.process_asset(left_p, duration, mode="cover")
        right = engine_part.process_asset(right_p, duration, mode="cover")
        left = create_animation_slide(left.with_position((0, 0)), (-part_w, 0), (0, 0), duration=1.0)
        right = create_animation_slide(right.with_position((part_w, 0)), (width, 0), (part_w, 0), duration=1.0)
    else:
        part_w, part_h = width, height // 2
        engine_part = MediaEngine(part_w, part_h)
        left = engine_part.process_asset(left_p, duration, mode="cover")
        right = engine_part.process_asset(right_p, duration, mode="cover")
        left = create_animation_slide(left.with_position((0, 0)), (0, -part_h), (0, 0), duration=1.0)
        right = create_animation_slide(right.with_position((0, part_h)), (0, height), (0, part_h), duration=1.0)

    clips.extend([left, right])
    return clips


def render_dynamic_scene(preset_id, elements, duration, output_path, video_format="vertical"):
    from core.config_loader import get_config
    config = get_config("dynamic_scenes")
    preset = next((p for p in config.get("presets", []) if p.get("id") == preset_id), None)

    if preset and preset.get("layers"):
        from core.layer_renderer import render_from_layers
        return render_from_layers(preset, elements, duration, output_path, video_format)

    if video_format == "horizontal":
        width, height = 1920, 1080
    else:
        width, height = 1080, 1920

    try:
        clips = []

        if preset_id == "split_compare":
            clips = _render_split_compare(elements, duration, width, height, video_format)

        if not clips:
            logger.error(f"Dynamic Render Error: preset '{preset_id}' has no layers and no hardcoded handler.")
            return None

        final = CompositeVideoClip(clips, size=(width, height))
        final.write_videofile(
            output_path, fps=30, codec="libx264", audio=False,
            threads=4, preset="ultrafast", bitrate="2000k", logger=None
        )
        return output_path

    except Exception as e:
        logger.error(f"Dynamic Render Error: {e}", exc_info=True)
        return None
