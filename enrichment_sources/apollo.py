"""
enrichment_sources/apollo.py
-----------------------------
Apollo.io enrichment source — Priority 4 in the fallback chain.

Key constraints:
- Max 5 contacts per company (APOLLO_MAX_CONTACTS_PER_COMPANY env var)
- Title filter: only the 14 decision-maker roles defined by GTM team
- Credit logging: every API call logged to apollo_usage table in Supabase
- Rate limiter: 45 req/min (Basic plan: 50/min hard limit)
- Retry with exponential backoff on 429 / 5xx
- Phone reveal + email reveal via /people/match
- Returns contact_name + contact_title for Hunter Pass 2 cross-feed
- Returns org_domain for website scraper fallback

Credit cost per operation (Apollo Basic):
  org_search    → 1 credit
  people_search → 1 credit per page
  email_reveal  → 1 credit per reveal
  phone_reveal  → 1 credit per reveal

Environment variable required: APOLLO_API_KEY
Optional:
  APOLLO_RPM                    — requests/min cap (default 45)
  APOLLO_MAX_CONTACTS_PER_COMPANY — max people to fetch per org (default 5)
  APOLLO_MONTHLY_CREDIT_CAP     — hard stop threshold (default 2520)
  APOLLO_CREDIT_WARNING_PCT     — warn at this % of cap (default 80)
"""

import asyncio
import logging
import os
import time
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")

_ORG_SEARCH_URL    = "https://api.apollo.io/api/v1/organizations/search"
_PEOPLE_SEARCH_URL = "https://api.apollo.io/api/v1/people/search"
_PEOPLE_MATCH_URL  = "https://api.apollo.io/api/v1/people/match"

# ── Credit config ──────────────────────────────────────────────────────────
_MONTHLY_CAP:     int = int(os.getenv("APOLLO_MONTHLY_CREDIT_CAP",     "2520"))
_WARNING_PCT:     int = int(os.getenv("APOLLO_CREDIT_WARNING_PCT",     "80"))
_MAX_PER_COMPANY: int = int(os.getenv("APOLLO_MAX_CONTACTS_PER_COMPANY", "5"))

# ── Title filter — GTM-approved decision-maker roles only ──────────────────
# Apollo people search will be filtered to ONLY these roles.
# No support staff, no junior roles, no generic contacts.
_TARGET_TITLES = [
    "founder", "co-founder",
    "owner",
    "ceo", "chief executive",
    "managing director", "md",
    "general manager", "gm",
    "managing partner",
    "business development manager", "business development head",
    "head of business development",
    "partnerships manager", "partnerships head", "head of partnerships",
    "partner manager",
    "sales manager", "sales head", "head of sales",
    "commercial manager", "head of commercial", "commercial head",
    "contracting manager", "contracting executive",
    "channel manager",
    "distribution manager",
    "reservations manager",
    "product manager",
    "marketing head", "head of marketing",
]

# For Apollo's title_fuzzy_match filter — top-level keywords only
_APOLLO_TITLE_KEYWORDS = [
    "founder", "owner", "ceo", "managing director", "general manager",
    "managing partner", "business development", "partnerships",
    "sales manager", "commercial", "contracting", "channel manager",
    "distribution", "reservations", "product manager", "marketing head",
]

# Seniority score for ranking — higher = more senior
_TITLE_SCORES: dict[str, int] = {
    "founder": 100, "co-founder": 100, "owner": 95,
    "ceo": 90, "chief executive": 90,
    "managing director": 88, "md": 88,
    "general manager": 85, "gm": 85,
    "managing partner": 82,
    "head of business development": 75, "business development head": 75,
    "business development manager": 70,
    "head of partnerships": 75, "partnerships head": 75,
    "partnerships manager": 70, "partner manager": 68,
    "head of sales": 72, "sales head": 72, "sales manager": 68,
    "head of commercial": 72, "commercial head": 72, "commercial manager": 68,
    "contracting manager": 65, "contracting executive": 62,
    "channel manager": 60,
    "distribution manager": 60,
    "reservations manager": 58,
    "product manager": 55,
    "head of marketing": 65, "marketing head": 65,
}


