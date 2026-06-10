"""
backend/api/outreach.py
-----------------------
Outreach endpoints.

GET  /api/outreach/          — List enriched partners ready for outreach
POST /api/outreach/launch    — Trigger outreach sequence for a partner
                               (calls run_outreach_workflow when wired in)
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.connection import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Try to import the real outreach workflow (wired in by the user later)
# Falls back to a stub that logs and returns gracefully.
# ---------------------------------------------------------------------------
try:
    from nodes.outreach.outreach_workflow import run_outreach_workflow  # type: ignore
    _HAS_REAL_WORKFLOW = True
    logger.info("Outreach: loaded real run_outreach_workflow.")
except ImportError:
    _HAS_REAL_WORKFLOW = False
    logger.info("Outreach: run_outreach_workflow not found — using stub.")

    async def run_outreach_workflow(partner: dict, channels: list, custom_message: str = "") -> dict:
        """Stub — replace by importing the real workflow."""
        return {
            "lead_name": partner.get("partner_name", "Unknown"),
            "results": [
                {"channel": ch, "result": {"status": "stub_pending", "note": "Outreach workflow not yet wired"}}
                for ch in channels
            ],
        }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OutreachLaunchRequest(BaseModel):
    partner_name: str
    channels: list[str] = ["whatsapp", "email"]
    custom_message: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
async def list_outreach_partners(
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Returns enriched partners (those with at least one contact field filled)
    along with per-channel send counts for the stats cards.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Partners with at least one contact method
        rows = await conn.fetch(
            """
            SELECT id, partner_name, category, subcategories, region,
                   phone_number, email_id, linkedin_profile, status, sheet_source
            FROM partners
            WHERE (phone_number IS NOT NULL AND phone_number != '')
               OR (email_id IS NOT NULL AND email_id != '')
               OR (linkedin_profile IS NOT NULL AND linkedin_profile != '')
            ORDER BY partner_name
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )

        # Channel stats (how many partners have each contact method)
        stats_rows = await conn.fetch(
            """
            SELECT
                SUM(CASE WHEN phone_number IS NOT NULL AND phone_number != '' THEN 1 ELSE 0 END)     AS whatsapp,
                SUM(CASE WHEN email_id IS NOT NULL AND email_id != '' THEN 1 ELSE 0 END)              AS email,
                SUM(CASE WHEN linkedin_profile IS NOT NULL AND linkedin_profile != '' THEN 1 ELSE 0 END) AS linkedin
            FROM partners
            """
        )

    leads = []
    for r in rows:
        p = dict(r)
        name_lower = (p.get("partner_name") or "").lower()
        if search and search.lower() not in name_lower:
            continue
        leads.append({
            "id":            str(p["id"]),
            "business_name": p.get("partner_name"),
            "category":      p.get("category"),
            "score":         75,          # placeholder — enrich with real scoring later
            "score_tier":    "WARM",
            "phone":         p.get("phone_number"),
            "email":         p.get("email_id"),
            "linkedin_url":  p.get("linkedin_profile"),
            "instagram":     None,
            "attempts":      0,
            "last_channel":  _last_channel(p),
            "last_status":   "Pending",
            "region":        p.get("region"),
            "sheet_source":  p.get("sheet_source"),
        })

    stats = dict(stats_rows[0]) if stats_rows else {}
    channels = [
        {"channel": "whatsapp", "count": int(stats.get("whatsapp") or 0)},
        {"channel": "email",    "count": int(stats.get("email")    or 0)},
        {"channel": "linkedin", "count": int(stats.get("linkedin") or 0)},
        {"channel": "voice",    "count": 0},
        {"channel": "instagram","count": 0},
    ]

    return {"leads": leads, "channels": channels}


def _last_channel(partner: dict) -> str:
    """Determine the most recently tried / best channel based on available data."""
    if partner.get("phone_number"):
        return "whatsapp"
    if partner.get("email_id"):
        return "email"
    if partner.get("linkedin_profile"):
        return "linkedin"
    return "—"


@router.post("/launch")
async def launch_outreach(req: OutreachLaunchRequest):
    """
    Launch outreach for a partner.
    Calls run_outreach_workflow (real or stub).
    """
    if not req.partner_name.strip():
        raise HTTPException(status_code=400, detail="partner_name is required")

    # Fetch partner record from DB
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, partner_name, category, phone_number, email_id,
                   linkedin_profile, website, region
            FROM partners WHERE partner_name ILIKE $1 LIMIT 1
            """,
            req.partner_name.strip(),
        )

    partner = dict(row) if row else {"partner_name": req.partner_name}

    logger.info(
        "Outreach launch: partner=%r channels=%s workflow_available=%s",
        req.partner_name,
        req.channels,
        _HAS_REAL_WORKFLOW,
    )

    result = await run_outreach_workflow(
        partner=partner,
        channels=req.channels,
        custom_message=req.custom_message,
    )

    return result
