"""
nodes/outreach/outreach_node.py
--------------------------------
Outreach Node — Stage 3 of the pipeline.

Implementation
---------------
For each enriched partner with a usable phone_number, places an outbound
voice call via the voice agent (Twilio + Deepgram + Groq), waits for the
call to complete (including post-call summarisation), and records the
result.

Partners with no phone_number are skipped (logged, not failed) — they
will need email/LinkedIn outreach instead, which is a separate concern.

Concurrency
-----------
Calls are placed with a concurrency cap (default 2) since voice calls are
expensive, slow (up to a few minutes each), and Twilio/Deepgram have their
own rate limits. Controlled via OUTREACH_CALL_CONCURRENCY env var.

Input  (GraphState field): enriched_partners: list[dict]
Output (GraphState field): outreach_results: list[dict]
    Each result: {
        "partner_name": str,
        "call_sid": str | None,
        "status": str,           # completed | no-answer | busy | failed | timeout | skipped | error
        "duration_s": int,
        "summary": dict | None,
    }
"""

import asyncio
import logging
import os

from state import GraphState
from voice_agent.engine import place_call

logger = logging.getLogger(__name__)

_CALL_CONCURRENCY: int = int(os.getenv("OUTREACH_CALL_CONCURRENCY", "2"))
_CALL_TIMEOUT_S: int = int(os.getenv("OUTREACH_CALL_TIMEOUT_S", "180"))

_DEFAULT_SCRIPT = (
    "Hello! This is an automated call from the Aarna GTM team at Mondee. "
    "We'd love to explore a partnership opportunity with you. "
    "Could you tell me a bit about your business and how you currently "
    "manage bookings?"
)


def _build_script(partner: dict) -> str:
    """Personalise the opening line using whatever contact info we have."""
    name = partner.get("partner_name", "your business")
    contact_name = partner.get("contact_name")

    greeting = f"Hi {contact_name}, " if contact_name else "Hello, "
    return (
        f"{greeting}this is an automated call from the Aarna GTM team at Mondee, "
        f"reaching out to {name}. We'd love to explore a partnership opportunity "
        f"with you. Could you tell me a bit about how you currently manage bookings?"
    )


async def _call_one_partner(partner: dict, run_id: str, semaphore: asyncio.Semaphore) -> dict:
    name = partner.get("partner_name", "Unknown")
    phone = (partner.get("phone_number") or "").strip()

    if not phone:
        logger.info("[%s] Outreach: skipping %r — no phone number.", run_id, name)
        return {
            "partner_name": name, "call_sid": None, "status": "skipped",
            "duration_s": 0, "summary": None, "reason": "no phone number",
        }

    async with semaphore:
        logger.info("[%s] Outreach: calling %r at %s…", run_id, name, phone)
        try:
            result = await place_call(
                to=phone,
                script=_build_script(partner),
                mission=f"GTM UAE partner outreach — {partner.get('category', 'General')}",
                partner_id=partner.get("id"),
                partner_name=name,
                timeout_s=_CALL_TIMEOUT_S,
            )
        except Exception as exc:
            logger.error("[%s] Outreach: call to %r failed with exception: %s", run_id, name, exc)
            return {
                "partner_name": name, "call_sid": None, "status": "error",
                "duration_s": 0, "summary": None, "reason": str(exc),
            }

    logger.info(
        "[%s] Outreach: %r call finished — status=%s duration=%ss",
        run_id, name, result.get("status"), result.get("duration_s"),
    )
    return {
        "partner_name": name,
        "call_sid": result.get("call_sid"),
        "status": result.get("status"),
        "duration_s": result.get("duration_s", 0),
        "summary": result.get("summary"),
    }


async def outreach_node(state: GraphState) -> dict:
    run_id = state.get("run_id", "")
    prefix = f"[{run_id}] " if run_id else ""

    enriched = state.get("enriched_partners", [])
    logger.info("%sOutreach node: processing %d enriched partners.", prefix, len(enriched))

    if not enriched:
        return {"outreach_results": []}

    semaphore = asyncio.Semaphore(_CALL_CONCURRENCY)

    results = await asyncio.gather(
        *[_call_one_partner(p, run_id, semaphore) for p in enriched],
        return_exceptions=False,
    )

    called = sum(1 for r in results if r["status"] not in ("skipped", "error"))
    skipped = sum(1 for r in results if r["status"] == "skipped")
    logger.info(
        "%sOutreach node: complete — %d called, %d skipped (no phone), %d total.",
        prefix, called, skipped, len(results),
    )

    return {"outreach_results": list(results)}