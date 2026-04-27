import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

import os
import argparse
import random
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

def generate_image(prompt: str, output_path: str):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    
    print(f"🎨 Генерирую изображение: {prompt[:50]}...")
    
    try:
        # Пытаемся сгенерировать через Imagen 3
        # Если метод generate_image недоступен, пробуем альтернативный путь
        try:
            response = client.models.generate_images(
                model="imagen-3.0-generate-001",
                prompt=prompt,
                config=types.GenerateImageConfig(
                    number_of_images=1,
                    include_rai_reason=True,
                    output_mime_type="image/png"
                )
            )
            image_data = response.generated_images[0].image_bytes
        except Exception:
            # Если Imagen недоступен, пробуем Gemini с подсказкой (если поддерживается)
            # Или просто выбрасываем исключение для срабатывания Fallback
            raise Exception("Imagen API not available or limit reached")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(image_data)
            
        print(f"✅ Изображение сохранено: {output_path}")
        return True
        
    except Exception as e:
        print(f"⚠️ Ошибка генерации ({e}). Использую Fallback...")
        # FALLBACK: Берем любую существующую картинку из local_assets
        assets_dir = Path("local_assets")
        existing_images = list(assets_dir.glob("*.png")) + list(assets_dir.glob("*.jpg"))
        
        if existing_images:
            fallback_img = random.choice(existing_images)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(fallback_img, output_path)
            print(f"🔄 Использована заглушка: {fallback_img.name}")
            return True
        else:
            print("❌ Даже заглушек нет в local_assets!")
            return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    generate_image(args.prompt, args.output)
