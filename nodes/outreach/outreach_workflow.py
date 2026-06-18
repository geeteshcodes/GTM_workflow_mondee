"""
nodes/outreach/outreach_workflow.py
-------------------------------------
Single-partner, channel-aware outreach workflow.

Channels live today:
    voice     — Twilio outbound call via voice_agent.engine.place_call()
    whatsapp  — Twilio WhatsApp sandbox / Business API
    email     — Gmail SMTP via app password
    linkedin  — Unipile API DM

Channel: "instagram" is accepted but returns not_implemented until wired.

Called from:
    backend/api/outreach.py  → manual single-partner launch from UI
    nodes/outreach/outreach_node.py → batch pipeline (voice only)
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from twilio.rest import Client as TwilioClient

from voice_agent.engine import place_call

logger = logging.getLogger(__name__)

# ── Env vars ───────────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID    = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN     = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM  = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

GMAIL_USER            = os.getenv("EMAIL_ADDRESS", "")
GMAIL_PASSWORD        = os.getenv("EMAIL_PASSWORD", "")
SMTP_SERVER           = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT             = int(os.getenv("SMTP_PORT", "587"))
EMAIL_FROM            = os.getenv("EMAIL_FROM", GMAIL_USER)

UNIPILE_API_KEY       = os.getenv("UNIPILE_API_KEY", "")
UNIPILE_DSN           = os.getenv("UNIPILE_DSN", "")
UNIPILE_ACCOUNT_ID    = os.getenv("UNIPILE_ACCOUNT_ID", "")


# ── WhatsApp ───────────────────────────────────────────────────────────────────

async def _run_whatsapp_channel(partner: dict, custom_message: str = "") -> dict:
    """Send a WhatsApp message via Twilio sandbox."""
    phone = (partner.get("phone_number") or "").strip()
    if not phone:
        return {"status": "skipped", "note": "No phone number on file"}

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return {"status": "error", "note": "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set"}

    name = partner.get("partner_name", "there")
    body = custom_message.strip() or (
        f"Hi, this is the Aarna GTM team at Mondee reaching out to {name}. "
        f"We'd love to explore a partnership opportunity with you on our UAE experience marketplace. "
        f"Could we connect for a quick 10-minute call? Reply here or visit aarna.ae for more info."
    )

    # Normalise phone to whatsapp: format
    to_number = phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"

    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=TWILIO_WHATSAPP_FROM,
            to=to_number,
        )
        logger.info("WhatsApp: sent to %s — SID=%s", phone, message.sid)
        return {
            "status":  "sent",
            "sid":     message.sid,
            "to":      phone,
            "channel": "whatsapp",
        }
    except Exception as exc:
        logger.error("WhatsApp: failed for %r — %s", name, exc)
        return {"status": "error", "note": str(exc)}


# ── Email ──────────────────────────────────────────────────────────────────────

async def _run_email_channel(partner: dict, custom_message: str = "") -> dict:
    """Send an outreach email via Gmail SMTP."""
    email = (partner.get("email_id") or "").strip()
    if not email:
        return {"status": "skipped", "note": "No email address on file"}

    if not GMAIL_USER or not GMAIL_PASSWORD:
        return {"status": "error", "note": "EMAIL_ADDRESS / EMAIL_PASSWORD not set"}

    name    = partner.get("partner_name", "there")
    contact = partner.get("contact_name", "")
    greeting = f"Hi {contact}" if contact else "Hi"

    subject = f"Partnership opportunity — List {name} on Aarna (UAE Experience Marketplace)"

    if custom_message.strip():
        body_text = custom_message.strip()
    else:
        body_text = f"""{greeting},

I'm reaching out from the Aarna GTM team at Mondee.

Aarna is the UAE's experience marketplace — connecting activity and experience operators like {name} with corporate travellers, MICE delegates, and Mondee's global B2B agent network of 65,000+ travel agents.

Listing is free. We work on commission only when a booking is confirmed.

Would you have 10 minutes for a quick call this week to explore if there's a fit?

