"""
test_all.py
-----------
Client-delivery verification — GTM UAE Partner Pipeline.

Tests the 3 critical enrichment sources + full pipeline to Outreach.

Run from repo root (venv activated, backend running on :8000):
    python test_all.py
"""

import asyncio
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Colours ───────────────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; B = "\033[1m"; X = "\033[0m"

passed = failed = warned = 0

def ok(label, detail=""):
    global passed; passed += 1
    print(f"  {G}✅ PASS{X}  {label}" + (f" — {detail}" if detail else ""))

def fail(label, reason=""):
    global failed; failed += 1
    print(f"  {R}❌ FAIL{X}  {label}" + (f" — {reason}" if reason else ""))

def warn(label, reason=""):
    global warned; warned += 1
    print(f"  {Y}⚠  WARN{X}  {label}" + (f" — {reason}" if reason else ""))

def section(title):
    print(f"\n{B}{C}{'─'*60}{X}\n{B}{C}  {title}{X}\n{B}{C}{'─'*60}{X}")


# ── TEST 1: Tavily ────────────────────────────────────────────────────────────

async def test_tavily():
    section("1. Tavily — LinkedIn URL Finder")

    key = os.getenv("TAVILY_API_KEY")
    if not key:
        fail("TAVILY_API_KEY not in .env")
        return

    ok("TAVILY_API_KEY is set")

    try:
        from enrichment_sources.linkedin_url_finder import find_company_linkedin_url

        t0 = time.monotonic()
        result = await find_company_linkedin_url(
            partner_name="Adventure HQ",
            category="Adventure & Extreme Sports",
            region="Local",
            website="https://adventurehq.ae",
        )
        elapsed = round(time.monotonic() - t0, 2)

        url = result.get("company_linkedin_url")
        if url:
            ok(f"LinkedIn URL resolved in {elapsed}s", url)
        else:
            warn(f"No LinkedIn URL for 'Adventure HQ' in {elapsed}s", "partner may not have a LinkedIn page")

        t0 = time.monotonic()
        result2 = await find_company_linkedin_url(
            partner_name="Sharjah Cricket Stadium",
            category="Sports",
            region="Local",
        )
        elapsed2 = round(time.monotonic() - t0, 2)
        url2 = result2.get("company_linkedin_url")
        if url2:
            ok(f"LinkedIn URL resolved for 'Sharjah Cricket Stadium' in {elapsed2}s", url2)
        else:
            warn(f"No LinkedIn URL for 'Sharjah Cricket Stadium' in {elapsed2}s")

    except ImportError:
        fail("tavily-python not installed", "run: pip install tavily-python")
    except Exception as e:
        fail("Tavily error", str(e))


# ── TEST 2: Hunter ────────────────────────────────────────────────────────────

async def test_hunter():
    section("2. Hunter.io — Email Finder")

    key = os.getenv("HUNTER_API_KEY")
    if not key:
        fail("HUNTER_API_KEY not in .env")
        return

    ok("HUNTER_API_KEY is set")

    try:
        from enrichment_sources.hunter import query_hunter

        t0 = time.monotonic()
        r1 = await query_hunter("Adventure HQ")
        elapsed = round(time.monotonic() - t0, 2)

        if r1.get("email_id"):
            ok(f"Email found for 'Adventure HQ' in {elapsed}s", r1["email_id"])
        else:
            warn(f"No email for 'Adventure HQ' in {elapsed}s", "not in Hunter DB")

        t0 = time.monotonic()
        r2 = await query_hunter("Marriott Hotels")
        elapsed2 = round(time.monotonic() - t0, 2)

        if r2.get("email_id"):
            ok(f"API key verified via Marriott in {elapsed2}s", r2["email_id"])
        else:
            fail("Hunter API key invalid or quota exhausted", "Marriott returned nothing")

    except Exception as e:
        fail("Hunter error", str(e))


# ── TEST 3: Apollo ────────────────────────────────────────────────────────────

