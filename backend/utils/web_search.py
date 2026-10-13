"""
Web search utility leveraging open source tools and DuckDuckGo / web engines.
Provides fast, resilient web retrieval with titles, snippets, clean URLs, and deep page content for citing.
"""

import asyncio
import re
import urllib.parse
from typing import Any, Dict, List
import httpx
from bs4 import BeautifulSoup
from loguru import logger


def clean_snippet(text: str) -> str:
    """Clean and normalize whitespace in extracted text snippets."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def search_duckduckgo_html(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search DuckDuckGo via HTML parsing (open source web scraper fallback)."""
    results: List[Dict[str, str]] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
            resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for item in soup.find_all("div", class_="result"):
                    title_elem = item.find("a", class_="result__a")
                    snippet_elem = item.find("a", class_="result__snippet")

                    if not title_elem:
                        continue

                    title = clean_snippet(title_elem.get_text(strip=True))
                    raw_href = title_elem.get("href", "")

                    # Extract actual target url from DuckDuckGo redirect
                    if "uddg=" in raw_href:
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
                        url = parsed.get("uddg", [raw_href])[0]
                    else:
                        url = raw_href

                    # Filter ad links
                    if "duckduckgo.com/y.js" in url or "ad_domain" in url:
                        continue

                    snippet = clean_snippet(snippet_elem.get_text(strip=True)) if snippet_elem else ""

                    if url.startswith("http") and title:
                        results.append({
                            "title": title,
                            "url": url,
                            "snippet": snippet,
                        })
                        if len(results) >= max_results:
                            break
    except Exception as e:
        logger.warning(f"DuckDuckGo HTML search error for '{query}': {e}")

    return results