Best regards,
Aarna Partnerships Team
Mondee Group UAE
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = email
    msg.attach(MIMEText(body_text, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, email, msg.as_string())

        logger.info("Email: sent to %s for partner %r", email, name)
        return {
            "status":  "sent",
            "to":      email,
            "subject": subject,
            "channel": "email",
        }
    except Exception as exc:
        logger.error("Email: failed for %r — %s", name, exc)
        return {"status": "error", "note": str(exc)}


# ── LinkedIn ───────────────────────────────────────────────────────────────────

async def _run_linkedin_channel(partner: dict, custom_message: str = "") -> dict:
    """Send a LinkedIn DM via Unipile API."""
    linkedin_url = (partner.get("linkedin_profile") or "").strip()
    if not linkedin_url:
        return {"status": "skipped", "note": "No LinkedIn profile on file"}

    if not UNIPILE_API_KEY or not UNIPILE_DSN or not UNIPILE_ACCOUNT_ID:
        return {"status": "error", "note": "UNIPILE_API_KEY / UNIPILE_DSN / UNIPILE_ACCOUNT_ID not set"}

    name    = partner.get("partner_name", "there")
    contact = partner.get("contact_name", "")
    greeting = f"Hi {contact}" if contact else "Hi"

    message_text = custom_message.strip() or (
        f"{greeting}, I came across {name} and believe you'd be a strong fit for Aarna — "
        f"Mondee's UAE experience marketplace. We connect operators with corporate travellers "
        f"and a global B2B agent network. Listing is free, commission-only. "
        f"Would you be open to a quick 10-minute call?"
    )

    # Step 1 — Resolve LinkedIn profile URL to Unipile provider_id
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Search for the LinkedIn profile via Unipile
            search_resp = await client.get(
                f"https://{UNIPILE_DSN}/api/v1/linkedin/profile",
                headers={
                    "X-API-KEY": UNIPILE_API_KEY,
                    "accept":    "application/json",
                },
                params={
                    "account_id": UNIPILE_ACCOUNT_ID,
                    "linkedin_url": linkedin_url,
                },
            )

            if search_resp.status_code != 200:
                logger.warning(
                    "LinkedIn: profile lookup failed %d for %r",
                    search_resp.status_code, name,
                )
                return {
                    "status": "error",
                    "note": f"Unipile profile lookup returned {search_resp.status_code}",
                }

            profile_data = search_resp.json()
            provider_id  = profile_data.get("provider_id") or profile_data.get("id")

            if not provider_id:
                return {"status": "error", "note": "Could not resolve LinkedIn provider_id"}

            # Step 2 — Send the DM
            dm_resp = await client.post(
                f"https://{UNIPILE_DSN}/api/v1/chats",
                headers={
                    "X-API-KEY":    UNIPILE_API_KEY,
                    "accept":       "application/json",
                    "content-type": "application/json",
                },
                json={
                    "account_id":         UNIPILE_ACCOUNT_ID,
                    "attendees_ids":      [provider_id],
                    "text":               message_text,
                },
            )

            if dm_resp.status_code in (200, 201):
                chat_id = dm_resp.json().get("id") or dm_resp.json().get("chat_id")
                logger.info("LinkedIn DM: sent to %s for %r — chat_id=%s", linkedin_url, name, chat_id)
                return {
                    "status":   "sent",
                    "to":       linkedin_url,
                    "chat_id":  chat_id,
                    "channel":  "linkedin",
                }
            else:
                logger.error(
                    "LinkedIn DM: send failed %d for %r — %s",
                    dm_resp.status_code, name, dm_resp.text,
                )
                return {
                    "status": "error",
                    "note":   f"Unipile DM returned {dm_resp.status_code}: {dm_resp.text[:200]}",
                }

    except Exception as exc:
        logger.error("LinkedIn: unexpected error for %r — %s", name, exc)
        return {"status": "error", "note": str(exc)}


# ── Voice ──────────────────────────────────────────────────────────────────────

async def _run_voice_channel(partner: dict, custom_message: str = "") -> dict:
    """Place an outbound voice call via Twilio + Deepgram + Groq."""
    phone = (partner.get("phone_number") or "").strip()
    if not phone:
        return {"status": "skipped", "note": "No phone number on file"}

    name   = partner.get("partner_name", "this business")
    script = custom_message.strip() or (
        f"Hello, this is an automated call from the Aarna GTM team at Mondee, "
        f"reaching out to {name}. We'd love to explore a partnership opportunity "
        f"with you. Could you tell me a bit about how you currently manage bookings?"
    )

    result = await place_call(
        to=phone,
        script=script,
        mission=f"Manual outreach launch — {partner.get('category', 'General')}",
        partner_id=partner.get("id"),
        partner_name=name,
        timeout_s=180,
    )

    return {
        "status":    result.get("status"),
        "call_sid":  result.get("call_sid"),
        "duration_s": result.get("duration_s", 0),
        "summary":   result.get("summary"),
        "channel":   "voice",
    }


# ── Not implemented ────────────────────────────────────────────────────────────

async def _run_unimplemented_channel(channel: str) -> dict:
    return {
        "status": "not_implemented",
        "note":   f"{channel} outreach is not yet wired.",
    }


# ── Main dispatcher ────────────────────────────────────────────────────────────

async def run_outreach_workflow(
    partner: dict,
    channels: list,
    custom_message: str = "",
) -> dict:
    """
    Run outreach across the requested channels for a single partner.

    Parameters
    ----------
    partner : dict
        Partner record — must include partner_name; phone_number / email_id /
        linkedin_profile used per channel.
    channels : list[str]
        Any combination of: "voice", "whatsapp", "email", "linkedin"
    custom_message : str
        Optional override for all channel messages/scripts.

    Returns
    -------
    dict
        {
            "lead_name": str,
            "results":   [{"channel": str, "result": {...}}, ...]
        }
    """
    name = partner.get("partner_name", "Unknown")
    logger.info("Outreach workflow: %r → channels=%s", name, channels)

    _CHANNEL_MAP = {
        "whatsapp": _run_whatsapp_channel,
        "email":    _run_email_channel,
        "linkedin": _run_linkedin_channel,
        "voice":    _run_voice_channel,
    }

    results = []
    for channel in channels:
        handler = _CHANNEL_MAP.get(channel)
        if handler:
            channel_result = await handler(partner, custom_message)
        else:
            channel_result = await _run_unimplemented_channel(channel)

        logger.info(
            "Outreach: %r channel=%s → status=%s",
            name, channel, channel_result.get("status"),
        )
        results.append({"channel": channel, "result": channel_result})

    return {"lead_name": name, "results": results}