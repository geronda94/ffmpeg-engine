import os
import logging
from moviepy import VideoFileClip, ImageClip, TextClip, CompositeVideoClip, ColorClip
import moviepy.video.fx as vfx
from core.media_engine import MediaEngine
from core.animation_utils import ease_out_cubic, slide_in_position, logo_pulse_zoom

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


def render_dynamic_scene(preset_id, elements, duration, output_path, video_format="vertical"):
    from core.config_loader import get_config
    config = get_config("dynamic_scenes")
    preset = next((p for p in config.get("presets", []) if p.get("id") == preset_id), None)

    if preset and preset.get("layers"):
        from core.layer_renderer import render_from_layers
        return render_from_layers(preset, elements, duration, output_path, video_format)

    try:
        if video_format == "horizontal":
            width, height = 1920, 1080
        else:
            width, height = 1080, 1920

        media_engine = MediaEngine(width, height)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not os.path.exists(font_path):
            font_path = "DejaVu-Sans-Bold"

        clips = []

        # 1. ФОН
        bg_path = elements.get('bg') or elements.get('left')
        if bg_path and os.path.exists(bg_path):
            bg_scene = media_engine.process_asset(
                bg_path, duration, mode="cover", allow_effects=True, effects=["ken_burns"]
            )
            clips.append(bg_scene)
        else:
            clips.append(ColorClip(size=(width, height), color=(20, 20, 25)).with_duration(duration))

        # 2. ПРЕСЕТЫ
        if preset_id == "logo_float":
            logo_path = elements.get('logo')
            if logo_path and os.path.exists(logo_path):
                logo = ImageClip(logo_path).with_duration(duration)
                logo = logo.resized(width=width * 0.4)

                def _logo_zoom(t):
                    return logo_pulse_zoom(t, duration)
                logo = logo.with_effects([vfx.Resize(_logo_zoom)])
                logo = logo.with_position("center")
                clips.append(logo)

        elif preset_id == "price_tag":
            title_text = elements.get('title', "Product")
            price_new = elements.get('price_new', "0")
            price_old = elements.get('price_old', "")
            discount = elements.get('discount', "")

            panel_h = int(height * 0.25)
            panel_y = int(height * 0.7)

            panel = ColorClip(size=(width - 100, panel_h), color=(0, 0, 0)).with_opacity(0.8).with_duration(duration)
            panel = panel.with_effects([vfx.FadeIn(0.5)])
            panel = create_animation_slide(panel, (width, panel_y), (50, panel_y), duration=0.8)
            clips.append(panel)

            txt_title = TextClip(text=title_text, font_size=70, color='white', font=font_path,
                                 method='caption', size=(width-200, None)).with_duration(duration)
            txt_title = create_animation_slide(txt_title, (width, panel_y + 40), (100, panel_y + 40), duration=1.0)
            clips.append(txt_title)

            txt_price = TextClip(text=f"{price_new} ₽", font_size=140, color=(255, 215, 0), font=font_path).with_duration(duration)
            txt_price = create_animation_slide(txt_price, (width, panel_y + 160), (100, panel_y + 160), duration=1.2)
            clips.append(txt_price)

            if price_old:
                txt_old = TextClip(text=f"{price_old} ₽", font_size=60, color=(153, 153, 153), font=font_path).with_duration(duration)
                txt_old = create_animation_slide(txt_old, (width, panel_y + 300), (100, panel_y + 300), duration=1.4)
                strike = ColorClip(size=(txt_old.w + 10, 4), color=(255, 51, 51)).with_duration(duration)
                strike = create_animation_slide(strike, (width, panel_y + 335), (100, panel_y + 335), duration=1.4)
                clips.extend([txt_old, strike])

            if discount:
                b_w, b_h = 220, 110
                badge = ColorClip(size=(b_w, b_h), color=(230, 57, 70)).with_duration(duration)
                badge = create_animation_slide(badge, (width, panel_y + 160), (width - 320, panel_y + 160), duration=1.3)
                txt_disc = TextClip(text=f"-{discount}%", font_size=55, color='white', font=font_path).with_duration(duration)
                txt_disc = create_animation_slide(txt_disc, (width, panel_y + 185), (width - 300, panel_y + 185), duration=1.3)
                clips.extend([badge, txt_disc])

        elif preset_id == "split_compare":
            left_p, right_p = elements.get('left'), elements.get('right')
            if left_p and right_p:
                if video_format == "vertical":
                    part_w, part_h = width, height // 2
                    engine_part = MediaEngine(part_w, part_h)
                    left = engine_part.process_asset(left_p, duration, mode="cover")
                    right = engine_part.process_asset(right_p, duration, mode="cover")

                    left = create_animation_slide(left.with_position((0, 0)), (0, -part_h), (0, 0), duration=1.0)
                    right = create_animation_slide(right.with_position((0, part_h)), (0, height), (0, part_h), duration=1.0)
                else:
                    part_w, part_h = width // 2, height
                    engine_part = MediaEngine(part_w, part_h)
                    left = engine_part.process_asset(left_p, duration, mode="cover")
                    right = engine_part.process_asset(right_p, duration, mode="cover")

                    left = create_animation_slide(left.with_position((0, 0)), (-part_w, 0), (0, 0), duration=1.0)
                    right = create_animation_slide(right.with_position((part_w, 0)), (width, 0), (part_w, 0), duration=1.0)

                clips.extend([left, right])

        final = CompositeVideoClip(clips, size=(width, height))
        final.write_videofile(
            output_path, fps=30, codec="libx264", audio=False,
            threads=4, preset="ultrafast", bitrate="2000k", logger=None
        )
        return output_path

    except Exception as e:
        logger.error(f"Dynamic Render Error: {e}", exc_info=True)
        return None