def _score_title(title: str) -> int:
    if not title:
        return 0
    t = title.lower().strip()
    # Exact match first
    if t in _TITLE_SCORES:
        return _TITLE_SCORES[t]
    # Partial match
    for key, score in _TITLE_SCORES.items():
        if key in t:
            return score
    return 0


def _is_target_title(title: str) -> bool:
    """Return True only if this title matches our GTM-approved list."""
    if not title:
        return False
    t = title.lower()
    return any(kw in t for kw in _APOLLO_TITLE_KEYWORDS)


# ── Rate limiter ───────────────────────────────────────────────────────────
_APOLLO_RPM: int    = int(os.getenv("APOLLO_RPM", "45"))
_apollo_lock        = asyncio.Lock()
_apollo_calls: list = []


async def _rate_gate() -> None:
    async with _apollo_lock:
        now = time.monotonic()
        while _apollo_calls and now - _apollo_calls[0] > 60:
            _apollo_calls.pop(0)
        if len(_apollo_calls) >= _APOLLO_RPM:
            sleep_for = 60 - (now - _apollo_calls[0]) + 0.1
            logger.info("Apollo rate gate: sleeping %.1fs", sleep_for)
            await asyncio.sleep(sleep_for)
        _apollo_calls.append(time.monotonic())


# ── Credit tracker ─────────────────────────────────────────────────────────

# In-memory counter for this server session
# Supabase logging is async and non-blocking
_session_credits: dict = {
    "org_search":    0,
    "people_search": 0,
    "email_reveal":  0,
    "phone_reveal":  0,
    "prospecting":   0,
    "total":         0,
}


async def _log_credit(
    operation: str,
    credits_used: int = 1,
    partner_name: str = "",
    run_id: str = "",
    result_fields: list | None = None,
    success: bool = True,
    error_msg: str = "",
) -> None:
    """
    Log an Apollo credit usage event to Supabase.
    Non-blocking — fires and forgets. Never raises.
    """
    # Update in-memory counter
    _session_credits[operation] = _session_credits.get(operation, 0) + credits_used
    _session_credits["total"]   = _session_credits.get("total", 0) + credits_used

    total = _session_credits["total"]
    warning_threshold = int(_MONTHLY_CAP * _WARNING_PCT / 100)

    if total >= _MONTHLY_CAP:
        logger.error(
            "Apollo CREDIT CAP REACHED: %d/%d credits used this session. "
            "Stopping further API calls.",
            total, _MONTHLY_CAP,
        )
    elif total >= warning_threshold:
        logger.warning(
            "Apollo credit warning: %d/%d credits used (%d%% of monthly cap).",
            total, _MONTHLY_CAP, int(total / _MONTHLY_CAP * 100),
        )

    # Async DB log — fire and forget
    try:
        from db.connection import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO apollo_usage
                    (run_id, partner_name, operation, credits_used,
                     result_fields, success, error_msg)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                run_id or "",
                partner_name or "",
                operation,
                credits_used,
                result_fields or [],
                success,
                error_msg or "",
            )
    except Exception as exc:
        logger.debug("Apollo credit log failed (non-critical): %s", exc)


def _check_credit_cap() -> bool:
    """Return True if we're under the monthly cap and can proceed."""
    return _session_credits.get("total", 0) < _MONTHLY_CAP


# ── Retry helper ───────────────────────────────────────────────────────────

async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    payload: dict,
    retries: int = 3,
) -> dict | None:
    for attempt in range(retries):
        await _rate_gate()
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = 2 ** attempt * 15
                logger.warning("Apollo 429 — backing off %.0fs (attempt %d)", wait, attempt + 1)
                await asyncio.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = 2 ** attempt * 5
                logger.warning("Apollo %d — backing off %.0fs", resp.status_code, wait)
                await asyncio.sleep(wait)
                continue
            logger.warning("Apollo HTTP %d for %s", resp.status_code, url)
            return None
        except Exception as exc:
            logger.error("Apollo request error: %s", exc)
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt * 3)
    return None


# ── Helpers ────────────────────────────────────────────────────────────────

