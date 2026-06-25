"""Configuration for Sarus: loads .env and exposes constants used across modules."""

import os

from dotenv import load_dotenv

load_dotenv()

# How far back to look for mail, in hours.
LOOKBACK_HOURS: int = int(os.getenv("LOOKBACK_HOURS", "18"))

# Anthropic model used for triage. Loaded from .env so it's swappable without code
# changes. Default claude-sonnet-4-6 (strong summaries); set MODEL=claude-haiku-4-5
# in .env for a cheaper/faster run.
MODEL: str = os.getenv("MODEL", "claude-sonnet-4-6")

# Microsoft Entra public-client app settings (loaded from .env; never hardcoded).
MS_CLIENT_ID: str | None = os.getenv("MS_CLIENT_ID")
MS_TENANT_AUTHORITY: str | None = os.getenv("MS_TENANT_AUTHORITY")

# Microsoft Graph delegated scope. READ-ONLY — do not add send/modify scopes.
GRAPH_SCOPES: list[str] = ["Mail.Read"]
