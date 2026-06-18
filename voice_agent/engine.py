"""
voice_agent/engine.py
----------------------
Outbound voice agent — refactored from the standalone script to:
  1. Use the shared PostgreSQL pool (db/connection.py) instead of SQLite.
  2. Run as part of the main FastAPI backend (no per-call ngrok/server spin-up).
  3. Expose an async `place_call()` function the outreach_node can await
     and get back a structured result once the call completes.

Stack: Twilio (calls) · Deepgram (live STT) · Groq gpt-oss-20b (summary) · PostgreSQL (storage)

Routes in this module are mounted onto the main FastAPI app in backend/main.py:
    /twilio/outbound/{call_sid}
    /twilio/status
    /ws/audio/{call_sid}

Public function for the outreach node:
    await place_call(to=..., script=..., mission=..., partner_id=..., partner_name=...)
    -> waits for the call to fully complete (including summarisation) and
       returns a result dict.
"""

import os
import json
import base64
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket, Response
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
from twilio.rest import Client as TwilioClient

from db.connection import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
DEEPGRAM_API_KEY    = os.getenv("DEEPGRAM_API_KEY")
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")

# Set once at backend startup by voice_agent/tunnel.py — see init_voice_agent()
PUBLIC_HOST: str = ""

# In-memory call state, keyed by Twilio CallSid.
# Holds the live transcript buffer and an asyncio.Event the outreach node
# awaits on so it knows when the full call (incl. summarisation) is done.
_calls: dict[str, dict] = {}


def set_public_host(host: str) -> None:
    """Called once at startup after the ngrok tunnel is established."""
    global PUBLIC_HOST
    PUBLIC_HOST = host
    logger.info("Voice agent public host set to: %s", host)


# ---------------------------------------------------------------------------
# Database helpers (PostgreSQL via shared pool)
# ---------------------------------------------------------------------------

async def _db_upsert_call(call_sid: str, **kwargs) -> None:
    pool = await get_pool()
    cols = list(kwargs.keys())
    values = list(kwargs.values())
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    col_list = ", ".join(["call_sid"] + cols)
    placeholders = ", ".join(f"${i+1}" for i in range(len(values) + 1))

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO outreach_calls ({col_list})
                VALUES ({placeholders})
                ON CONFLICT (call_sid) DO UPDATE SET {set_clause}
                """,
                call_sid, *values,
            )
    except Exception as exc:
        logger.warning("Voice agent: DB upsert failed for %s — %s (run voice_agent/db_schema.sql on Supabase)", call_sid, exc)


async def _db_insert_line(call_sid: str, speaker: str, text: str, ts: datetime) -> None:
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO outreach_transcript_lines (call_sid, speaker, line_text, spoken_at) "
                "VALUES ($1, $2, $3, $4)",
                call_sid, speaker, text, ts,
            )
    except Exception as exc:
        logger.warning("Voice agent: DB line insert failed for %s — %s", call_sid, exc)


async def _db_insert_summary(call_sid: str, parsed: dict, raw: str) -> None:
    pool = await get_pool()
    try:
      async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO outreach_call_summaries
                (call_sid, outcome, key_points, action_items, sentiment, notable_quotes, raw_summary)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (call_sid) DO UPDATE SET
                outcome = EXCLUDED.outcome,
                key_points = EXCLUDED.key_points,
                action_items = EXCLUDED.action_items,
                sentiment = EXCLUDED.sentiment,
                notable_quotes = EXCLUDED.notable_quotes,
                raw_summary = EXCLUDED.raw_summary
            """,
            call_sid,
            parsed.get("outcome", ""),
            json.dumps(parsed.get("key_points", [])),
            json.dumps(parsed.get("action_items", [])),
            parsed.get("sentiment", ""),
            json.dumps(parsed.get("notable_quotes", [])),
            raw,
        )
    except Exception as exc:
        logger.warning("Voice agent: DB summary insert failed for %s — %s", call_sid, exc)


