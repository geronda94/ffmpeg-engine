import logging
import asyncio
import time

logger = logging.getLogger(__name__)

DDG_AVAILABLE = False
DDGS = None
try:
    from ddgs import DDGS as _DDGS
    DDGS = _DDGS
    DDG_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS as _DDGS
        DDGS = _DDGS
        DDG_AVAILABLE = True
        logger.warning("⚠️ Using legacy duckduckgo_search. Run: pip install ddgs")
    except ImportError:
        logger.warning("⚠️ Neither ddgs nor duckduckgo_search installed. DDG search disabled.")


WATERMARK_BLACKLIST = [
    # Stock/watermark sites
    "legacyicons", "monasteryicons", "shutterstock", "depositphotos", "istockphoto", "istock",
    "alamy", "gettyimages", "123rf", "dreamstime", "freepik", "vecteezy", "vectorstock",
    "pinterest", "pinimg", "etsy", "ebay", "amazon", "redbubble", "teepublic", "society6",
    "stockphoto", "canva", "adobe", "pond5", "bigstockphoto", "cn-", "cn_",
    # Vector icon repos (NOT Orthodox painted icons!)
    "flaticon", "icons8", "svgrepo", "thenounproject", "iconfinder",
    "iconarchive", "iconmonstr", "iconduck", "iconscout",
    # Design/UI platforms
    "dribbble", "behance",
    # E-commerce / product catalogs
    "salko", "lamoda", "wildberries", "aliexpress",
]



async def search_images_ddg_async(query: str, max_results: int = 15, min_size: int = 500) -> list:
    """Async wrapper for DDG search."""
    return await asyncio.to_thread(search_images_ddg, query, max_results, min_size)


def search_images_ddg(query: str, max_results: int = 15, min_size: int = 300,
                       max_retries: int = 3) -> list:
    """Поиск изображений через DuckDuckGo с ретраями и backoff."""
    if not DDG_AVAILABLE:
        return []

    for attempt in range(max_retries):
        try:
            results = []
            safe_query = (
                f"{query} -site:pinterest.com -site:shutterstock.com "
                f"-site:legacyicons.com -site:monasteryicons.com -site:alamy.com"
            )
            with DDGS() as ddgs:
                for r in ddgs.images(safe_query, max_results=max_results + 15):
                    img_url = r.get("image", "").lower()
                    source_url = r.get("url", "").lower()
                    title = r.get("title", "").lower()
                    if any(bad in img_url or bad in source_url or bad in title
                           for bad in WATERMARK_BLACKLIST):
                        continue
                    try:
                        w = int(r.get("width", 0) or 0)
                        h = int(r.get("height", 0) or 0)
                    except ValueError:
                        w, h = 0, 0
                    if min_size > 0 and (w < min_size or h < min_size):
                        continue
                    results.append({
                        "url": r.get("image", ""),
                        "photographer": "DuckDuckGo",
                        "source": "ddg",
                        "width": w,
                        "height": h,
                        "title": r.get("title", ""),
                        "tags": r.get("title", ""),
                    })
                    if len(results) >= max_results:
                        break
            logger.info(f"DDG search '{query}': {len(results)} results (min {min_size}px)")
            return results
        except Exception as e:
            if attempt < max_retries - 1:
                delay = 2 ** attempt  # 1, 2, 4 сек
                logger.warning(
                    f"DDG search attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"DDG search '{query}' failed after {max_retries} attempts: {e}")

    return []


async def reformulate_query_ai(scene_description: str, failed_queries: list,
                                style_id: str = "", script: str = "") -> list:
    """Просит LLM переформулировать запросы, если предыдущие не дали результатов."""
    try:
        from ai.llm_client import achat
        prompt = (
            "Previous image search queries returned ZERO results. "
            "Generate 2-3 NEW, DIFFERENT search queries for this scene.\n\n"
            f"Scene description: {scene_description}\n"
            f"Failed queries: {', '.join(failed_queries[:4])}\n\n"
            "Return ONLY a JSON array of strings: [\"query1\", \"query2\", \"query3\"]"
        )
        resp = await achat(prompt)
        import json, re
        match = re.search(r'\[.*\]', resp, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        logger.warning(f"reformulate_query_ai failed: {e}")
    return []
