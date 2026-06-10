"""
backend/api/enrichment.py
-------------------------
Enrichment-stage endpoints.

GET /api/enrichment/
    Returns enriched partners — those that have at least one contact
    field filled (phone, email, or LinkedIn), with per-field fill stats.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

from db.connection import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def list_enriched(
    search: Optional[str] = Query(None),
    has_phone: Optional[bool] = Query(None),
    has_email: Optional[bool] = Query(None),
    has_linkedin: Optional[bool] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Returns partners that have been enriched (at least one contact field present).
    Includes aggregate fill-rate stats for the enrichment dashboard.
    """
    conditions = [
        """(
            (phone_number IS NOT NULL AND phone_number != '')
         OR (email_id IS NOT NULL AND email_id != '')
         OR (linkedin_profile IS NOT NULL AND linkedin_profile != '')
        )"""
    ]
    params: list = []
    idx = 1

    if has_phone is True:
        conditions.append(f"phone_number IS NOT NULL AND phone_number != ''")
    if has_email is True:
        conditions.append(f"email_id IS NOT NULL AND email_id != ''")
    if has_linkedin is True:
        conditions.append(f"linkedin_profile IS NOT NULL AND linkedin_profile != ''")

    if search:
        conditions.append(f"partner_name ILIKE ${idx}")
        params.append(f"%{search}%")
        idx += 1

    where = "WHERE " + " AND ".join(conditions)

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Aggregate stats over ALL enriched partners (not paginated)
        stats_row = await conn.fetchrow(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN phone_number IS NOT NULL AND phone_number != '' THEN 1 ELSE 0 END)     AS phone,
                SUM(CASE WHEN email_id IS NOT NULL AND email_id != '' THEN 1 ELSE 0 END)              AS email,
                SUM(CASE WHEN linkedin_profile IS NOT NULL AND linkedin_profile != '' THEN 1 ELSE 0 END) AS linkedin,
                SUM(CASE WHEN phone_number IS NOT NULL AND phone_number != ''
                          AND email_id IS NOT NULL AND email_id != ''
                          AND linkedin_profile IS NOT NULL AND linkedin_profile != '' THEN 1 ELSE 0 END) AS fully_enriched
            FROM partners {where}
            """,
            *params,
        )

        rows = await conn.fetch(
            f"""
            SELECT id, partner_name, category, subcategories, website,
                   region, status, digitisation, phone_number, email_id,
                   linkedin_profile, sheet_source
            FROM partners {where}
            ORDER BY partner_name
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params, limit, offset,
        )

    stats = dict(stats_row) if stats_row else {}
    total = int(stats.get("total") or 0)

    enrichment_stats = {
        "total":          total,
        "verified":       int(stats.get("fully_enriched") or 0),
        "pending":        total - int(stats.get("fully_enriched") or 0),
        "failed":         0,
        "phone_count":    int(stats.get("phone")   or 0),
        "email_count":    int(stats.get("email")   or 0),
        "linkedin_count": int(stats.get("linkedin") or 0),
    }

    leads = []
    for r in rows:
        p = dict(r)
        # Compute per-partner fill flags
        p["has_phone"]    = bool(p.get("phone_number"))
        p["has_email"]    = bool(p.get("email_id"))
        p["has_linkedin"] = bool(p.get("linkedin_profile"))
        fill_count = sum([p["has_phone"], p["has_email"], p["has_linkedin"]])
        p["fill_rate"]    = round(fill_count / 3 * 100)
        leads.append(p)

    return {"leads": leads, "stats": enrichment_stats}
