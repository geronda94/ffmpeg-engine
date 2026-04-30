import os
import logging
from moviepy import VideoFileClip, ImageClip, TextClip, CompositeVideoClip, ColorClip
import moviepy.video.fx as vfx

logger = logging.getLogger(__name__)

def render_dynamic_scene(preset_id: str, elements: dict, duration: float, output_path: str, width=1080, height=1920):
    """
    Рендерит мини-видео (пре-рендер) на основе пресета и собранных элементов.
    """
    try:
        clips = []
        
        if preset_id == "logo_float":
            # Elements: bg (media), logo (photo)
            bg_path = elements['bg']
            logo_path = elements['logo']
            
            # Фоновый клип
            if bg_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                bg = ImageClip(bg_path).with_duration(duration).resized(width=width, height=height)
            else:
                bg = VideoFileClip(bg_path).without_audio().subclipped(0, duration).resized(width=width, height=height)
            clips.append(bg)
            
            # Логотип с пульсацией
            logo_w = 300
            logo = ImageClip(logo_path).with_duration(duration).resized(width=logo_w)
            # Эффект пульсации через зум
            logo = logo.with_effects([vfx.Resize(lambda t: 1.0 + 0.05 * (t % 2 if t % 2 < 1 else 2 - t % 2))])
            # Позиционируем в правый верхний угол с отступом 50px
            logo = logo.with_position((width - logo_w - 50, 50))
            clips.append(logo)

        elif preset_id == "price_tag":
            # Elements: bg (media), title (text), price (text)
            bg_path = elements['bg']
            title_txt = elements['title']
            price_txt = elements['price']
            
            if bg_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                bg = ImageClip(bg_path).with_duration(duration).resized(width=width, height=height)
            else:
                bg = VideoFileClip(bg_path).without_audio().subclipped(0, duration).resized(width=width, height=height)
            clips.append(bg)
            
            # Плашка под текст
            box = ColorClip(size=(width - 200, 400), color=(0, 0, 0)).with_opacity(0.6).with_duration(duration)
            box = box.with_position(("center", 1400))
            clips.append(box)
            
            # Поиск шрифта на Linux
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if not os.path.exists(font_path):
                font_path = "DejaVu-Sans-Bold" # Попытка через ImageMagick/Pillow

            # Тексты
            title_clip = TextClip(
                text=title_txt, 
                font_size=70, 
                color='white', 
                font=font_path, 
                method='caption', 
                size=(width-300, None)
            ).with_duration(duration)
            title_clip = title_clip.with_position(("center", 1450))
            
            price_clip = TextClip(
                text=price_txt, 
                font_size=120, 
                color='yellow', 
                font=font_path, 
                method='caption',
                size=(width-300, None)
            ).with_duration(duration)
            price_clip = price_clip.with_position(("center", 1550))
            
            clips.extend([title_clip, price_clip])

        elif preset_id == "split_compare":
            # Elements: left (media), right (media)
            l_path = elements['left']
            r_path = elements['right']
            
            def process_side(path):
                if path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    return ImageClip(path).with_duration(duration).resized(height=height)
                return VideoFileClip(path).without_audio().subclipped(0, duration).resized(height=height)
            
            left = process_side(l_path).cropped(x1=width//4, x2=3*width//4).resized(width=width//2)
            right = process_side(r_path).cropped(x1=width//4, x2=3*width//4).resized(width=width//2)
            
            left = left.with_position((0, 0))
            right = right.with_position((width//2, 0))
            clips.extend([left, right])

        if not clips:
            return None
            
        final = CompositeVideoClip(clips, size=(width, height)).with_duration(duration)
        final.write_videofile(output_path, fps=24, codec="libx264", audio=False, logger=None)
        
        for c in clips: c.close()
        return output_path
        
    except Exception as e:
        logger.error(f"Dynamic Scene Render Error: {e}")
        return None
