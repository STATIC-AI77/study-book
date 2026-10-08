"""
Web search utility leveraging open source tools and DuckDuckGo / web engines.
Provides fast, resilient web retrieval with titles, snippets, and clean URLs for citing.
"""

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
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers=headers) as client:
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


async def search_web(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """
    Search the web for query, returning top results with title, url, snippet.
    Uses DDG HTML parsing first, falling back to DuckDuckGo Instant API.
    """
    results = await search_duckduckgo_html(query, max_results=max_results)
    if not results:
        results = await search_duckduckgo_instant_api(query, max_results=max_results)
    return results
