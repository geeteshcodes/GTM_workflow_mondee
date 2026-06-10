"""
backend/api/analytics.py
------------------------
Analytics / Dashboard endpoint.

GET /api/analytics/dashboard
    Returns aggregate stats used by the Command Dashboard.
"""

import logging
from datetime import datetime

from fastapi import APIRouter

from db.connection import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard():
    """
    Return all dashboard metrics in a single payload:
      - stats:         high-level counts by pipeline stage
      - funnel:        stage-by-stage partner counts for the funnel chart
      - categories:    distribution of partners by top-level category
      - trends:        simple delta strings (placeholder)
      - activity_feed: last N status changes (mocked from DB data)
      - hitl_queue:    partners needing human review (placeholder)
      - pending_tasks: count of items in hitl_queue
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ── Aggregate counts ──────────────────────────────────────────────
        agg = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                                                           AS total,
                SUM(CASE WHEN status = 'Yet to Start'       THEN 1 ELSE 0 END)                   AS yet_to_start,
                SUM(CASE WHEN status = 'Partner Outreach'   THEN 1 ELSE 0 END)                   AS outreach,
                SUM(CASE WHEN status = 'Onboarding'         THEN 1 ELSE 0 END)                   AS onboarding,
                SUM(CASE WHEN status = 'Fully Onboarded'    THEN 1 ELSE 0 END)                   AS live,
                SUM(CASE WHEN (phone_number IS NOT NULL AND phone_number != '')
                           OR (email_id IS NOT NULL AND email_id != '')
                           OR (linkedin_profile IS NOT NULL AND linkedin_profile != '')
                           THEN 1 ELSE 0 END)                                                     AS enriched
            FROM partners
            """
        )

        # ── Category breakdown ────────────────────────────────────────────
        cat_rows = await conn.fetch(
            """
            SELECT category, COUNT(*) AS cnt
            FROM partners
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY cnt DESC
            LIMIT 10
            """
        )

        # ── Recent activity (last 20 partners added / status updated) ─────
        recent_rows = await conn.fetch(
            """
            SELECT partner_name, status, category
            FROM partners
            ORDER BY id DESC
            LIMIT 20
            """
        )

    agg = dict(agg) if agg else {}
    total      = int(agg.get("total", 0))
    yet_start  = int(agg.get("yet_to_start", 0))
    enriched   = int(agg.get("enriched", 0))
    outreach   = int(agg.get("outreach", 0))
    onboarding = int(agg.get("onboarding", 0))
    live       = int(agg.get("live", 0))

    stats = {
        "total_leads":      total,
        "discovered_today": yet_start,
        "qualified":        enriched,
        "outreach":         outreach,
        "onboarding":       onboarding,
        "live":             live,
    }

    funnel = [
        {"name": "Discovery",  "value": total,      "fill": "#3b82f6"},
        {"name": "Enrichment", "value": enriched,   "fill": "#8b5cf6"},
        {"name": "Outreach",   "value": outreach,   "fill": "#f59e0b"},
        {"name": "Onboarding", "value": onboarding, "fill": "#06b6d4"},
        {"name": "Live",       "value": live,        "fill": "#10b981"},
    ]

    categories = [
        {"name": r["category"], "count": int(r["cnt"])}
        for r in cat_rows
    ]

    # Activity feed — derive from recent records
    _status_icons = {
        "Yet to Start":    "🔍",
        "Partner Outreach": "📨",
        "Onboarding":      "🤝",
        "Fully Onboarded": "✅",
        "Rejected":        "❌",
    }
    activity_feed = []
    now = datetime.now()
    for i, r in enumerate(recent_rows):
        icon  = _status_icons.get(r["status"], "📋")
        stage = r["status"] or "Updated"
        text  = f"{icon} {r['partner_name']} — {stage}"
        activity_feed.append({"icon": icon, "text": text, "time": "recently"})

    return {
        "stats":         stats,
        "trends":        {
            "total_leads":      f"+{max(0, total - 10)}",
            "discovered_today": f"+{yet_start}",
            "qualified":        f"{round(enriched / total * 100) if total else 0}%",
            "outreach":         f"+{outreach}",
            "onboarding":       f"+{onboarding}",
            "live":             f"+{live}",
        },
        "funnel":        funnel,
        "categories":    categories,
        "activity_feed": activity_feed,
        "hitl_queue":    [],
        "pending_tasks": 0,
    }
