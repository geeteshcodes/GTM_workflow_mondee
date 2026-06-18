"""
enrichment_sources/website_scraper.py
--------------------------------------
Website Scraper — Fallback source (Priority 6) in the enrichment chain.

Purpose
-------
When Hunter + Apollo + LinkedIn all fail to fill a contact field, this scraper
hits the company's own website directly and extracts whatever is still missing.

It only runs for fields that are STILL missing after the full fallback chain —
never called if Hunter/Apollo already filled everything.

The domain comes from Hunter's result dict ("domain" key) or Apollo's org search.
No website URL needs to be pre-populated in the CRM.

Strategy
--------
1. Try /contact, /contact-us, /about, /about-us pages first (highest yield).
2. Fall back to the homepage if none of those return useful data.
3. Extract email, phone, LinkedIn using regex — no heavy HTML parsing needed.
4. Return only the fields that are still missing (passed in via `missing_fields`).

Return schema
-------------
{
    "email_id":         str | None,
    "phone_number":     str | None,
    "linkedin_profile": str | None,
    "scraped_from":     str,        # URL that yielded the data
}
Returns {} on any error or if nothing found.

No environment variables required.
"""

import logging
import re
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# Pages most likely to have contact info — tried in order
_CONTACT_PATHS = [
    "/contact",
    "/contact-us",
    "/contact_us",
    "/contactus",
    "/about",
    "/about-us",
    "/about_us",
    "/reach-us",
    "/get-in-touch",
]

# Regex patterns
_EMAIL_RE    = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE    = re.compile(
    r"(?:\+?\d[\d\s\-\(\)]{7,}\d)"  # international formats
)
_LINKEDIN_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:in|company)/[a-zA-Z0-9_\-\%]+"
)

# Generic email prefixes — we can do better than these from Hunter already
_GENERIC_PREFIXES = {
    "info", "contact", "hello", "support", "admin",
    "sales", "enquiries", "enquiry", "booking", "bookings",
    "reservations", "reception", "office", "team", "mail",
    "general", "service", "services", "help", "noreply",
    "no-reply", "donotreply",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_generic_email(email: str) -> bool:
    prefix = email.split("@")[0].lower().strip()
    return prefix in _GENERIC_PREFIXES


def _clean_domain(raw: str) -> str:
    """Normalise a raw domain or URL to a bare https:// base URL."""
    if not raw:
        return ""
    raw = raw.strip()
    if not raw.startswith("http"):
        raw = "https://" + raw
    parsed = urlparse(raw)
    # Rebuild as scheme + netloc only
    return f"{parsed.scheme}://{parsed.netloc}"


def _extract_emails(text: str, prefer_personal: bool = True) -> list[str]:
    """Extract all emails from text. If prefer_personal, sort personal first."""
    found = list(set(_EMAIL_RE.findall(text)))
    if prefer_personal:
        personal = [e for e in found if not _is_generic_email(e)]
        generic  = [e for e in found if _is_generic_email(e)]
        return personal + generic
    return found


def _extract_phones(text: str) -> list[str]:
    """Extract all phone numbers from text, cleaned up."""
    raw_phones = _PHONE_RE.findall(text)
    cleaned = []
    for p in raw_phones:
        p = p.strip()
        # Filter out numbers that are too short or look like dates/zip codes
        digits = re.sub(r"\D", "", p)
        if len(digits) >= 7:
            cleaned.append(p)
    return list(set(cleaned))


def _extract_linkedin(text: str) -> str | None:
    """Extract the first LinkedIn company or person URL from text."""
    matches = _LINKEDIN_RE.findall(text)
    # Prefer /company/ URLs for business pages
    company = [m for m in matches if "/company/" in m]
    if company:
        return company[0]
    if matches:
        return matches[0]
    return None


async def _fetch_page(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetch a page and return its text, or None on failure."""
    try:
        resp = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=10.0)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception as exc:
        logger.debug("Scraper: failed to fetch %r — %s", url, exc)
        return None


# ── Main Scraper ───────────────────────────────────────────────────────────────

async def scrape_website(
    domain: str,
    missing_fields: list[str],
) -> dict:
    """
    Scrape a company website for missing contact fields.

    Parameters
    ----------
    domain : str
        The company domain from Hunter ("domain" key) or Apollo org search.
        Can be bare domain ("alboommarine.com") or full URL.
    missing_fields : list[str]
        Fields still missing after Hunter + Apollo — only these are extracted.
        Subset of: ["email_id", "phone_number", "linkedin_profile"]

    Returns
    -------
    dict — keys matching missing_fields that were found, plus "scraped_from".
    Returns {} if nothing found or domain is empty.
    """
    if not domain or not missing_fields:
        return {}

    base_url = _clean_domain(domain)
    if not base_url:
        logger.warning("Scraper: could not normalise domain %r — skipping.", domain)
        return {}

    logger.info(
        "Scraper: starting for domain=%r, missing=%s",
        domain, missing_fields,
    )

    result: dict = {}
    scraped_from: str = ""

    # Pages to try — contact/about paths first, then homepage
    pages_to_try = [urljoin(base_url, path) for path in _CONTACT_PATHS] + [base_url]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for page_url in pages_to_try:
            text = await _fetch_page(client, page_url)
            if not text:
                continue

            page_result: dict = {}

            # Extract only what's still missing
            if "email_id" in missing_fields and "email_id" not in result:
                emails = _extract_emails(text, prefer_personal=True)
                if emails:
                    page_result["email_id"] = emails[0]

            if "phone_number" in missing_fields and "phone_number" not in result:
                phones = _extract_phones(text)
                if phones:
                    page_result["phone_number"] = phones[0]

            if "linkedin_profile" in missing_fields and "linkedin_profile" not in result:
                linkedin = _extract_linkedin(text)
                if linkedin:
                    page_result["linkedin_profile"] = linkedin

            if page_result:
                result.update(page_result)
                scraped_from = page_url
                logger.info(
                    "Scraper: found %s on %r",
                    list(page_result.keys()), page_url,
                )

            # Stop if all missing fields are now resolved
            if all(f in result for f in missing_fields):
                logger.info("Scraper: all missing fields resolved from %r.", page_url)
                break

    if result:
        result["scraped_from"] = scraped_from
        logger.info(
            "Scraper: final result for %r — fields=%s source=%r",
            domain, list(result.keys()), scraped_from,
        )
    else:
        logger.info("Scraper: nothing found for domain %r.", domain)

    return result