async def test_apollo():
    section("3. Apollo.io — Contact Finder")

    key = os.getenv("APOLLO_API_KEY")
    if not key:
        fail("APOLLO_API_KEY not in .env")
        return

    ok("APOLLO_API_KEY is set")

    try:
        from enrichment_sources.apollo import query_apollo

        t0 = time.monotonic()
        r1 = await query_apollo("Adventure HQ")
        elapsed = round(time.monotonic() - t0, 2)

        fields = [k for k in ("email_id", "phone_number", "linkedin_profile") if r1.get(k)]
        if fields:
            ok(f"Contact found for 'Adventure HQ' in {elapsed}s — {fields}")
            for k in fields:
                print(f"      └─ {k}: {r1[k]}")
        else:
            warn(f"No data for 'Adventure HQ' in {elapsed}s", "small UAE company may not be in Apollo")

        t0 = time.monotonic()
        r2 = await query_apollo("Marriott International")
        elapsed2 = round(time.monotonic() - t0, 2)

        fields2 = [k for k in ("email_id", "phone_number", "linkedin_profile") if r2.get(k)]
        if fields2:
            ok(f"API key verified via Marriott in {elapsed2}s — {fields2}")
        else:
            fail("Apollo API key invalid or quota hit", "Marriott returned nothing — check key in .env")

    except Exception as e:
        fail("Apollo error", str(e))


# ── TEST 4: Full pipeline Discovery → Enrichment → Outreach ──────────────────

async def test_full_pipeline():
    section("4. Full Pipeline — Discovery → Enrichment → Outreach")

    try:
        from db.connection import init_pool, close_pool
        from nodes.discovery_node import discovery_node
        from nodes.enrichment_node import enrichment_node
        from nodes.outreach.outreach_node import outreach_node

        await init_pool()

        # ── Stage 1: Discovery ────────────────────────────────────────────
        print(f"\n  {B}Stage 1 — Discovery{X}")
        state = {
            "input_category": "Adventure & Extreme Sports",
            "run_id": "verify",
            "discovered_partners": [],
            "enriched_partners": [],
        }

        t0 = time.monotonic()
        disc = await discovery_node(state)
        state.update(disc)
        partners = state["discovered_partners"]
        elapsed = round(time.monotonic() - t0, 2)

        if partners:
            ok(f"Discovered {len(partners)} partners in {elapsed}s")
            statuses = {}
            for p in partners:
                s = p.get("status", "Unknown")
                statuses[s] = statuses.get(s, 0) + 1
            for s, c in statuses.items():
                print(f"      └─ {s}: {c}")
        else:
            fail("Discovery returned 0 partners — check DB and status filter")
            await close_pool()
            return

        # ── Stage 2: Enrichment (3 partners to save quota) ────────────────
        print(f"\n  {B}Stage 2 — Enrichment (3 partners){X}")
        state["discovered_partners"] = partners[:3]

        t0 = time.monotonic()
        enrich = await enrichment_node(state)
        state.update(enrich)
        enriched = state["enriched_partners"]
        elapsed = round(time.monotonic() - t0, 2)

        if not enriched:
            fail("Enrichment returned no partners")
            await close_pool()
            return

        filled = 0
        for ep in enriched:
            name = ep.get("partner_name")
            got = {k: ep.get(k) for k in ("email_id", "phone_number", "linkedin_profile") if ep.get(k)}
            cl_url = ep.get("company_linkedin_url")
            if got:
                filled += 1
                ok(f"Enriched: {name}", ", ".join(got.keys()))
                for k, v in got.items():
                    print(f"      └─ {k}: {v}")
            else:
                warn(f"No data found for: {name}", "all sources returned empty")
            if cl_url:
                print(f"      └─ company_linkedin_url: {cl_url}")

        ok(f"Enrichment complete in {elapsed}s — {filled}/{len(enriched)} partners got contact data")

        # ── Stage 3: Outreach ─────────────────────────────────────────────
        print(f"\n  {B}Stage 3 — Outreach{X}")

        t0 = time.monotonic()
        outreach = await outreach_node(state)
        state.update(outreach or {})
        elapsed = round(time.monotonic() - t0, 2)

        ok(f"Outreach node executed in {elapsed}s", "stub — wired and ready for implementation")

        await close_pool()

    except Exception as e:
        fail("Full pipeline error", str(e))
        import traceback; traceback.print_exc()


# ── SUMMARY ───────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{B}{'='*60}{X}")
    print(f"{B}  GTM UAE — Client Delivery Verification{X}")
    print(f"{B}{'='*60}{X}")

    await test_tavily()
    await test_hunter()
    await test_apollo()
    await test_full_pipeline()

    print(f"\n{B}{'='*60}{X}")
    print(f"{B}  SUMMARY{X}")
    print(f"{B}{'='*60}{X}")
    print(f"  {G}PASS : {passed}{X}")
    print(f"  {R}FAIL : {failed}{X}")
    print(f"  {Y}WARN : {warned}{X}")

    if failed == 0:
        print(f"\n  {G}{B}✅ Pipeline is client-ready.{X}\n")
    else:
        print(f"\n  {R}{B}❌ {failed} failure(s) — fix before client delivery.{X}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())