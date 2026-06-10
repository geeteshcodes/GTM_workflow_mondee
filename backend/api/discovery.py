"""
backend/api/discovery.py
------------------------
Discovery-stage endpoints.

GET /api/discovery/
    Returns partners whose status is 'Yet to Start' (the discovery pool).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

from db.connection import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()

_DISCOVERY_STATUS = "Yet to Start"


@router.get("/")
async def list_discovered(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Returns partners in the discovery pool (status = 'Yet to Start').
    Optionally filter by category or search by name.
    """
    conditions = ["status = $1"]
    params: list = [_DISCOVERY_STATUS]
    idx = 2

    if category:
        conditions.append(f"subcategories ILIKE ${idx}")
        params.append(f"%{category}%")
        idx += 1
    if search:
        conditions.append(f"partner_name ILIKE ${idx}")
        params.append(f"%{search}%")
        idx += 1

    where = "WHERE " + " AND ".join(conditions)

    pool = await get_pool()
    async with pool.acquire() as conn:
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS total FROM partners {where}", *params
        )
        rows = await conn.fetch(
            f"""
            SELECT id, partner_name, category, subcategories, website,
                   region, status, digitisation, product_count,
                   phone_number, email_id, linkedin_profile, sheet_source
            FROM partners {where}
            ORDER BY sheet_source, partner_name
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params, limit, offset,
        )

    leads = [dict(r) for r in rows]
    return {
        "total":  int(count_row["total"]) if count_row else 0,
        "leads":  leads,
        "status": _DISCOVERY_STATUS,
    }
