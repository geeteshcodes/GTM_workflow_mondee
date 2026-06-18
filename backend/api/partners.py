"""
backend/api/partners.py
-----------------------
REST endpoints for the partners table.

GET  /api/partners/          — Paginated list with optional filters
GET  /api/partners/{id}      — Single partner detail
PATCH /api/partners/{id}/status — Update partner status
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.connection import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class StatusUpdate(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
async def list_partners(
    status: Optional[str] = Query(None, description="Filter by status"),
    category: Optional[str] = Query(None, description="Filter by category (case-insensitive)"),
    region: Optional[str] = Query(None, description="Filter by region"),
    sheet_source: Optional[str] = Query(None, description="'track1' or 'track2'"),
    search: Optional[str] = Query(None, description="Search partner_name or website"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return a paginated, filtered list of all partners."""
    conditions = []
    params: list = []
    idx = 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if category:
        # Match against individual subcategory tags (exact) or category name (fuzzy)
        cat_idx = idx
        conditions.append(f"(${cat_idx} = ANY(subcategory_tags) OR category ILIKE ${cat_idx+1})")
        params.append(category)
        params.append(f"%{category}%")
        idx += 2
    if region:
        conditions.append(f"region ILIKE ${idx}")
        params.append(f"%{region}%")
        idx += 1
    if sheet_source:
        conditions.append(f"sheet_source = ${idx}")
        params.append(sheet_source)
        idx += 1
    if search:
        conditions.append(f"(partner_name ILIKE ${idx} OR website ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS total FROM partners {where_clause}", *params
        )
        rows = await conn.fetch(
            f"""
            SELECT id, partner_name, digitisation, category, subcategories,
                   subcategory_tags, website, product_count, status, integrated, region,
                   phone_number, email_id, linkedin_profile, sheet_source
            FROM partners
            {where_clause}
            ORDER BY sheet_source, partner_name
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params, limit, offset,
        )

    partners = [dict(r) for r in rows]
    return {
        "total": count_row["total"],
        "limit": limit,
        "offset": offset,
        "partners": partners,
    }


@router.get("/{partner_id}")
async def get_partner(partner_id: int):
    """Return a single partner by ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, partner_name, digitisation, category, subcategories,
                   website, product_count, status, integrated, region,
                   phone_number, email_id, linkedin_profile, sheet_source
            FROM partners WHERE id = $1
            """,
            partner_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Partner not found")
    return dict(row)


@router.patch("/{partner_id}/status")
async def update_partner_status(partner_id: int, body: StatusUpdate):
    """Update the status of a partner (e.g. mark as 'Partner Outreach')."""
    allowed_statuses = [
        "Yet to Start",
        "Partner Outreach",
        "Onboarding",
        "Fully Onboarded",
        "Rejected",
    ]
    if body.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {allowed_statuses}",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE partners SET status = $1 WHERE id = $2",
            body.status, partner_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Partner not found")

    logger.info("Partner %d status updated to %r", partner_id, body.status)
    return {"id": partner_id, "status": body.status, "updated": True}