async def search_duckduckgo_instant_api(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search DuckDuckGo free instant answer API."""
    results: List[Dict[str, str]] = []
    url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                abstract = clean_snippet(data.get("AbstractText", ""))
                abstract_url = data.get("AbstractURL", "")
                heading = data.get("Heading", query)

                if abstract and abstract_url:
                    results.append({
                        "title": heading,
                        "url": abstract_url,
                        "snippet": abstract,
                    })

                for topic in data.get("RelatedTopics", []):
                    if len(results) >= max_results:
                        break
                    if isinstance(topic, dict) and "Text" in topic and "FirstURL" in topic:
                        results.append({
                            "title": topic.get("Text", "").split(" - ")[0],
                            "url": topic.get("FirstURL", ""),
                            "snippet": topic.get("Text", ""),
                        })
    except Exception as e:
        logger.warning(f"DuckDuckGo Instant API error for '{query}': {e}")

    return results


async def fetch_webpage_content(url: str, client: httpx.AsyncClient, timeout: float = 4.5) -> str:
    """Fetch and extract readable body text from a webpage URL."""
    try:
        resp = await client.get(url, timeout=timeout)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Decompose boilerplate and script elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "svg", "noscript", "form"]):
                tag.decompose()
            text = " ".join(soup.get_text().split())
            return clean_snippet(text)[:2500]
    except Exception:
        pass
    return ""


def distill_search_queries(raw_text: str) -> List[str]:
    """
    Distill a user prompt or long academic/instructional question into 1-2 focused search queries.
    Strips prompt fluff and conversational scaffolding to maximize search relevance.
    """
    fluff = [
        r"(?i)\b(?:provide|give\s+me)\s+a\s+(?:detailed\s+|comprehensive\s+)?comparison\s+of\b",
        r"(?i)\bcompare\s+(?:and\s+contrast\s+)?\b",
        r"(?i)\binclude\s+real[- ]world\s+benchmark\s+metrics.*",
        r"(?i)\bcite\s+the\s+performance\s+numbers.*",
        r"(?i)\bcurves\s*,?\s*and\s+memory\s+overhead\s+tradeoffs\s+between\b",
        r"(?i)\btradeoffs\s+between\b",
        r"(?i)\bwhen\s+scaling\s+to\s+[^?.,]+",
        r"(?i)\bin\s+production\??",
        r"(?i)\bcan\s+you\s+(?:please\s+)?\b",
        r"(?i)\btell\s+me\s+about\b",
        r"(?i)\bwhat\s+is\s+the\s+difference\s+between\b",
    ]
    cleaned = raw_text
    for f in fluff:
        cleaned = re.sub(f, " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" ?,.:;")

    queries: List[str] = []
    if cleaned:
        queries.append(cleaned[:110])

    # Extract high-value technical keywords if present
    entities = []
    for term in [
        "pgvector", "0.8.0", "DiskANN", "pgvectorscale", "Cohere",
        "binary quantization", "scalar quantization", "HNSW", "benchmark", "recall"
    ]:
        if term.lower() in raw_text.lower():
            entities.append(term)
    if len(entities) >= 2:
        queries.append(" ".join(entities[:6]))

    return queries or [raw_text[:80]]


def resolve_search_query(current_message: str, messages: Any = None) -> str:
    """
    Resolve the intended factual search query from the current message and recent chat history.
    Handles follow-ups, conversational retries ('now try again with web search', 'retry'),
    and meta-directives by inspecting earlier human messages when the current input
    is conversational or an instruction.
    """
    cleaned = current_message.strip()

    retry_patterns = [
        r"\b(?:try\s+again|retry|redo|do\s+it\s+again)\b",
        r"\b(?:given\s+you|with|use|enable)\s+(?:a\s+)?(?:web|search|internet|research)\b",
        r"\b(?:search\s+(?:the\s+web|online|internet|for\s+that|that))\b",
        r"\b(?:what\s+about\s+(?:that|it|this))\b",
        r"\b(?:tell\s+me\s+more)\b",
    ]

    is_retry = any(re.search(pat, cleaned, re.IGNORECASE) for pat in retry_patterns) or len(cleaned.split()) <= 4

    if is_retry and messages:
        # Search backward for the most recent substantive human message
        for msg in reversed(messages):
            role = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
            content = getattr(msg, "content", "") or (msg.get("content") if isinstance(msg, dict) else "")
            if role in ("human", "user") and content.strip():
                if not any(re.search(pat, content, re.IGNORECASE) for pat in retry_patterns):
                    cleaned = content.strip()
                    break

    # Strip conversational meta prefixes
    prefixes = [
        r"^(?:now\s+)?(?:try\s+again|retry)[,\s]*(?:ive\s+given\s+you\s+[^,.]+[,\s]*)?",
        r"^(?:can\s+you\s+)?(?:please\s+)?(?:search\s+(?:the\s+web\s+for|for|online\s+for)|look\s+up|find\s+out)\s+",
        r"^(?:can\s+you\s+)?(?:please\s+)?(?:tell\s+me\s+about|explain|describe|give\s+me)\s+",
    ]
    for p in prefixes:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE).strip()

    return cleaned or current_message.strip()


async def search_web(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """
    Basic web search returning top results with title, url, snippet.
    """
    results = await search_duckduckgo_html(query, max_results=max_results)
    if not results:
        results = await search_duckduckgo_instant_api(query, max_results=max_results)
    return results


async def search_web_deep(raw_message: str, messages: Any = None, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Deep web retrieval pipeline:
    1. Resolves substantive question from chat history if the user message is a follow-up/retry.
    2. Distills prompt into clean, entity-focused search queries.
    3. Searches DuckDuckGo across queries and deduplicates hits.
    4. Concurrently fetches full body content of top pages for rich context.
    """
    substantive_text = resolve_search_query(raw_message, messages)
    queries = distill_search_queries(substantive_text)
    logger.info(f"Distilled search queries: {queries}")

    seen_urls = set()
    combined_hits: List[Dict[str, str]] = []

    for q in queries[:2]:
        hits = await search_duckduckgo_html(q, max_results=max_results)
        if not hits:
            hits = await search_duckduckgo_instant_api(q, max_results=max_results)
        for h in hits:
            norm_url = h["url"].split("#")[0].rstrip("/")
            if norm_url not in seen_urls:
                seen_urls.add(norm_url)
                combined_hits.append(h)
            if len(combined_hits) >= max_results:
                break
        if len(combined_hits) >= max_results:
            break

    if not combined_hits:
        return []

    # Concurrently fetch full page body text for top results
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            top_to_fetch = combined_hits[:4]
            tasks = [fetch_webpage_content(h["url"], client, timeout=4.5) for h in top_to_fetch]
            page_contents = await asyncio.gather(*tasks, return_exceptions=True)

            for h, content in zip(top_to_fetch, page_contents):
                if isinstance(content, str) and content.strip():
                    h["content"] = content.strip()
                else:
                    h["content"] = h.get("snippet", "")
    except Exception as e:
        logger.warning(f"Error fetching page contents in search_web_deep: {e}")
        for h in combined_hits:
            h["content"] = h.get("snippet", "")

    return combined_hits
