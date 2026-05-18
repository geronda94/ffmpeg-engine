from PIL import Image, ImageDraw, ImageFont
import os

font_path = "assets/fonts/Montserrat-Bold.ttf"
output_path = "local_assets/logo/tech.png"

# Создаем прозрачное изображение
width, height = 700, 180
img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Загружаем шрифт
font_size = 72
font = ImageFont.truetype(font_path, font_size)

# Сегменты текста с их цветами
segments = [
    {"text": "IT", "color": (255, 255, 255, 255)},
    {"text": "2", "color": (0, 229, 255, 255)}, # Неоновый циан #00E5FF
    {"text": "B", "color": (255, 255, 255, 255)},
    {"text": ".", "color": (0, 229, 255, 255)},
    {"text": "top", "color": (255, 255, 255, 255)}
]

# Вычисляем общую ширину для центрирования
total_width = 0
segment_widths = []
for seg in segments:
    w = draw.textlength(seg["text"], font=font)
    segment_widths.append(w)
    total_width += w

# Начальная координата X для идеального центрирования
x = (width - total_width) // 2

# Начальная координата Y (вертикальное центрирование)
bbox = draw.textbbox((0, 0), "IT2B.top", font=font)
text_h = bbox[3] - bbox[1]
y = (height - text_h) // 2 - 10 

# Рендерим сегменты по очереди
for i, seg in enumerate(segments):
    draw.text((x, y), seg["text"], fill=seg["color"], font=font)
    x += segment_widths[i]

# Сохраняем изображение
os.makedirs(os.path.dirname(output_path), exist_ok=True)
img.save(output_path, "PNG")
print(f"Successfully generated new transparent IT logo at {output_path}")
