import os
import numpy as np
from PIL import Image, ImageDraw

VARIANTS = [
    {"name": "plate_anthracite", "base": (38, 38, 38, 217), "outline": (255, 255, 255, 140), "border": 3},
    {"name": "plate_gold", "base": (40, 30, 10, 210), "outline": (212, 175, 55, 160), "border": 3},
    {"name": "plate_red_sale", "base": (180, 30, 30, 200), "outline": (255, 80, 80, 150), "border": 3},
    {"name": "plate_blue_night", "base": (15, 25, 50, 210), "outline": (80, 140, 220, 150), "border": 3},
    {"name": "plate_glass", "base": (255, 255, 255, 40), "outline": (255, 255, 255, 80), "border": 2},
    {"name": "plate_minimal", "base": (20, 20, 22, 230), "outline": (80, 80, 85, 90), "border": 2},
    {"name": "plate_green_premium", "base": (10, 40, 25, 210), "outline": (60, 180, 110, 150), "border": 3},
]

def generate_plate(name, base_color, outline_color, border_width):
    w, h = 900, 260
    radius = 28
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, w, h),
        radius=radius,
        fill=base_color,
        outline=outline_color,
        width=border_width
    )
    img_array = np.array(img).astype(np.int16)
    noise = np.random.randint(-12, 12, (h, w), dtype=np.int16)
    alpha_mask = img_array[:, :, 3] > 0
    for i in range(3):
        img_array[:, :, i][alpha_mask] += noise[alpha_mask]
    np.clip(img_array, 0, 255, out=img_array)
    final_img = Image.fromarray(img_array.astype(np.uint8))
    path = f"local_assets/ui/{name}_noise.png"
    final_img.save(path)
    print(f"  {path}")

if __name__ == "__main__":
    os.makedirs("local_assets/ui", exist_ok=True)
    for v in VARIANTS:
        generate_plate(v["name"], v["base"], v["outline"], v["border"])
    print("Done.")