def _is_masked(email: str | None) -> bool:
    if not email:
        return False
    local = email.split("@")[0]
    return "***" in local or local.strip("*") == ""


def _clean_domain(raw: str) -> str:
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = "https://" + raw
    parsed = urlparse(raw)
    return parsed.netloc or parsed.path.split("/")[0]


def _extract_phone(person: dict) -> str | None:
    phones = person.get("phone_numbers") or []
    for phone in phones:
        number = phone.get("sanitized_number") or phone.get("raw_number")
        if number:
            return number
    return None


# ── Main enrichment query ──────────────────────────────────────────────────

async def query_apollo(
    business_name: str,
    run_id: str = "",
) -> dict:
    """
    Query Apollo.io for the best decision-maker contact at a given business.

    Enforces:
    - Max _MAX_PER_COMPANY contacts fetched per org
    - Title filter: only GTM-approved roles
    - Per-operation credit logging to Supabase

    Returns
    -------
    dict with keys:
        email_id         : str | None
        phone_number     : str | None
        linkedin_profile : str | None
        contact_name     : str
        contact_title    : str
        org_domain       : str
        email_revealed   : bool
        all_contacts     : list[dict]  — all found contacts (up to _MAX_PER_COMPANY)
    Returns {} on failure.
    """
    if not APOLLO_API_KEY:
        logger.warning("APOLLO_API_KEY not set — skipping Apollo for %r.", business_name)
        return {}
    if not business_name:
        return {}
    if not _check_credit_cap():
        logger.error("Apollo credit cap reached — skipping %r.", business_name)
        return {}

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:

            # ── Step 1: Organisation search (1 credit) ─────────────────────
            org_data = await _post_with_retry(
                client, _ORG_SEARCH_URL, headers,
                {"q_organization_name": business_name, "page": 1, "per_page": 1},
            )

            await _log_credit(
                "org_search", 1, business_name, run_id,
                success=bool(org_data),
                error_msg="" if org_data else "no response",
            )

            org_id     = None
            org_domain = None

            if org_data:
                orgs = org_data.get("organizations") or []
                if orgs:
                    org        = orgs[0]
                    org_id     = org.get("id")
                    raw_domain = org.get("primary_domain") or org.get("website_url") or ""
                    org_domain = _clean_domain(raw_domain)
                    logger.info(
                        "Apollo: org found — id=%s domain=%r for %r.",
                        org_id, org_domain, business_name,
                    )

            if not org_id and not org_domain:
                logger.info("Apollo: no org found for %r.", business_name)
                return {"org_domain": org_domain} if org_domain else {}

            # ── Step 2: People search — title-filtered, capped ────────────
            # (1 credit per page)
            people_payload: dict = {
                "page":     1,
                "per_page": _MAX_PER_COMPANY,  # never fetch more than cap
                # Title fuzzy filter — Apollo applies this server-side
                "person_titles": _APOLLO_TITLE_KEYWORDS,
            }
            if org_id:
                people_payload["organization_ids"] = [org_id]
            else:
                people_payload["q_organization_domains"] = [org_domain]

            people_data = await _post_with_retry(
                client, _PEOPLE_SEARCH_URL, headers, people_payload,
            )

            await _log_credit(
                "people_search", 1, business_name, run_id,
                success=bool(people_data),
                error_msg="" if people_data else "no response",
            )

            people = (people_data or {}).get("people") or []

            # Client-side title filter as safety net
            people = [p for p in people if _is_target_title(p.get("title") or "")]

            # Enforce company cap
            people = people[:_MAX_PER_COMPANY]

            if not people:
                logger.info(
                    "Apollo: no target-title contacts found for %r (cap=%d).",
                    business_name, _MAX_PER_COMPANY,
                )
                return {"org_domain": org_domain} if org_domain else {}

            logger.info(
                "Apollo: %d target-title contacts found for %r (cap=%d).",
                len(people), business_name, _MAX_PER_COMPANY,
            )

            # ── Step 3: Rank by title seniority ───────────────────────────
            people.sort(key=lambda p: _score_title(p.get("title") or ""), reverse=True)
            best  = people[0]
            name  = best.get("name") or ""
            title = best.get("title") or ""
            email = best.get("email")

            logger.info(
                "Apollo: best candidate — name=%r title=%r masked=%s for %r.",
                name, title, _is_masked(email), business_name,
            )

            # ── Step 4: Email reveal (1 credit) ───────────────────────────
            email_revealed = False

            if _is_masked(email) or not email:
                linkedin_url = best.get("linkedin_url")
                if linkedin_url and _check_credit_cap():
                    match_data = await _post_with_retry(
                        client, _PEOPLE_MATCH_URL, headers,
                        {
                            "linkedin_url":           linkedin_url,
                            "reveal_personal_emails": False,
                            "reveal_phone_number":    True,
                        },
                    )
                    revealed_fields = []
                    if match_data:
                        revealed       = match_data.get("person") or {}
                        rev_email      = revealed.get("email")
                        if rev_email and not _is_masked(rev_email) and "@" in rev_email:
                            email          = rev_email
                            email_revealed = True
                            revealed_fields.append("email")
                        rev_phones = revealed.get("phone_numbers") or []
                        if rev_phones:
                            best["phone_numbers"] = rev_phones
                            revealed_fields.append("phone")

                    await _log_credit(
                        "email_reveal", 1, business_name, run_id,
                        result_fields=revealed_fields,
                        success=bool(revealed_fields),
                        error_msg="" if revealed_fields else "reveal returned nothing",
                    )
                else:
                    email = None

            # ── Step 5: Phone reveal if still missing ─────────────────────
            phone = _extract_phone(best)
            if not phone and org_domain and name and _check_credit_cap():
                parts = name.strip().split()
                if len(parts) >= 2:
                    match_data = await _post_with_retry(
                        client, _PEOPLE_MATCH_URL, headers,
                        {
                            "first_name":          parts[0],
                            "last_name":           parts[-1],
                            "organization_name":   business_name,
                            "domain":              org_domain,
                            "reveal_phone_number": True,
                        },
                    )
                    if match_data:
                        rev_person = match_data.get("person") or {}
                        phone      = _extract_phone(rev_person) or phone

                    await _log_credit(
                        "phone_reveal", 1, business_name, run_id,
                        result_fields=["phone"] if phone else [],
                        success=bool(phone),
                    )

            # ── Step 6: Build result ───────────────────────────────────────
            result: dict = {
                "contact_name":   name,
                "contact_title":  title,
                "email_revealed": email_revealed,
                "org_domain":     org_domain or "",
                # All contacts found (for CRM / future use)
                "all_contacts": [
                    {
                        "name":     p.get("name", ""),
                        "title":    p.get("title", ""),
                        "linkedin": p.get("linkedin_url", ""),
                        "email":    p.get("email") if not _is_masked(p.get("email")) else None,
                    }
                    for p in people
                ],
            }

            if email and "@" in email and not _is_masked(email):
                result["email_id"] = email
            if phone:
                result["phone_number"] = phone
            if best.get("linkedin_url"):
                result["linkedin_profile"] = best["linkedin_url"]

            fields_found = [k for k in ("email_id", "phone_number", "linkedin_profile") if result.get(k)]
            logger.info(
                "Apollo: result for %r — fields=%s contacts=%d revealed=%s.",
                business_name, fields_found, len(people), email_revealed,
            )
            return result

    except Exception as exc:
        logger.error("Apollo error for %r: %s", business_name, exc)
        return {}


