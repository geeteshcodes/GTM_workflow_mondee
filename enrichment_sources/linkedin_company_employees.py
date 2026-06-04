"""
enrichment_sources/linkedin_company_employees.py
-------------------------------------------------
LinkedIn Company Employee Scraper — Priority 2.5 in the fallback chain.

Strategy
--------
Instead of hitting Apollo / Hunter and getting a generic support@ or info@
inbox, we:
  1. Scrape the company's LinkedIn page for employees via Apify.
  2. Filter for SENIOR-level roles only (VP, Director, Head, C-suite, Manager, etc.)
  3. Return the best candidate's LinkedIn profile URL so downstream enrichment
     (email-finding tools) can target a real decision-maker.

This source sits BEFORE Hunter and Apollo in the chain because a real named
contact is far more valuable than a domain-level email guess.

Actor used
----------
  Apify actor: «proxycurl/linkedin-company-employees»  (configurable via env)
  Docs: https://apify.com/proxycurl/linkedin-company-employees

Environment variables required
-------------------------------
  APIFY_API_TOKEN          — your Apify API token
  APIFY_LINKEDIN_EMP_ACTOR — actor ID/name (default: «easyapi/linkedin-company-employees-scraper»)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — pulled from env so nothing is hard-coded
# ---------------------------------------------------------------------------
APIFY_API_TOKEN: str = os.getenv("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID: str = os.getenv(
    "APIFY_LINKEDIN_EMP_ACTOR",
    "easyapi/linkedin-company-employees-scraper",  # sensible default
)
APIFY_BASE_URL = "https://api.apify.com/v2"

# Maximum employees to fetch from LinkedIn (cost control)
MAX_ITEMS: int = int(os.getenv("LINKEDIN_EMP_MAX_ITEMS", "30"))

# How long to wait for the Apify run to finish (seconds)
APIFY_POLL_TIMEOUT: int = int(os.getenv("APIFY_POLL_TIMEOUT_SEC", "90"))
APIFY_POLL_INTERVAL: int = 5  # seconds between status checks

# ---------------------------------------------------------------------------
# Seniority keywords — we ONLY want decision-makers
# ---------------------------------------------------------------------------
SENIOR_KEYWORDS: tuple[str, ...] = (
    # C-suite
    "ceo", "coo", "cto", "cfo", "cmo", "cpo", "cso", "cro",
    "chief",
    # VP / Director
    "vp", "vice president", "svp", "evp",
    "director",
    # Head / Lead
    "head of", "head,",
    "lead",
    # Manager (department/senior)
    "senior manager", "general manager",
    # Founder
    "founder", "co-founder",
    # Partner / Principal
    "partner", "principal",
    # President / MD / GM
    "president", "managing director", "md",
)


def _is_senior(headline: str | None) -> bool:
    """Return True if the employee headline suggests a senior decision-maker."""
    if not headline:
        return False
    h = headline.lower()
    return any(kw in h for kw in SENIOR_KEYWORDS)


# ---------------------------------------------------------------------------
# Apify helpers  (sync HTTP — runs in a thread via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _run_apify_actor(run_input: dict[str, Any]) -> list[dict]:
    """
    Start an Apify actor run and block until it finishes, then return items.

    Returns an empty list on any error (network, timeout, bad token, etc.)
    """
    if not APIFY_API_TOKEN:
        logger.warning("APIFY_API_TOKEN not set — skipping LinkedIn employee scrape.")
        return []

    headers = {"Authorization": f"Bearer {APIFY_API_TOKEN}"}

    # 1. Start the run
    try:
        resp = httpx.post(
            f"{APIFY_BASE_URL}/acts/{APIFY_ACTOR_ID}/runs",
            headers=headers,
            json=run_input,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Apify: failed to start actor run: %s", exc)
        return []

    run_id: str = resp.json()["data"]["id"]
    dataset_id: str | None = None

    # 2. Poll until SUCCEEDED / FAILED / TIMED-OUT
    deadline = time.monotonic() + APIFY_POLL_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(APIFY_POLL_INTERVAL)
        try:
            status_resp = httpx.get(
                f"{APIFY_BASE_URL}/actor-runs/{run_id}",
                headers=headers,
                timeout=15,
            )
            status_resp.raise_for_status()
        except Exception as exc:
            logger.warning("Apify: status poll error: %s", exc)
            continue

        run_data = status_resp.json()["data"]
        status = run_data.get("status", "")
        if status == "SUCCEEDED":
            dataset_id = run_data["defaultDatasetId"]
            break
        if status in ("FAILED", "TIMED-OUT", "ABORTED"):
            logger.warning("Apify actor run %s ended with status %s.", run_id, status)
            return []

    if not dataset_id:
        logger.warning("Apify: actor run %s did not finish within %ds.", run_id, APIFY_POLL_TIMEOUT)
        return []

    # 3. Fetch dataset items
    try:
        items_resp = httpx.get(
            f"{APIFY_BASE_URL}/datasets/{dataset_id}/items",
            headers=headers,
            params={"format": "json", "clean": "true"},
            timeout=30,
        )
        items_resp.raise_for_status()
        return items_resp.json()
    except Exception as exc:
        logger.error("Apify: failed to fetch dataset items: %s", exc)
        return []


def _scrape_employees(company_linkedin_url: str) -> list[dict]:
    """
    Call the Apify actor and return a deduplicated list of employee dicts.

    Each dict has: name, headline, linkedinUrl, location
    """
    run_input = {
        "companyUrls": [company_linkedin_url],
        "maxItems": MAX_ITEMS,
    }
    raw_items = _run_apify_actor(run_input)

    seen_urls: set[str] = set()
    employees: list[dict] = []
    for e in raw_items:
        url = e.get("linkedinUrl") or ""
        if url in seen_urls:
            continue
        seen_urls.add(url)
        employees.append({
            "name":        (
                f"{e.get('firstName', '')} {e.get('lastName', '')}".strip()
                or e.get("name", "")
            ),
            "headline":    e.get("headline") or "",
            "linkedinUrl": url,
            "location":    (
                (e.get("location") or {}).get("linkedinText")
                or e.get("location")
                or ""
            ),
        })
    return employees


def _pick_best_contact(employees: list[dict]) -> dict | None:
    """
    From a list of employees, prefer senior roles.
    Returns the best match or the first result if none are senior.
    """
    senior_matches = [e for e in employees if _is_senior(e.get("headline"))]
    if senior_matches:
        return senior_matches[0]
    return employees[0] if employees else None


# ---------------------------------------------------------------------------
# Public async interface  (matches the signature of all other enrichment sources)
# ---------------------------------------------------------------------------

async def query_linkedin_employees(
    business_name: str,
    company_linkedin_url: str = "",
) -> dict:
    """
    Scrape a company's LinkedIn employees and return the best senior contact.

    Parameters
    ----------
    business_name : str
        Human-readable company name — used only for logging.
    company_linkedin_url : str
        The company's LinkedIn page URL, e.g.
        ``https://www.linkedin.com/company/mondee``.
        If empty / unknown, the function returns {} immediately.

    Returns
    -------
    dict
        A dict with zero or more of these keys:
            ``linkedin_profile``  — URL of the best senior contact found
            ``contact_name``      — full name of that person
            ``contact_headline``  — their LinkedIn headline

        Returns {} if:
          - ``company_linkedin_url`` is not provided
          - The Apify token is missing
          - No employees are found
          - The actor run fails
    """
    if not company_linkedin_url:
        logger.debug(
            "query_linkedin_employees: no company URL for %r — skipping.",
            business_name,
        )
        return {}

    logger.info(
        "query_linkedin_employees: scraping employees for %r (%s).",
        business_name,
        company_linkedin_url,
    )

    # Run the blocking Apify HTTP calls in a thread so we don't block the loop
    import asyncio
    employees = await asyncio.to_thread(_scrape_employees, company_linkedin_url)

    if not employees:
        logger.info(
            "query_linkedin_employees: no employees found for %r.", business_name
        )
        return {}

    logger.info(
        "query_linkedin_employees: found %d employees for %r (%d senior).",
        len(employees),
        business_name,
        sum(1 for e in employees if _is_senior(e.get("headline"))),
    )

    best = _pick_best_contact(employees)
    if not best:
        return {}

    result: dict = {}
    if best.get("linkedinUrl"):
        result["linkedin_profile"] = best["linkedinUrl"]
    if best.get("name"):
        result["contact_name"] = best["name"]
    if best.get("headline"):
        result["contact_headline"] = best["headline"]

    logger.info(
        "query_linkedin_employees: best contact for %r → %r (%s).",
        business_name,
        result.get("contact_name"),
        result.get("contact_headline"),
    )
    return result
