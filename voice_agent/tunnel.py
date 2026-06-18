"""
voice_agent/tunnel.py
-----------------------
Starts ONE ngrok tunnel for the entire backend at startup (not per call).
Twilio webhooks (call connect, status, audio stream) hit this public URL,
which forwards to your local FastAPI server on port 8000.

Called once from backend/main.py's lifespan startup hook.
"""

import os
import logging

from pyngrok import ngrok

from voice_agent.engine import set_public_host

logger = logging.getLogger(__name__)

NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

_tunnel = None


def start_tunnel() -> str | None:
    """
    Start the ngrok tunnel for the backend port.
    Returns the public host (no scheme), or None if NGROK_AUTH_TOKEN is missing.
    """
    global _tunnel

    if not NGROK_AUTH_TOKEN:
        logger.warning(
            "NGROK_AUTH_TOKEN not set — voice agent outreach calls will not work "
            "(Twilio cannot reach a local server without a public tunnel)."
        )
        return None

    try:
        ngrok.set_auth_token(NGROK_AUTH_TOKEN)
        _tunnel = ngrok.connect(BACKEND_PORT, bind_tls=True)
        public_host = _tunnel.public_url.replace("https://", "")
        set_public_host(public_host)
        logger.info("Voice agent: ngrok tunnel live at https://%s -> localhost:%d", public_host, BACKEND_PORT)
        return public_host
    except Exception as exc:
        logger.error("Voice agent: failed to start ngrok tunnel: %s", exc)
        return None


def stop_tunnel() -> None:
    global _tunnel
    if _tunnel is not None:
        try:
            ngrok.disconnect(_tunnel.public_url)
        except Exception:
            pass
        _tunnel = None