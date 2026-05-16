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


def search_images_ddg(query: str, max_results: int = 15, min_size: int = 800) -> list:
    if not DDG_AVAILABLE:
        return []

    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.images(query, max_results=max_results):
                w = r.get("width", 0) or 0
                h = r.get("height", 0) or 0
                if min_size > 0 and (w < min_size or h < min_size):
                    continue
                results.append({
                    "url": r.get("image", ""),
                    "photographer": "DuckDuckGo",
                    "source": "ddg",
                    "width": w,
                    "height": h,
                    "title": r.get("title", ""),
                })
        logger.info(f"DDG search '{query}': {len(results)} results (min {min_size}px)")
        return results
    except Exception as e:
        logger.error(f"DDG search error: {e}")
        return []
