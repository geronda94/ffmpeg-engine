import os
import numpy as np
from PIL import Image, ImageDraw

def generate_noise_plate():
    os.makedirs("local_assets/ui", exist_ok=True)

    w, h = 900, 250
    radius = 25
    base_color = (38, 38, 38, 217)  # Темный антрацит ~85%
    outline_color = (255, 255, 255, 140) # Усиленная светлая рамка (было 80)
    border_width = 3 # Утолщенная рамка (было 2)

    # 1. Рисуем базовую плашку
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, w, h), 
        radius=radius, 
        fill=base_color, 
        outline=outline_color, 
        width=border_width
    )

    # 2. Генерируем монохромный шум (numpy)
    img_array = np.array(img).astype(np.int16)
    # Интенсивность шума чуть выше для фактурности
    noise = np.random.randint(-15, 15, (h, w), dtype=np.int16)

    # Применяем шум только там, где есть плашка (alpha > 0)
    alpha_mask = img_array[:, :, 3] > 0
    for i in range(3):
        img_array[:, :, i][alpha_mask] += noise[alpha_mask]

    # 3. Финализация
    np.clip(img_array, 0, 255, out=img_array)
    final_img = Image.fromarray(img_array.astype(np.uint8), 'RGBA')
    
    path = "local_assets/ui/plate_anthracite_noise.png"
    final_img.save(path)
    print(f"Плашка успешно сгенерирована: {path}")

if __name__ == "__main__":
    generate_noise_plate()
