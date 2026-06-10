"""
nodes/enrichment_node.py
------------------------
Enrichment Node — Stage 2 of the pipeline.

Purpose
-------
For each partner discovered in Stage 1, attempt to fill in any missing contact
fields (phone_number, email_id, linkedin_profile) using a strict prioritised
fallback chain:

    Priority 1   — Partners DB data (already in discovered_partners dict)
                   If the field is non-null and non-empty, use it directly.
    Priority 2   — Internal Database API  (enrichment_sources/database_query.py)
    Priority 2.3 — LinkedIn URL Finder    (enrichment_sources/linkedin_url_finder.py)
                   Tavily web search: ``"<name>" <category> <region> site:linkedin.com/company``
                   Resolves the company's LinkedIn page URL so Priority 2.5 can work
                   even when the DB has no ``company_linkedin_url`` column value.
    Priority 2.5 — LinkedIn Employee Scrape (enrichment_sources/linkedin_company_employees.py)
                   Scrapes the company LinkedIn page, filters for senior staff
                   (VP, Director, C-suite, etc.) and returns a real person's
                   profile URL — far better than a support@ inbox.
    Priority 3   — Hunter.io              (enrichment_sources/hunter.py)
    Priority 4   — Apollo.io              (enrichment_sources/apollo.py)
    Priority 5   — LinkedIn Sales Nav     (enrichment_sources/linkedin_sales_nav.py)

Rules
-----
- Per-field resolution: each contact field is resolved independently.
  e.g. email may come from Hunter while phone comes from Apollo.
- Stop early per field: as soon as a non-null, non-empty value is found,
  do not call lower-priority sources for that field.
- Failure tolerance: if all sources return null for a field, set it to None.
  Never raise an exception — return partial data and continue.
- Async + concurrent: all external source calls for a single partner are run
  concurrently via asyncio.gather for speed.

Extensibility
-------------
To add a new enrichment source:
  1. Create enrichment_sources/<new_source>.py with an async query function.
  2. Add it to enrichment_sources/__init__.py.
  3. Append it to the FALLBACK_CHAIN list below. That's it.
"""

import asyncio
import logging
import os
import time
from typing import Any

