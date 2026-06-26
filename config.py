"""Configuration for Sarus: loads .env and exposes constants used across modules."""

import os

from dotenv import load_dotenv

load_dotenv()

# How far back to look for mail, in hours.
LOOKBACK_HOURS: int = int(os.getenv("LOOKBACK_HOURS", "18"))

# LLM provider for triage + meeting prep. Loaded from .env so it's swappable
# without code changes. Only "anthropic" is implemented today; the value is
# routed through provider.summarize() so other providers can slot in later.
PROVIDER: str = os.getenv("PROVIDER", "anthropic")

# Model used for triage + prep. Loaded from .env so it's swappable without code
# changes. Default claude-sonnet-4-6 (strong summaries); set MODEL=claude-haiku-4-5
# in .env for a cheaper/faster run.
MODEL: str = os.getenv("MODEL", "claude-sonnet-4-6")

# Meeting-prep poll window, in minutes. The poll briefs any meeting starting
# within the next PREP_WINDOW_MINUTES (a window, not a point — see prep.py).
PREP_WINDOW_MINUTES: int = int(os.getenv("PREP_WINDOW_MINUTES", "35"))

# Microsoft Entra public-client app settings (loaded from .env; never hardcoded).
MS_CLIENT_ID: str | None = os.getenv("MS_CLIENT_ID")
MS_TENANT_AUTHORITY: str | None = os.getenv("MS_TENANT_AUTHORITY")

# Microsoft Graph delegated scopes. READ-ONLY ONLY — never add a scope that can
# send, delete, move, or modify anything (no Mail.Send, Mail.ReadWrite, etc.).
# Calendars.Read + Files.Read.All are owner-approved read-only additions for the
# meeting-prep feature (see CLAUDE.md guardrail #1).
GRAPH_SCOPES: list[str] = ["Mail.Read", "Calendars.Read", "Files.Read.All"]
