"""Search + fetch backends.

`local`  : the fictional corpus in data/corpus.json (offline, deterministic -> reliable demos)
`tavily` : real web search via Tavily + httpx page fetch (optional)

Failure simulation (for demo scenario 10) is built into the local corpus:
  "simulate_failure": "always" -> dead link, every fetch fails
  "simulate_failure": "once"   -> first attempt fails, retry succeeds
"""
from __future__ import annotations

import asyncio
import json
import re
from functools import lru_cache

from rdi import config
from rdi.models import Page, SearchHit
from rdi.services.bm25 import BM25


class ToolFailure(Exception):
    """Recoverable tool failure (network, timeout, missing page)."""


REQUIRED_PAGE_FIELDS = ("url", "title", "publisher", "content")


def load_corpus(path) -> list[dict]:
    """Load + validate the fictional corpus. Fails early with a readable message (not a stack trace in the UI)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise ToolFailure(f"Corpus file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise ToolFailure(f"Corpus file is not valid JSON ({path}): {e}") from e
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list) or not pages:
        raise ToolFailure(f"Corpus {path} must be an object with a non-empty 'pages' list.")
    seen: set[str] = set()
    for i, p in enumerate(pages):
        missing = [k for k in REQUIRED_PAGE_FIELDS if not isinstance(p.get(k), str) or not p[k].strip()]
        if missing:
            raise ToolFailure(f"Corpus page #{i} is missing/empty fields: {missing}")
        if p["url"] in seen:
            raise ToolFailure(f"Corpus has a duplicate url: {p['url']}")
        seen.add(p["url"])
    return pages


class LocalCorpusBackend:
    def __init__(self, path=None):
        # resolved at call time (not import time) so tests / scenarios can redirect config.CORPUS_PATH
        self.pages: list[dict] = load_corpus(path or config.CORPUS_PATH)
        self.by_url = {p["url"]: p for p in self.pages}
        self.index = BM25([p["title"] + " " + p["publisher"] + " " + p["content"] for p in self.pages])

    async def search(self, query: str, k: int) -> list[SearchHit]:
        hits = []
        for i, score in self.index.top(query, k):
            p = self.pages[i]
            hits.append(SearchHit(url=p["url"], title=p["title"], snippet=p["content"][:180] + "...", score=round(score, 2)))
        return hits

    async def fetch(self, url: str, attempt: int) -> Page:
        await asyncio.sleep(0.05)  # pretend network
        p = self.by_url.get(url.strip())
        if p is None:
            raise ToolFailure(f"404 Not Found: {url}")
        mode = p.get("simulate_failure")
        if mode == "always" or (mode == "once" and attempt == 0):
            raise ToolFailure(f"Timeout while fetching {url} (attempt {attempt + 1})")
        return Page(url=p["url"], title=p["title"], publisher=p["publisher"], author=p.get("author", ""),
                    published=p.get("published", ""), source_type=p.get("source_type", "unknown"), content=p["content"])


class TavilyBackend:  # pragma: no cover - needs network + key
    def __init__(self):
        import httpx

        self.httpx = httpx

    async def search(self, query: str, k: int) -> list[SearchHit]:
        async with self.httpx.AsyncClient(timeout=20) as client:
            r = await client.post("https://api.tavily.com/search",
                                  json={"api_key": config.TAVILY_API_KEY, "query": query, "max_results": k})
            r.raise_for_status()
            return [SearchHit(url=x["url"], title=x.get("title", ""), snippet=x.get("content", "")[:200],
                              score=float(x.get("score", 0))) for x in r.json().get("results", [])]

    async def fetch(self, url: str, attempt: int) -> Page:
        try:
            async with self.httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": "rdi-course-project/1.0"})
                r.raise_for_status()
        except Exception as e:
            raise ToolFailure(f"Fetch failed for {url}: {e}") from e
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        title = re.search(r"<title>(.*?)</title>", r.text, re.S | re.I)
        return Page(url=url, title=title.group(1).strip() if title else url, content=text, source_type="unknown")


@lru_cache(maxsize=1)
def get_backend():
    if config.SEARCH_BACKEND == "tavily" and config.TAVILY_API_KEY:
        return TavilyBackend()
    return LocalCorpusBackend()


async def fetch_with_retry(url: str, retries: int = config.FETCH_RETRIES, on_retry=None) -> Page:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await get_backend().fetch(url, attempt)
        except ToolFailure as e:
            last = e
            if on_retry:
                on_retry(attempt, str(e))
            await asyncio.sleep(0.2 * (2 ** attempt))  # exponential backoff
    raise ToolFailure(f"{last} - gave up after {retries + 1} attempts")
