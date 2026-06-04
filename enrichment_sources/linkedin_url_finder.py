"""
enrichment_sources/linkedin_url_finder.py
------------------------------------------
LinkedIn Company URL Finder — Priority 2.3 in the fallback chain.

Strategy
--------
When a partner's ``company_linkedin_url`` is not already known, this source
performs a targeted Tavily web search using keywords we have in the DB:

    site:linkedin.com/company  "<partner_name>"  <category>  <region>

The first matching result that looks like a real LinkedIn company URL is
returned.  The result is stored on the partner record as ``company_linkedin_url``
so the downstream LinkedIn employee scraper (Priority 2.5) can use it.

Why Tavily?
-----------
- Native LangChain / LangGraph integration
- Returns clean, structured JSON (no HTML scraping needed)
- 1 000 free searches/month on the free tier
- ``include_domains`` filter makes it trivially precise

Environment variable required
------------------------------
  TAVILY_API_KEY   — your Tavily API key (https://tavily.com)

Docs: https://docs.tavily.com/docs/python-sdk/tavily-search
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

# Regex to extract a clean LinkedIn company URL from any result URL
_LINKEDIN_COMPANY_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/company/[A-Za-z0-9\-_%]+",
    re.IGNORECASE,
)


def _build_query(partner_name: str, category: str, region: str) -> str:
    """
    Build a precise Tavily search query for a company's LinkedIn page.

    Example output:
        "Mondee" adventure sports UAE site:linkedin.com/company
    """
    parts = [f'"{partner_name}"']

    # Add category if meaningful (avoid generic words like "Other")
    if category and category.lower() not in ("other", "n/a", ""):
        # Take only the first 3 words to keep the query concise
        short_cat = " ".join(category.split()[:3])
        parts.append(short_cat)

    # Translate DB region codes into human-readable geo terms
    if region:
        region_lower = region.strip().lower()
        if region_lower in ("local", "uae"):
            parts.append("UAE")
        elif region_lower == "international":
            pass  # Don't restrict geo for international partners
        else:
            parts.append(region)

    parts.append("site:linkedin.com/company")
    return " ".join(parts)


def _extract_linkedin_url(results: list[dict]) -> str | None:
    """
    Walk Tavily results and return the first LinkedIn company URL found.

    Checks both the result ``url`` field and the ``content`` snippet.
    """
    for result in results:
        # 1. Check the direct URL
        url: str = result.get("url", "")
        m = _LINKEDIN_COMPANY_RE.match(url)
        if m:
            # Strip trailing slashes / query params for a clean canonical URL
            return m.group(0).rstrip("/")

        # 2. Fallback: scan the content snippet for an embedded URL
        content: str = result.get("content", "")
        m = _LINKEDIN_COMPANY_RE.search(content)
        if m:
            return m.group(0).rstrip("/")

    return None


async def find_company_linkedin_url(
    partner_name: str,
    category: str = "",
    region: str = "",
    website: str = "",
) -> dict:
    """
    Search Tavily for a company's LinkedIn page URL.

    Parameters
    ----------
    partner_name : str
        The partner / company name from the DB.
    category : str
        The company's category (e.g. "Adventure & Extreme Sports").
        Used to disambiguate common company names.
    region : str
        The partner's region from the DB ("Local", "International", etc.).
    website : str
        The company's website (used for future cross-validation, not yet active).

    Returns
    -------
    dict
        ``{"company_linkedin_url": "https://www.linkedin.com/company/..."}``
        or ``{}`` if:
          - ``TAVILY_API_KEY`` is not set
          - No LinkedIn company URL is found in the results
          - The Tavily call fails
    """
    if not TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not set — skipping LinkedIn URL search for %r.", partner_name)
        return {}

    if not partner_name:
        return {}

    query = _build_query(partner_name, category, region)
    logger.info("find_company_linkedin_url: query=%r", query)

    try:
        # Import here to avoid hard dependency if Tavily isn't installed
        from tavily import AsyncTavilyClient  # type: ignore

        client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
        response = await client.search(
            query=query,
            search_depth="basic",        # "basic" is faster & cheaper; "advanced" for better recall
            include_domains=["linkedin.com"],
            max_results=5,               # We only need the top hit
        )
    except ImportError:
        logger.error(
            "tavily-python not installed. Run: pip install tavily-python"
        )
        return {}
    except Exception as exc:
        logger.error("find_company_linkedin_url: Tavily search failed for %r: %s", partner_name, exc)
        return {}

    results: list[dict] = response.get("results", [])
    logger.debug("find_company_linkedin_url: got %d results for %r.", len(results), partner_name)

    linkedin_url = _extract_linkedin_url(results)

    if not linkedin_url:
        logger.info("find_company_linkedin_url: no LinkedIn URL found for %r.", partner_name)
        return {}

    logger.info(
        "find_company_linkedin_url: found LinkedIn URL for %r → %s",
        partner_name,
        linkedin_url,
    )
    return {"company_linkedin_url": linkedin_url}
