"""Fetch recent mail from Microsoft Graph.

Pulls messages received in the last LOOKBACK_HOURS using the Mail.Read scope and
returns them as a list of plain dicts for the triage step to consume.
"""

from datetime import datetime, timedelta, timezone

import requests

from auth import get_token
from config import LOOKBACK_HOURS

_GRAPH_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/messages"

_SELECT_FIELDS = "subject,from,receivedDateTime,bodyPreview,isRead,hasAttachments"


def fetch_recent_mail() -> list[dict]:
    """Return messages received within the last LOOKBACK_HOURS, newest first.

    Each dict has the Graph fields in _SELECT_FIELDS. Returns an empty list when
    no mail arrived in the window.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    # Graph wants ISO-8601 in UTC, e.g. 2026-06-25T05:40:46Z
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    token = get_token()
    resp = requests.get(
        _GRAPH_MESSAGES_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={
            "$filter": f"receivedDateTime ge {since_iso}",
            "$select": _SELECT_FIELDS,
            "$top": "50",
            "$orderby": "receivedDateTime desc",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("value", [])


def _sender_address(message: dict) -> str:
    """Pull the sender email address out of a Graph message, or 'unknown'."""
    return (message.get("from") or {}).get("emailAddress", {}).get("address", "unknown")


if __name__ == "__main__":
    mail = fetch_recent_mail()
    if not mail:
        print(f"No mail in the last {LOOKBACK_HOURS} hours.")
    else:
        print(f"{len(mail)} message(s) in the last {LOOKBACK_HOURS} hours:\n")
        for m in mail:
            print(f"  {_sender_address(m)} — {m.get('subject')}")
