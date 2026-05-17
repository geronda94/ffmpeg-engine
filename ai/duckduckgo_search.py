import logging

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
    "legacyicons", "monasteryicons", "shutterstock", "depositphotos", "istockphoto", "istock",
    "alamy", "gettyimages", "123rf", "dreamstime", "freepik", "vecteezy", "vectorstock",
    "pinterest", "etsy", "ebay", "amazon", "redbubble", "teepublic", "society6", "stockphoto",
    "canva", "adobe", "pond5", "bigstockphoto", "cn-", "cn_"
]


def search_images_ddg(query: str, max_results: int = 15, min_size: int = 500) -> list:
    if not DDG_AVAILABLE:
        return []

    try:
        results = []
        safe_query = f"{query} -site:pinterest.com -site:shutterstock.com -site:legacyicons.com -site:monasteryicons.com -site:alamy.com"
        with DDGS() as ddgs:
            for r in ddgs.images(safe_query, max_results=max_results + 15):
                img_url = r.get("image", "").lower()
                source_url = r.get("url", "").lower()
                title = r.get("title", "").lower()
                if any(bad in img_url or bad in source_url or bad in title for bad in WATERMARK_BLACKLIST):
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
        logger.info(f"DDG search '{query}': {len(results)} results (min {min_size}px, watermark filtered)")
        return results
    except Exception as e:
        logger.error(f"DDG search error: {e}")
        return []