# ── Apollo Prospecting (Discovery mode) ────────────────────────────────────

async def prospect_apollo(
    category: str,
    region: str = "UAE",
    max_companies: int = 50,
    run_id: str = "",
) -> list[dict]:
    """
    Use Apollo's prospecting API to discover NEW companies not in our DB.

    Maps the pipeline's category/subcategory to Apollo industry + title filters,
    returns a list of partner-shaped dicts ready for enrichment.

    Credit cost: 1 per page of results (10 companies/page)

    Parameters
    ----------
    category : str
        Pipeline input_category e.g. "Adventure & Extreme Sports"
    region : str
        "UAE" by default
    max_companies : int
        Hard cap on companies to return (default 50)

    Returns
    -------
    list[dict] — partner-shaped dicts with partner_name, website, org_domain,
                 contact_name, contact_title, email_id, phone_number,
                 linkedin_profile, sheet_source="apollo_prospecting"
    """
    if not APOLLO_API_KEY:
        logger.warning("APOLLO_API_KEY not set — skipping Apollo prospecting.")
        return []
    if not _check_credit_cap():
        logger.error("Apollo credit cap reached — skipping prospecting.")
        return []

    # Map pipeline category to Apollo industry keywords
    _CATEGORY_TO_INDUSTRIES = {
        "adventure":    ["recreational facilities", "sports", "tourism", "outdoor recreation"],
        "wellness":     ["health wellness fitness", "spa", "yoga", "alternative medicine"],
        "food":         ["restaurants", "food beverages", "hospitality"],
        "culture":      ["museums", "arts crafts", "entertainment", "tourism"],
        "travel":       ["leisure travel tourism", "hospitality", "travel arrangements"],
        "experience":   ["entertainment", "events services", "tourism", "recreation"],
    }

    cat_lower = category.lower()
    industries = []
    for key, vals in _CATEGORY_TO_INDUSTRIES.items():
        if key in cat_lower:
            industries.extend(vals)
    if not industries:
        industries = ["leisure travel tourism", "entertainment", "hospitality"]

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY,
    }

    partners: list[dict] = []
    page = 1
    per_page = 10

    logger.info(
        "Apollo prospecting: category=%r industries=%s max=%d",
        category, industries, max_companies,
    )

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            while len(partners) < max_companies:
                if not _check_credit_cap():
                    logger.warning("Apollo credit cap reached during prospecting — stopping.")
                    break

                payload = {
                    "page":                  page,
                    "per_page":              per_page,
                    "organization_locations": [region],
                    "organization_industry_tag_ids": industries,
                    "person_titles":         _APOLLO_TITLE_KEYWORDS,
                    "organization_num_employees_ranges": ["1,200"],  # SME operators
                }

                data = await _post_with_retry(client, _PEOPLE_SEARCH_URL, headers, payload)

                await _log_credit(
                    "prospecting", 1, f"category:{category}", run_id,
                    success=bool(data),
                )

                if not data:
                    break

                people = data.get("people") or []
                if not people:
                    break

                for person in people:
                    if len(partners) >= max_companies:
                        break

                    org  = (person.get("organization") or {})
                    name = org.get("name") or person.get("organization_name") or ""
                    if not name:
                        continue

                    # Skip if title doesn't match our target list
                    if not _is_target_title(person.get("title") or ""):
                        continue

                    email = person.get("email")
                    if _is_masked(email):
                        email = None

                    partners.append({
                        "partner_name":     name,
                        "category":         category,
                        "subcategories":    category,
                        "website":          org.get("website_url") or "",
                        "org_domain":       _clean_domain(org.get("website_url") or ""),
                        "region":           "Local",
                        "status":           "Yet to Start",
                        "digitisation":     "Semi-digitised",
                        "sheet_source":     "apollo_prospecting",
                        "contact_name":     person.get("name") or "",
                        "contact_title":    person.get("title") or "",
                        "email_id":         email or "",
                        "phone_number":     _extract_phone(person) or "",
                        "linkedin_profile": person.get("linkedin_url") or "",
                    })

                total_pages = data.get("pagination", {}).get("total_pages", 1)
                logger.info(
                    "Apollo prospecting page %d/%d: %d new partners (total=%d)",
                    page, total_pages, len(people), len(partners),
                )

                if page >= total_pages:
                    break
                page += 1

    except Exception as exc:
        logger.error("Apollo prospecting error for category %r: %s", category, exc)

    logger.info(
        "Apollo prospecting: found %d partners for category=%r", len(partners), category,
    )
    return partners


# ── Session credit summary ─────────────────────────────────────────────────

def get_session_credit_summary() -> dict:
    """Return in-memory credit usage for this server session."""
    return {
        **_session_credits,
        "monthly_cap":    _MONTHLY_CAP,
        "remaining_est":  max(0, _MONTHLY_CAP - _session_credits.get("total", 0)),
        "warning_pct":    _WARNING_PCT,
    }