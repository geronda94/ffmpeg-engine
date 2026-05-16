import os
from PIL import Image, ImageDraw, ImageFilter

def add_glass_plate(input_path, output_path, padding=40, radius=15, opacity=160):
    if not os.path.exists(input_path):
        print(f"File not found: {input_path}")
        return

    # Загружаем оригинальное лого
    logo = Image.open(input_path).convert("RGBA")
    w, h = logo.size

    # Уменьшим само лого, если оно слишком большое (например, чтобы плашка смотрелась аккуратнее)
    # 1492x385 - это огромное лого. Сделаем его, скажем, высотой 200px
    target_h = 200
    if h > target_h:
        ratio = target_h / float(h)
        target_w = int(float(w) * ratio)
        logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
        w, h = logo.size

    # Размеры плашки
    new_w = w + padding * 2
    new_h = h + padding * 2

    # Создаем холст
    base = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))

    # Маска для закругленных углов
    mask = Image.new("L", (new_w, new_h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, new_w, new_h), radius=radius, fill=opacity)

    # Рисуем саму "стеклянную" плашку (полупрозрачный черный/темно-синий)
    # Техничный темный цвет
    plate = Image.new("RGBA", (new_w, new_h), (15, 20, 30, 255))
    base.paste(plate, (0, 0), mask)

    # Добавляем светлую обводку по краю для эффекта "стекла" (glassmorphism)
    border_mask = Image.new("L", (new_w, new_h), 0)
    draw_b = ImageDraw.Draw(border_mask)
    draw_b.rounded_rectangle((1, 1, new_w - 2, new_h - 2), radius=radius, outline=120, width=2)
    border = Image.new("RGBA", (new_w, new_h), (255, 255, 255, 255))
    base.paste(border, (0, 0), border_mask)

    # Вставляем оригинальное лого по центру
    base.paste(logo, (padding, padding), logo)

    # Сохраняем поверх
    base.save(output_path)
    print(f"Success! Saved to {output_path}")

if __name__ == "__main__":
    add_glass_plate("local_assets/logo/tech.png", "local_assets/logo/tech.png", padding=60, radius=25, opacity=140)
