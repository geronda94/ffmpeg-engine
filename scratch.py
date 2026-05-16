import requests
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("PIXABAY_API_KEY")

r = requests.get("https://pixabay.com/api/", params={"key": API_KEY, "q": "nature", "image_type": "photo"})
data = r.json()
if "hits" in data and len(data["hits"]) > 0:
    url = data["hits"][0]["largeImageURL"]
    print(f"URL: {url}")
    
    r2 = requests.get(url)
    print(f"Status without UA: {r2.status_code}")
    
    r3 = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    print(f"Status with UA: {r3.status_code}")
