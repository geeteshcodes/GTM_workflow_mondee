"""
enrichment_sources/hunter.py
-----------------------------
Hunter.io enrichment source — Priority 3 in the fallback chain.

Strategy (Two-Pass)
-------------------
Pass 1 — Domain Search:
    Query Hunter's domain-search by company name.
    Filter out generic/catch-all emails (info@, contact@, etc.).
    Pick the best personal email by department + confidence score.

Pass 2 — Email Finder (runs only if Pass 1 yields no personal email):
    If a contact name is available (from CRM or Apollo), use Hunter's
    email-finder endpoint to construct + verify a personal email
    using the domain's known email pattern.

Return schema
-------------
{
    "email_id":    str,           # the selected email address
    "email_type":  "personal"     # verified personal email
                 | "constructed"  # pattern-matched via email-finder
                 | "generic",     # info@/contact@ fallback
    "confidence":  int,           # Hunter confidence score (0–100)
    "domain":      str,           # company domain found by Hunter
    "source":      "hunter_domain_search" | "hunter_email_finder"
}
Returns {} on any error or if nothing usable is found.

Environment variable required: HUNTER_API_KEY
Docs: https://hunter.io/api-documentation
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")

_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"
_EMAIL_FINDER_URL  = "https://api.hunter.io/v2/email-finder"

_MIN_CONFIDENCE = 70  # Below this, Hunter's email is a guess — not usable

# Departments to prioritise for decision-maker contacts
_PREFERRED_DEPARTMENTS = [
    "executive",
    "management",
    "sales",
    "business development",
]

# Email prefixes that indicate a catch-all / generic inbox
_GENERIC_PREFIXES = {
    "info", "contact", "hello", "support", "admin",
    "sales", "enquiries", "enquiry", "booking", "bookings",
    "reservations", "reception", "office", "team", "mail",
    "general", "service", "services", "help", "noreply",
    "no-reply", "donotreply",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_generic(email: str) -> bool:
    """Return True if the email prefix is a catch-all inbox."""
    prefix = email.split("@")[0].lower().strip()
    return prefix in _GENERIC_PREFIXES


def _pick_best_personal(emails: list) -> tuple[str | None, int]:
    """
    Select the best personal (non-generic) email from a domain-search result.

    Priority:
      1. Verified (confidence ≥ 70), non-generic, preferred department
      2. Verified, non-generic, highest confidence
      3. Any non-generic email (unverified)

    Returns (email, confidence) or (None, 0).
    """
    if not emails:
        return None, 0

    verified     = [e for e in emails if e.get("confidence", 0) >= _MIN_CONFIDENCE]
    personal_v   = [e for e in verified if not _is_generic(e.get("value", ""))]
    personal_any = [e for e in emails   if not _is_generic(e.get("value", ""))]

    # Priority 1 — verified personal from a preferred department
    for dept in _PREFERRED_DEPARTMENTS:
        for e in personal_v:
            if dept in (e.get("department") or "").lower():
                return e["value"], e.get("confidence", 0)

    # Priority 2 — any verified personal, highest confidence
    if personal_v:
        best = max(personal_v, key=lambda e: e.get("confidence", 0))
        return best["value"], best.get("confidence", 0)

    # Priority 3 — non-generic but unverified
    if personal_any:
        best = max(personal_any, key=lambda e: e.get("confidence", 0))
        return best["value"], best.get("confidence", 0)

    return None, 0


def _pick_generic_fallback(emails: list) -> tuple[str | None, int]:
    """
    Return the best generic email as a last resort.
    Only called when no personal email exists at all.
    """
    generics = [e for e in emails if _is_generic(e.get("value", ""))]
    if generics:
        best = max(generics, key=lambda e: e.get("confidence", 0))
        return best["value"], best.get("confidence", 0)
    return None, 0


# ── Main Query ─────────────────────────────────────────────────────────────────

async def query_hunter(
    business_name: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> dict:
    """
    Query Hunter.io for the best contact email for a given business.

    Parameters
    ----------
    business_name : str
        The company name to look up.
    first_name : str, optional
        Contact's first name — used for Pass 2 (Email Finder).
        Provide this from CRM or Apollo people search for best results.
    last_name : str, optional
        Contact's last name — used for Pass 2 (Email Finder).

    Returns
    -------
    dict — see module docstring for schema. Returns {} on failure.
    """
    if not HUNTER_API_KEY:
        logger.warning("HUNTER_API_KEY not set — skipping Hunter for %r.", business_name)
        return {}

    if not business_name:
        return {}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:

            # ── Pass 1: Domain Search ──────────────────────────────────────
            resp = await client.get(
                _DOMAIN_SEARCH_URL,
                params={
                    "company":  business_name,
                    "api_key":  HUNTER_API_KEY,
                    "limit":    10,
                    "type":     "personal",   # exclude generic emails from index
                },
            )
            resp.raise_for_status()
            data = resp.json()

            errors = data.get("errors")
            if errors:
                logger.warning("Hunter domain-search errors for %r: %s", business_name, errors)
                return {}

            domain_data = data.get("data", {})
            domain      = domain_data.get("domain")
            emails      = domain_data.get("emails", [])

            logger.info(
                "Hunter Pass 1: domain=%r, %d emails for %r.",
                domain, len(emails), business_name,
            )

            personal_email, confidence = _pick_best_personal(emails)

            if personal_email:
                logger.info(
                    "Hunter Pass 1 success: %r (confidence=%d) for %r.",
                    personal_email, confidence, business_name,
                )
                return {
                    "email_id":   personal_email,
                    "email_type": "personal",
                    "confidence": confidence,
                    "domain":     domain or "",
                    "source":     "hunter_domain_search",
                }

            logger.info(
                "Hunter Pass 1: no personal email found for %r — trying Email Finder.",
                business_name,
            )

            # ── Pass 2: Email Finder (requires name + domain) ──────────────
            if domain and first_name and last_name:
                finder_resp = await client.get(
                    _EMAIL_FINDER_URL,
                    params={
                        "domain":      domain,
                        "first_name":  first_name,
                        "last_name":   last_name,
                        "api_key":     HUNTER_API_KEY,
                    },
                )
                finder_resp.raise_for_status()
                finder_data = finder_resp.json().get("data", {})

                constructed = finder_data.get("email")
                score       = finder_data.get("score", 0)

                logger.info(
                    "Hunter Pass 2: email=%r score=%d for %r.",
                    constructed, score, business_name,
                )

                if constructed and score >= _MIN_CONFIDENCE:
                    logger.info(
                        "Hunter Pass 2 success: %r (score=%d) for %r.",
                        constructed, score, business_name,
                    )
                    return {
                        "email_id":   constructed,
                        "email_type": "constructed",
                        "confidence": score,
                        "domain":     domain or "",
                        "source":     "hunter_email_finder",
                    }

                logger.info(
                    "Hunter Pass 2: score %d below threshold for %r — skipping.",
                    score, business_name,
                )
            else:
                logger.info(
                    "Hunter Pass 2 skipped for %r — missing domain=%r or name (%r %r).",
                    business_name, domain, first_name, last_name,
                )

            # ── Last Resort: Generic Fallback ──────────────────────────────
            # Re-fetch without type=personal filter to capture info@ emails
            fallback_resp = await client.get(
                _DOMAIN_SEARCH_URL,
                params={
                    "company": business_name,
                    "api_key": HUNTER_API_KEY,
                    "limit":   5,
                    # No type filter — allows generic emails through
                },
            )
            fallback_resp.raise_for_status()
            fallback_emails = fallback_resp.json().get("data", {}).get("emails", [])

            generic_email, generic_confidence = _pick_generic_fallback(fallback_emails)

            if generic_email:
                logger.info(
                    "Hunter generic fallback: %r for %r — flagged for manual/WhatsApp outreach.",
                    generic_email, business_name,
                )
                return {
                    "email_id":   generic_email,
                    "email_type": "generic",
                    "confidence": generic_confidence,
                    "domain":     domain or "",
                    "source":     "hunter_domain_search",
                }

            logger.info("Hunter: no email found at all for %r.", business_name)
            return {}

    except httpx.HTTPStatusError as exc:
        logger.error("Hunter HTTP %d for %r: %s", exc.response.status_code, business_name, exc)
        return {}
    except Exception as exc:
        logger.error("Hunter unexpected error for %r: %s", business_name, exc)
        return {}