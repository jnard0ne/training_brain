"""Shared Supabase + env access for the training_brain package.

The sync job and ingesters all reach Postgres and Storage through `client()`.
The athlete UUID lives in `.env` (seeded once when the project is provisioned),
so all ingestion is single-tenant by default — the schema supports multi-athlete
if that ever changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache

from dotenv import load_dotenv
from supabase import Client, create_client


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_secret_key: str
    athlete_id: str
    garmin_email: str | None
    garmin_password: str | None
    tp_ical_url: str | None
    strava_client_id: str | None
    strava_client_secret: str | None
    strava_refresh_token: str | None


@cache
def settings() -> Settings:
    load_dotenv()
    return Settings(
        supabase_url=_required("SUPABASE_URL"),
        supabase_secret_key=_required("SUPABASE_SECRET_KEY"),
        athlete_id=_required("ATHLETE_ID"),
        garmin_email=os.getenv("GARMIN_EMAIL"),
        garmin_password=os.getenv("GARMIN_PASSWORD"),
        tp_ical_url=os.getenv("TP_ICAL_URL"),
        strava_client_id=os.getenv("STRAVA_CLIENT_ID"),
        strava_client_secret=os.getenv("STRAVA_CLIENT_SECRET"),
        strava_refresh_token=os.getenv("STRAVA_REFRESH_TOKEN"),
    )


@cache
def client() -> Client:
    s = settings()
    return create_client(s.supabase_url, s.supabase_secret_key)


def athlete_id() -> str:
    return settings().athlete_id


def _required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}. See .env.example.")
    return val