from enrichment_sources.apollo import query_apollo
from enrichment_sources.database_query import query_database
from enrichment_sources.hunter import query_hunter
from enrichment_sources.linkedin_company_employees import query_linkedin_employees
from enrichment_sources.linkedin_sales_nav import query_linkedin
from enrichment_sources.linkedin_url_finder import find_company_linkedin_url
from state import GraphState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Concurrency cap — limits how many partners are enriched simultaneously.
# Set via env var ENRICH_CONCURRENCY (default 10).
# Raising this speeds things up but uses more API quota & DB connections.
# ---------------------------------------------------------------------------
_ENRICH_CONCURRENCY: int = int(os.getenv("ENRICH_CONCURRENCY", "10"))
_enrich_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Return (or lazily create) the module-level enrichment semaphore."""
    global _enrich_semaphore
    if _enrich_semaphore is None:
        _enrich_semaphore = asyncio.Semaphore(_ENRICH_CONCURRENCY)
        logger.info(
            "Enrichment semaphore initialised: max %d concurrent partners.",
            _ENRICH_CONCURRENCY,
        )
    return _enrich_semaphore

# ---------------------------------------------------------------------------
# Fields we attempt to enrich.  Order matters for logging clarity only;
# the fallback chain logic below is field-agnostic.
# ---------------------------------------------------------------------------
ENRICHABLE_FIELDS = ("phone_number", "email_id", "linkedin_profile")

# Extra fields written by the LinkedIn employee scraper (not standard enrichment
# targets, but stored on the partner record for outreach personalisation).
_LINKEDIN_BONUS_FIELDS = ("contact_name", "contact_headline")


def _is_present(value: Any) -> bool:
    """Return True if `value` is a non-null, non-whitespace-only string."""
    if value is None:
        return False
    return str(value).strip() != ""


async def _enrich_one_partner(partner: dict, run_id: str = "") -> dict:
    """
    Run the fallback chain for a single partner and return the enriched dict.
    Acquires the module-level semaphore so at most ENRICH_CONCURRENCY partners
    are processed simultaneously — essential for large partner lists.

    Parameters
    ----------
    partner : dict
        A single record from discovered_partners.
    run_id : str
        Optional pipeline run ID for log correlation.

    Returns
    -------
    dict
        Same dict with phone_number / email_id / linkedin_profile filled in
        where possible.  Unresolved fields are set to None.
    """
    prefix = f"[{run_id}] " if run_id else ""
    enriched = dict(partner)

    business_name: str = partner.get("partner_name", "") or ""
    detail: str = " ".join(
        filter(None, [partner.get("category", ""), partner.get("subcategories", "")])
    )

    # ------------------------------------------------------------------
    # Priority 1: check what's already in the DB record
    # ------------------------------------------------------------------
    fields_needed = [f for f in ENRICHABLE_FIELDS if not _is_present(partner.get(f))]

    if not fields_needed:
        logger.info("%sPartner %r: all fields already present — skipping enrichment.", prefix, business_name)
        return enriched

    logger.info(
        "%sPartner %r: needs enrichment for fields %s.",
        prefix, business_name, fields_needed,
    )

    async with _get_semaphore():
        await _enrich_one_partner_inner(enriched, partner, business_name, detail, fields_needed, prefix)
    return enriched


async def _enrich_one_partner_inner(
    enriched: dict,
    partner: dict,
    business_name: str,
    detail: str,
    fields_needed: list,
    prefix: str,
) -> None:
    """Inner enrichment logic — runs inside the semaphore."""
    t0 = time.monotonic()

    # ------------------------------------------------------------------
    # Priority 2–5: resolve company_linkedin_url first (sequential pre-step),
    # then fire all remaining sources concurrently.
    # ------------------------------------------------------------------

    # Step A — Resolve company LinkedIn page URL (Priority 2.3)
    company_linkedin_url: str = partner.get("company_linkedin_url") or ""

    if not company_linkedin_url:
        try:
            logger.info("%s  → [%s] Searching LinkedIn URL via Tavily…", prefix, business_name)
            url_result = await find_company_linkedin_url(
                partner_name=business_name,
                category=partner.get("category", "") or "",
                region=partner.get("region", "") or "",
                website=partner.get("website", "") or "",
            )
            company_linkedin_url = url_result.get("company_linkedin_url", "")
            if company_linkedin_url:
                enriched["company_linkedin_url"] = company_linkedin_url
                logger.info(
                    "%s  → [%s] LinkedIn URL found: %s",
                    prefix, business_name, company_linkedin_url,
                )
            else:
                logger.info("%s  → [%s] LinkedIn URL not found via Tavily.", prefix, business_name)
        except Exception as exc:
            logger.warning(
                "%s  → [%s] LinkedIn URL finder failed: %s",
                prefix, business_name, exc,
            )

    # Step B — Fire all remaining sources concurrently (Priority 2, 2.5, 3, 4, 5)
    logger.info(
        "%s  → [%s] Querying sources: database, linkedin_employees, hunter, apollo, linkedin_sales_nav…",
        prefix, business_name,
    )
    try:
        (
            db_result,
            linkedin_emp_result,
            hunter_result,
            apollo_result,
            linkedin_result,
        ) = await asyncio.gather(
            query_database(business_name, detail),
            query_linkedin_employees(business_name, company_linkedin_url),
            query_hunter(business_name),
            query_apollo(business_name),
            query_linkedin(business_name),
            return_exceptions=True,  # never let one failure abort the rest
        )
    except Exception as exc:
        logger.error("Unexpected error during gather for %r: %s", business_name, exc)
        db_result = linkedin_emp_result = hunter_result = apollo_result = linkedin_result = {}

    # Convert any exceptions returned by gather into empty dicts
    source_results = []
    for name, result in [
        ("database",         db_result),
        ("linkedin_emp",     linkedin_emp_result),
        ("hunter",           hunter_result),
        ("apollo",           apollo_result),
        ("linkedin",         linkedin_result),
    ]:
        if isinstance(result, Exception):
            logger.warning(
                "Partner %r: source %r raised %s — treating as empty.",
                business_name,
                name,
                result,
            )
            source_results.append({})
        else:
            source_results.append(result or {})

    db_res, linkedin_emp_res, hunter_res, apollo_res, linkedin_res = source_results

    # ------------------------------------------------------------------
    # Bonus: store contact_name / contact_headline from LinkedIn scrape
    # These are metadata fields, not standard ENRICHABLE_FIELDS, so we
    # write them directly without going through the fallback loop.
    # ------------------------------------------------------------------
    for bonus_field in _LINKEDIN_BONUS_FIELDS:
        if _is_present(linkedin_emp_res.get(bonus_field)) and not _is_present(
            enriched.get(bonus_field)
        ):
            enriched[bonus_field] = linkedin_emp_res[bonus_field]

    # Walk fallback chain per field
    resolved_fields = {}
    for field in fields_needed:
        resolved_value = None
        for source_name, source_data in [
            ("database",     db_res),
            ("linkedin_emp", linkedin_emp_res),  # Priority 2.5 — real named contact
            ("hunter",       hunter_res),
            ("apollo",       apollo_res),
            ("linkedin",     linkedin_res),
        ]:
            candidate = source_data.get(field)
            if _is_present(candidate):
                enriched[field] = candidate
                resolved_value = candidate
                resolved_fields[field] = source_name
                break

        if resolved_value is None:
            enriched[field] = None  # explicit None — all sources exhausted

    elapsed = time.monotonic() - t0
    if resolved_fields:
        logger.info(
            "%s  ✓ [%s] Enriched in %.1fs — %s",
            prefix, business_name, elapsed,
            ", ".join(f"{k} via {v}" for k, v in resolved_fields.items()),
        )
    else:
        logger.info(
            "%s  ✗ [%s] No new data found in %.1fs (all sources empty).",
            prefix, business_name, elapsed,
        )


async def enrichment_node(state: GraphState) -> dict:
    """
    LangGraph node: enrich all discovered partners concurrently.
    At most ENRICH_CONCURRENCY (default 10) partners are processed
    simultaneously — controlled by the module-level semaphore.

    Parameters
    ----------
    state : GraphState
        Must contain `discovered_partners` (list[dict]).

    Returns
    -------
    dict
        Partial state update: {"enriched_partners": list[dict]}
    """
    discovered = state.get("discovered_partners", [])
    run_id: str = state.get("run_id", "")

    if not discovered:
        logger.warning("[%s] Enrichment node: no discovered partners to enrich.", run_id)
        return {"enriched_partners": []}

    total = len(discovered)
    logger.info(
        "[%s] Enrichment node: starting %d partners (concurrency cap: %d).",
        run_id, total, _ENRICH_CONCURRENCY,
    )
    t_start = time.monotonic()

    # Schedule all partners; semaphore inside _enrich_one_partner limits
    # actual concurrency to _ENRICH_CONCURRENCY at any moment.
    enriched_partners = await asyncio.gather(
        *[_enrich_one_partner(partner, run_id=run_id) for partner in discovered],
        return_exceptions=False,
    )

    elapsed = time.monotonic() - t_start
    filled = sum(
        1 for p in enriched_partners
        if any(p.get(f) for f in ("phone_number", "email_id", "linkedin_profile"))
    )
    logger.info(
        "[%s] Enrichment node: finished %d partners in %.1fs — %d/%d had contact data filled.",
        run_id, total, elapsed, filled, total,
    )

    return {"enriched_partners": list(enriched_partners)}