# ---------------------------------------------------------------------------
# Public entry point — what outreach_node.py calls
# ---------------------------------------------------------------------------

async def place_call(
    to: str,
    script: str,
    mission: str,
    partner_id: Optional[int] = None,
    partner_name: Optional[str] = None,
    timeout_s: int = 180,
) -> dict:
    """
    Place an outbound call and wait for it to fully complete (including
    post-call summarisation).

    Returns a result dict:
        {
            "call_sid": str,
            "status": str,          # completed | no-answer | busy | failed | timeout
            "duration_s": int,
            "summary": dict | None, # parsed Groq summary, if call connected
        }
    """
    if not PUBLIC_HOST:
        logger.error("Voice agent: PUBLIC_HOST not set — cannot place call to %r.", to)
        return {"call_sid": None, "status": "error", "duration_s": 0, "summary": None,
                "error": "Voice agent tunnel not initialised"}

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        logger.error("Voice agent: Twilio credentials missing — cannot place call to %r.", to)
        return {"call_sid": None, "status": "error", "duration_s": 0, "summary": None,
                "error": "Twilio credentials not configured"}

    twilio = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    done_event = asyncio.Event()

    try:
        call = await asyncio.to_thread(
            twilio.calls.create,
            url=f"https://{PUBLIC_HOST}/twilio/outbound",
            status_callback=f"https://{PUBLIC_HOST}/twilio/status",
            status_callback_method="POST",
            status_callback_event=["completed", "no-answer", "busy", "failed"],
            to=to,
            from_=TWILIO_PHONE_NUMBER,
        )
    except Exception as exc:
        logger.error("Voice agent: failed to place call to %r: %s", to, exc)
        return {"call_sid": None, "status": "error", "duration_s": 0, "summary": None, "error": str(exc)}

    call_sid = call.sid
    _calls[call_sid] = {
        "script": script,
        "mission": mission,
        "partner_id": partner_id,
        "partner_name": partner_name,
        "to": to,
        "transcript": [],
        "done_event": done_event,
        "result": None,
    }

    await _db_upsert_call(
        call_sid,
        partner_id=partner_id,
        partner_name=partner_name,
        mission=mission,
        to_number=to,
        status="initiated",
        started_at=datetime.now(timezone.utc),
    )

    logger.info("Voice agent: call placed SID=%s to=%s partner=%r", call_sid, to, partner_name)

    try:
        await asyncio.wait_for(done_event.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("Voice agent: call %s timed out after %ds — marking as timeout.", call_sid, timeout_s)
        result = {"call_sid": call_sid, "status": "timeout", "duration_s": timeout_s, "summary": None}
        _calls.pop(call_sid, None)
        return result

    result = _calls.get(call_sid, {}).get("result") or {
        "call_sid": call_sid, "status": "unknown", "duration_s": 0, "summary": None,
    }
    _calls.pop(call_sid, None)
    return result


# ---------------------------------------------------------------------------
# Twilio webhook: call connected → respond with TwiML
# ---------------------------------------------------------------------------

@router.api_route("/twilio/outbound", methods=["GET", "POST"])
async def twilio_outbound(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")

    meta = _calls.get(call_sid, {})

    await _db_upsert_call(
        call_sid,
        status="connected",
        from_number=form.get("From", ""),
    )

    logger.info("Voice agent: call connected SID=%s", call_sid)

    response = VoiceResponse()
    script = meta.get("script", "Hello! This is an automated call.")
    response.say(script, voice="Polly.Joanna", language="en-US")
    response.pause(length=1)

    connect = Connect()
    stream = Stream(url=f"wss://{PUBLIC_HOST}/ws/audio/{call_sid}")
    stream.parameter(name="callSid", value=call_sid)
    connect.append(stream)
    response.append(connect)

    return Response(content=str(response), media_type="application/xml")


# ---------------------------------------------------------------------------
# Twilio webhook: call ended
# ---------------------------------------------------------------------------

@router.api_route("/twilio/status", methods=["POST"])
async def twilio_status(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    status = form.get("CallStatus", "")
    duration = int(form.get("CallDuration", "0") or 0)

    logger.info("Voice agent: call ended SID=%s status=%s duration=%ds", call_sid, status, duration)

    if call_sid in _calls:
        _calls[call_sid]["status"] = status
        _calls[call_sid]["duration"] = duration

    await _db_upsert_call(
        call_sid,
        status=status,
        duration_s=duration,
        ended_at=datetime.now(timezone.utc),
    )

    # If the call was never answered, the audio WebSocket never opens —
    # finalise immediately rather than waiting on a stream that won't come.
    if status in ("no-answer", "busy", "failed") and call_sid in _calls:
        meta = _calls[call_sid]
        meta["result"] = {
            "call_sid": call_sid,
            "status": status,
            "duration_s": duration,
            "summary": None,
        }
        meta["done_event"].set()

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# WebSocket: Twilio audio → Deepgram live STT
# ---------------------------------------------------------------------------

@router.websocket("/ws/audio/{call_sid}")
async def audio_stream(ws: WebSocket, call_sid: str):
    await ws.accept()
    logger.info("Voice agent: audio stream open SID=%s", call_sid)

    dg_url = (
        "wss://api.deepgram.com/v1/listen"
        "?model=nova-2&language=en"
        "&smart_format=true"
        "&punctuate=true"
        "&diarize=true"
        "&utterance_end_ms=1500"
        "&interim_results=true"
        "&endpointing=300"
        "&encoding=mulaw&sample_rate=8000"
        "&channels=1"
    )

    try:
        async with websockets.connect(
            dg_url,
            additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
        ) as dg_ws:

            async def recv_from_twilio():
                async for message in ws.iter_text():
                    data = json.loads(message)
                    event = data.get("event")
                    if event == "media":
                        raw_audio = base64.b64decode(data["media"]["payload"])
                        await dg_ws.send(raw_audio)
                    elif event == "stop":
                        await dg_ws.close()
                        break

            async def recv_from_deepgram():
                async for msg in dg_ws:
                    result = json.loads(msg)
                    if result.get("type") != "Results":
                        continue
                    if not result.get("is_final", True):
                        continue

                    alts = result.get("channel", {}).get("alternatives", [])
                    if not alts:
                        continue
                    text = alts[0].get("transcript", "").strip()
                    if not text:
                        continue

                    words = alts[0].get("words", [])
                    speaker = f"Speaker {words[0].get('speaker', 0)}" if words else "Speaker 0"
                    ts = datetime.now(timezone.utc)

                    if call_sid in _calls:
                        _calls[call_sid]["transcript"].append({
                            "speaker": speaker, "text": text, "ts": ts.isoformat(),
                        })

                    await _db_insert_line(call_sid, speaker, text, ts)
                    logger.info("  [%s] %s: %s", ts.isoformat(timespec="seconds"), speaker, text)

            await asyncio.gather(recv_from_twilio(), recv_from_deepgram())

    except Exception as exc:
        logger.warning("Voice agent: audio stream error SID=%s: %s", call_sid, exc)

    logger.info("Voice agent: audio stream closed SID=%s", call_sid)

    # Stream done — safe to summarise now.
    if call_sid in _calls:
        await asyncio.sleep(1)  # small buffer for trailing Deepgram results
        await _post_process(call_sid)


# ---------------------------------------------------------------------------
# Post-call: summarise with Groq, store, signal completion
# ---------------------------------------------------------------------------

async def _post_process(call_sid: str) -> None:
    meta = _calls.get(call_sid, {})
    transcript = meta.get("transcript", [])

    logger.info("Voice agent: post-processing SID=%s (%d turns)", call_sid, len(transcript))

    readable = "\n".join(
        f"[{e['ts']}] {e['speaker']}: {e['text']}" for e in transcript
    ) or "(no transcript — call not answered or too short)"

    parsed, raw = await _summarise_with_groq(
        transcript=readable,
        mission=meta.get("mission", "General outbound call"),
        to=meta.get("to", ""),
        duration=str(meta.get("duration", "0")),
    )

    await _db_insert_summary(call_sid, parsed, raw)

    meta["result"] = {
        "call_sid": call_sid,
        "status": meta.get("status", "completed"),
        "duration_s": meta.get("duration", 0),
        "summary": parsed,
    }
    meta["done_event"].set()

    logger.info("Voice agent: summary stored for SID=%s — outcome=%r", call_sid, parsed.get("outcome"))


async def _summarise_with_groq(transcript: str, mission: str, to: str, duration: str) -> tuple[dict, str]:
    prompt = f"""You are analysing a transcript from an outbound business call.

Call metadata:
- Mission: {mission}
- Called: {to}
- Duration: {duration}s

Transcript:
{transcript}

Respond ONLY with a valid JSON object — no markdown, no preamble — with exactly these keys:
{{
  "outcome": "1-sentence outcome of the call",
  "key_points": ["point 1", "point 2"],
  "action_items": ["action 1", "action 2"],
  "sentiment": "Positive | Neutral | Negative — one-line reason",
  "notable_quotes": ["quote 1", "quote 2"]
}}

If the call was not answered or transcript is empty, set outcome accordingly and leave other lists empty."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openai/gpt-oss-20b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 600,
                },
            )
            r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.error("Voice agent: Groq summarisation failed: %s", exc)
        return {
            "outcome": "Summary unavailable (Groq error)",
            "key_points": [], "action_items": [], "sentiment": "Unknown", "notable_quotes": [],
        }, ""

    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        parsed = {
            "outcome": raw, "key_points": [], "action_items": [],
            "sentiment": "Unknown", "notable_quotes": [],
        }

    return parsed, raw

# ---------------------------------------------------------------------------
# Call history API — view transcripts and summaries
# ---------------------------------------------------------------------------

@router.get("/api/calls")
async def list_calls(limit: int = 50):
    """List recent outbound calls with status and outcome."""
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT c.call_sid, c.partner_name, c.to_number, c.status,
                       c.duration_s, c.started_at, c.ended_at,
                       s.outcome, s.sentiment
                FROM outreach_calls c
                LEFT JOIN outreach_call_summaries s ON s.call_sid = c.call_sid
                ORDER BY c.created_at DESC
                LIMIT $1
            """, limit)
        return {"calls": [dict(r) for r in rows]}
    except Exception as exc:
        return {"calls": [], "error": str(exc)}


@router.get("/api/calls/{call_sid}")
async def get_call_detail(call_sid: str):
    """Get full transcript and AI summary for a single call."""
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            call = await conn.fetchrow(
                "SELECT * FROM outreach_calls WHERE call_sid = $1", call_sid
            )
            if not call:
                return {"error": "Call not found"}

            lines = await conn.fetch("""
                SELECT speaker, line_text, spoken_at
                FROM outreach_transcript_lines
                WHERE call_sid = $1
                ORDER BY id
            """, call_sid)

            summary = await conn.fetchrow(
                "SELECT * FROM outreach_call_summaries WHERE call_sid = $1", call_sid
            )

        import json as _json
        return {
            "call": dict(call),
            "transcript": [dict(l) for l in lines],
            "summary": {
                "outcome":        summary["outcome"]        if summary else None,
                "sentiment":      summary["sentiment"]      if summary else None,
                "key_points":     _json.loads(summary["key_points"]     or "[]") if summary else [],
                "action_items":   _json.loads(summary["action_items"]   or "[]") if summary else [],
                "notable_quotes": _json.loads(summary["notable_quotes"] or "[]") if summary else [],
                "raw":            summary["raw_summary"]    if summary else None,
            } if summary else None,
        }
    except Exception as exc:
        return {"error": str(exc)}