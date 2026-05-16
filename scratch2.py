import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("PIXABAY_API_KEY")

async def test():
    async with aiohttp.ClientSession() as session:
        # Search
        async with session.get("https://pixabay.com/api/", params={"key": API_KEY, "q": "nature", "image_type": "photo"}) as r:
            data = await r.json()
            url = data["hits"][0]["largeImageURL"]
            print(f"URL: {url}")
        
        # Download
        async with session.get(url) as r:
            print(f"Status: {r.status}")
            if r.status != 200:
                print(f"Headers: {r.headers}")

asyncio.run(test())
