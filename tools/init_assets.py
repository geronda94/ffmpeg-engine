import os
import subprocess
import numpy as np
from PIL import Image, ImageDraw

def generate_static_plate():
    os.makedirs("local_assets/ui", exist_ok=True)
    w, h = 900, 250
    radius = 25
    base_color = (38, 38, 38, 217)  # Темный антрацит
    outline_color = (255, 255, 255, 140) # Усиленная рамка
    border_width = 3

    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=base_color, outline=outline_color, width=border_width)

    # Запекаем шум
    img_array = np.array(img).astype(np.int16)
    noise = np.random.randint(-15, 15, (h, w), dtype=np.int16)
    alpha_mask = img_array[:, :, 3] > 0
    for i in range(3):
        img_array[:, :, i][alpha_mask] += noise[alpha_mask]

    np.clip(img_array, 0, 255, out=img_array)
    final_img = Image.fromarray(img_array.astype(np.uint8), 'RGBA')
    final_img.save("local_assets/ui/plate_static.png")
    print("Создано: local_assets/ui/plate_static.png")

def generate_test_animation():
    output = "local_assets/ui/test_anim.webm"
    # Безопасный вызов через subprocess
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=200x200:d=2:r=30",
        "-vf", "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='128+127*sin(2*PI*t/2)'",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", output
    ]
    subprocess.run(cmd, capture_output=True)
    if os.path.exists(output):
        print(f"Создано: {output} (анимированный WebM)")
    else:
        print(f"Не удалось создать анимированный WebM")

if __name__ == "__main__":
    generate_static_plate()
    generate_test_animation()
