"""
nodes/discovery_node.py
-----------------------
Discovery Node — Stage 1 of the pipeline.

Strategy
--------
1. DB first — query partners table for matching subcategory + status
2. Apollo prospecting gap-fill — if DB returns < APOLLO_PROSPECTING_MIN
   results, Apollo discovers additional UAE operators for that category
   and appends them (deduped by name)

Apollo-discovered partners are:
- Tagged sheet_source = "apollo_prospecting"
- Upserted into partners table for future runs
- Passed directly to enrichment with whatever Apollo already found
"""

import logging
import os

from db.connection import get_pool
from enrichment_sources.apollo import prospect_apollo
from state import GraphState

logger = logging.getLogger(__name__)

STATUSES_TO_ENRICH = ["Yet to Start", "Partner Outreach"]

# Minimum DB results before Apollo prospecting kicks in
_APOLLO_MIN_THRESHOLD: int = int(os.getenv("APOLLO_PROSPECTING_MIN", "10"))
# Max Apollo partners to add per run
_APOLLO_MAX_PROSPECT:  int = int(os.getenv("APOLLO_PROSPECTING_MAX", "30"))

_DISCOVERY_QUERY = """
SELECT
    id,
    partner_name,
    digitisation,
    category,
    subcategories,
    subcategory_tags,
    website,
    product_count,
    status,
    integrated,
    region,
    phone_number,
    email_id,
    linkedin_profile,
    sheet_source
FROM partners
WHERE status = ANY($1)
  AND (
      $2 = ANY(subcategory_tags)          -- exact tag match (preferred)
      OR subcategories ILIKE $3           -- fallback for untagged rows
  )
ORDER BY
    ($2 = ANY(subcategory_tags)) DESC,   -- exact matches first
    sheet_source,
    partner_name;
"""

_UPSERT_APOLLO_PARTNER = """
INSERT INTO partners
    (partner_name, category, subcategories, website, status,
     digitisation, region, phone_number, email_id, linkedin_profile, sheet_source)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
ON CONFLICT (partner_name, sheet_source) DO UPDATE SET
    category         = EXCLUDED.category,
    subcategories    = EXCLUDED.subcategories,
    website          = COALESCE(EXCLUDED.website, partners.website),
    phone_number     = COALESCE(NULLIF(EXCLUDED.phone_number, ''), partners.phone_number),
    email_id         = COALESCE(NULLIF(EXCLUDED.email_id,    ''), partners.email_id),
    linkedin_profile = COALESCE(NULLIF(EXCLUDED.linkedin_profile,''), partners.linkedin_profile)
RETURNING id, partner_name;
"""


async def discovery_node(state: GraphState) -> dict:
    """
    LangGraph node: discover partners for the given category.

    Flow:
      1. Query DB for matching partners
      2. If results < threshold → run Apollo prospecting for the category
      3. Upsert Apollo-found partners to DB
      4. Merge and return deduplicated list

    Returns
    -------
    dict: {"discovered_partners": list[dict]}
    """
    input_category = state["input_category"].strip()
    run_id = state.get("run_id", "")
    prefix = f"[{run_id}] " if run_id else ""
    like_pattern = f"%{input_category}%"

    logger.info(
        "%sDiscovery: searching DB for subcategory=%r, statuses=%r",
        prefix, input_category, STATUSES_TO_ENRICH,
    )

    pool = await get_pool()

    # ── Step 1: DB query ───────────────────────────────────────────────────
    async with pool.acquire() as conn:
        rows = await conn.fetch(_DISCOVERY_QUERY, STATUSES_TO_ENRICH, input_category, like_pattern)

    db_partners = [dict(row) for row in rows]
    logger.info("%sDiscovery: DB returned %d partners.", prefix, len(db_partners))

    # ── Step 2: Apollo prospecting gap-fill ───────────────────────────────
    apollo_partners: list[dict] = []

    if len(db_partners) < _APOLLO_MIN_THRESHOLD:
        logger.info(
            "%sDiscovery: DB results (%d) below threshold (%d) — running Apollo prospecting for %r.",
            prefix, len(db_partners), _APOLLO_MIN_THRESHOLD, input_category,
        )
        try:
            apollo_partners = await prospect_apollo(
                category=input_category,
                region="UAE",
                max_companies=_APOLLO_MAX_PROSPECT,
                run_id=run_id,
            )
            logger.info(
                "%sDiscovery: Apollo prospecting found %d partners.",
                prefix, len(apollo_partners),
            )
        except Exception as exc:
            logger.warning("%sDiscovery: Apollo prospecting failed: %s", prefix, exc)
            apollo_partners = []

        # ── Step 3: Upsert Apollo partners to DB ──────────────────────────
        if apollo_partners:
            try:
                async with pool.acquire() as conn:
                    upserted = 0
                    for p in apollo_partners:
                        await conn.fetchrow(
                            _UPSERT_APOLLO_PARTNER,
                            p.get("partner_name", ""),
                            p.get("category", input_category),
                            p.get("subcategories", input_category),
                            p.get("website", ""),
                            "Yet to Start",
                            p.get("digitisation", "Semi-digitised"),
                            p.get("region", "Local"),
                            p.get("phone_number", "") or "",
                            p.get("email_id", "") or "",
                            p.get("linkedin_profile", "") or "",
                            "apollo_prospecting",
                        )
                        upserted += 1
                logger.info(
                    "%sDiscovery: upserted %d Apollo partners to DB.",
                    prefix, upserted,
                )
            except Exception as exc:
                logger.error("%sDiscovery: Apollo upsert failed: %s", prefix, exc)

    # ── Step 4: Merge + deduplicate ───────────────────────────────────────
    seen_names: set[str] = {p.get("partner_name", "").lower() for p in db_partners}
    new_from_apollo = []

    for p in apollo_partners:
        name_lower = p.get("partner_name", "").lower()
        if name_lower and name_lower not in seen_names:
            seen_names.add(name_lower)
            new_from_apollo.append(p)

    discovered = db_partners + new_from_apollo

    logger.info(
        "%sDiscovery: total %d partners (%d DB + %d new from Apollo).",
        prefix, len(discovered), len(db_partners), len(new_from_apollo),
    )

    return {"discovered_partners": discovered}