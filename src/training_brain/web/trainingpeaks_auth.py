"""TrainingPeaks calendar config helpers for the web UI.

TP isn't OAuth — it's a personal iCal URL with an embedded token. "Auth" here
just means: the URL is set in .env and the feed actually returns a parseable
calendar. The probe doubles as a smoke test for new URLs.
"""

from __future__ import annotations

import re

import httpx
from icalendar import Calendar

from training_brain.web.env_writer import read_keys, write_keys


def status() -> dict:
    """Report whether TP_ICAL_URL is set and the feed is reachable."""
    url = read_keys(["TP_ICAL_URL"])["TP_ICAL_URL"]
    if not url:
        return {"configured": False, "feed": None, "url_masked": None}
    return {
        "configured": True,
        "url_masked": _mask(url),
        "feed": _probe(url),
    }


def save_url(url: str) -> dict:
    """Persist a new TP iCal URL to .env, normalizing webcal:// → https://."""
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("URL is required")
    cleaned = re.sub(r"^webcal://", "https://", cleaned)
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError("URL must start with http://, https://, or webcal://")
    write_keys({"TP_ICAL_URL": cleaned})
    return status()


def _probe(url: str) -> dict:
    """Fetch the feed and count VEVENTs. Returns {ok, event_count?, reason?}."""
    fetch_url = re.sub(r"^webcal://", "https://", url)
    try:
        resp = httpx.get(fetch_url, timeout=15.0, follow_redirects=True)
    except httpx.HTTPError as e:
        return {"ok": False, "reason": f"network: {e}"}
    if resp.status_code != 200:
        return {"ok": False, "reason": f"http {resp.status_code}"}
    try:
        cal = Calendar.from_ical(resp.text)
    except Exception as e:
        return {"ok": False, "reason": f"invalid iCal: {e}"}
    count = sum(1 for _ in cal.walk("VEVENT"))
    return {"ok": True, "event_count": count}


def _mask(url: str) -> str:
    """Keep host and the last 4 chars of the token; redact the rest."""
    m = re.match(r"^(https?|webcal)://([^/]+)/(.*)$", url)
    if not m:
        return "•••"
    scheme, host, path = m.groups()
    if len(path) <= 4:
        return f"{scheme}://{host}/{path}"
    return f"{scheme}://{host}/…{path[-6:]}"
