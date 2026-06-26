"""Meeting-prep poll: brief any meeting starting soon, once each.

Runs every ~30 min (its own launchd agent). For each calendar event starting
within the next PREP_WINDOW_MINUTES that hasn't been prepped today, it collects
the event's own data (no transcripts), asks the LLM for a structured prep brief,
and renders + notifies through the shared output pipeline. State lives in
prepped.json so one meeting yields exactly one brief. If nothing matches, it
exits silently — no empty notifications.

Read-only: uses the Calendars.Read scope; never modifies the calendar.
Run standalone:  python prep.py
"""

import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from auth import get_token
from config import PREP_WINDOW_MINUTES
from output import notify_and_open, render_brief
from provider import summarize

_CALENDAR_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendarView"

# Everything we need comes from the event object itself — no extra calls (except
# an optional, guarded attachment-name lookup). No transcripts.
_SELECT_FIELDS = (
    "id,subject,bodyPreview,body,attendees,organizer,location,onlineMeeting,"
    "isOnlineMeeting,importance,categories,recurrence,webLink,responseStatus,"
    "start,end,hasAttachments"
)

# A meeting that already started up to this long ago is still worth prepping if
# the poll fires right at start time (clock skew / poll cadence grace).
_START_GRACE = timedelta(minutes=2)

_STATE_PATH = Path("prepped.json")

_PREP_INSTRUCTIONS = (
    "You are a meeting-prep assistant. Given the details of ONE upcoming meeting, "
    "write a concise, scannable prep brief in GitHub-flavored markdown so the "
    "attendee can walk in ready. Do not invent facts not present in the details. "
    "Do not output code fences around the whole document.\n\n"
    "Use these sections (omit one only if there is genuinely nothing to say):\n"
    "  ## What & when — one line: subject, start time, duration if known, online/in-person.\n"
    "  ## Who — organizer, and attendees with their role (required/optional) and "
    "response (accepted/declined/tentative/no response). Call out notable declines.\n"
    "  ## Agenda — bullet the agenda/purpose drawn from the meeting body.\n"
    "  ## Join — the join link or location.\n"
    "  ## What to prepare — 2–5 concrete prep actions tailored to this meeting.\n"
    "Keep it tight. No preamble, no sign-off."
)


# --- Time helpers ---------------------------------------------------------------

def _parse_graph_utc(dt_str: str) -> datetime:
    """Parse a Graph dateTime (UTC, e.g. '2026-06-26T15:00:00.0000000') to aware UTC."""
    s = dt_str.rstrip("Z")
    if "." in s:
        head, frac = s.split(".", 1)
        s = f"{head}.{frac[:6]}"  # fromisoformat accepts at most 6 fractional digits
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _graph_param_time(dt: datetime) -> str:
    """Format an aware datetime as a naive UTC string for the calendarView params."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# --- State (dedup) --------------------------------------------------------------

def _today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load_prepped() -> set[str]:
    """Return the set of event ids already prepped today."""
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    return set(data.get(_today_key(), []))


def _mark_prepped(event_id: str) -> None:
    """Record an event id as prepped today. Prunes other days to keep the file tiny."""
    today = _today_key()
    prepped = _load_prepped()
    prepped.add(event_id)
    _STATE_PATH.write_text(
        json.dumps({today: sorted(prepped)}, indent=2), encoding="utf-8"
    )


# --- Fetch + select -------------------------------------------------------------

def fetch_upcoming_events() -> list[dict]:
    """Fetch events whose window overlaps [now-grace, now+PREP_WINDOW_MINUTES]."""
    now = datetime.now(timezone.utc)
    lower = now - _START_GRACE
    upper = now + timedelta(minutes=PREP_WINDOW_MINUTES)

    token = get_token(allow_interactive=False)  # unattended: never prompt
    resp = requests.get(
        _CALENDAR_VIEW_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Prefer": 'outlook.timezone="UTC"',
        },
        params={
            "startDateTime": _graph_param_time(lower),
            "endDateTime": _graph_param_time(upper),
            "$select": _SELECT_FIELDS,
            "$orderby": "start/dateTime",
            "$top": "25",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("value", [])


def select_meetings_to_prep(events: list[dict]) -> list[dict]:
    """Keep events that START within the window and haven't been prepped today."""
    now = datetime.now(timezone.utc)
    lower = now - _START_GRACE
    upper = now + timedelta(minutes=PREP_WINDOW_MINUTES)
    prepped = _load_prepped()

    selected = []
    for ev in events:
        event_id = ev.get("id")
        if not event_id or event_id in prepped:
            continue
        start_raw = (ev.get("start") or {}).get("dateTime")
        if not start_raw:
            continue
        start = _parse_graph_utc(start_raw)
        if lower <= start <= upper:
            selected.append(ev)
    return selected


# --- Collect event data ---------------------------------------------------------

def _strip_html(text: str) -> str:
    """Crudely convert an HTML event body to readable plain text."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _agenda_text(event: dict) -> str:
    """Best plain-text agenda: full body if available, else the preview."""
    body = event.get("body") or {}
    content = (body.get("content") or "").strip()
    if content:
        if (body.get("contentType") or "").lower() == "html":
            content = _strip_html(content)
        if content:
            return content[:4000]
    return (event.get("bodyPreview") or "").strip()[:4000]


def _attachment_names(event_id: str) -> list[str]:
    """Best-effort list of invite attachment names (no download/convert in v1)."""
    try:
        token = get_token(allow_interactive=False)
        resp = requests.get(
            f"https://graph.microsoft.com/v1.0/me/events/{event_id}/attachments",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "name,size"},
            timeout=30,
        )
        resp.raise_for_status()
        return [a.get("name", "(unnamed)") for a in resp.json().get("value", [])]
    except (requests.RequestException, ValueError):
        return []  # attachments are a nicety — never let them break the brief


def _format_attendees(attendees: list[dict]) -> str:
    lines = []
    for a in attendees or []:
        ea = a.get("emailAddress", {})
        who = ea.get("name") or ea.get("address") or "unknown"
        role = a.get("type", "required")
        status = (a.get("status") or {}).get("response", "none")
        lines.append(f"  - {who} ({role}, {status})")
    return "\n".join(lines) if lines else "  (none listed)"


def _event_facts(event: dict, attachment_names: list[str]) -> str:
    """Render the collected event data into a compact text block for the LLM."""
    subject = event.get("subject") or "(no subject)"
    start = (event.get("start") or {}).get("dateTime", "?")
    end = (event.get("end") or {}).get("dateTime", "?")
    organizer = ((event.get("organizer") or {}).get("emailAddress") or {})
    organizer_str = organizer.get("name") or organizer.get("address") or "unknown"

    online = event.get("isOnlineMeeting", False)
    join_url = ((event.get("onlineMeeting") or {}).get("joinUrl")) or ""
    location = ((event.get("location") or {}).get("displayName")) or ""
    my_status = (event.get("responseStatus") or {}).get("response", "none")
    importance = event.get("importance", "normal")
    categories = ", ".join(event.get("categories") or []) or "none"
    recurring = "yes" if event.get("recurrence") else "no"

    parts = [
        f"Subject: {subject}",
        f"Start (UTC): {start}",
        f"End (UTC): {end}",
        f"Organizer: {organizer_str}",
        f"My response: {my_status}",
        f"Importance: {importance}",
        f"Categories: {categories}",
        f"Recurring: {recurring}",
        f"Online meeting: {'yes' if online else 'no'}",
        f"Join URL: {join_url or '(none)'}",
        f"Location: {location or '(none)'}",
        f"Web link: {event.get('webLink', '(none)')}",
        "Attendees:",
        _format_attendees(event.get("attendees", [])),
    ]
    if attachment_names:
        parts.append("Attached files (names only): " + ", ".join(attachment_names))
    parts.append("")
    parts.append("Meeting body / agenda:")
    parts.append(_agenda_text(event) or "(empty)")
    return "\n".join(parts)


# --- Brief one meeting ----------------------------------------------------------

def prep_meeting(event: dict) -> Path:
    """Build, render, and notify a prep brief for one event. Returns the HTML path."""
    event_id = event["id"]
    subject = event.get("subject") or "Meeting"

    attachment_names = _attachment_names(event_id) if event.get("hasAttachments") else []
    facts = _event_facts(event, attachment_names)
    brief_md = summarize(f"{_PREP_INSTRUCTIONS}\n\nMeeting details:\n\n{facts}").strip()

    # Filename starts with "meeting"; the hash suffix keeps two same-named
    # meetings in a day from colliding.
    suffix = hashlib.sha1(event_id.encode("utf-8")).hexdigest()[:8]
    path = render_brief(brief_md, title=f"meeting {subject} {suffix}", kind=subject)
    notify_and_open(path, "Meeting prep", subject)
    return path


def run_prep() -> None:
    """Poll the calendar and brief each new upcoming meeting. Silent when none."""
    events = fetch_upcoming_events()
    to_prep = select_meetings_to_prep(events)
    if not to_prep:
        print(f"No meetings starting in the next {PREP_WINDOW_MINUTES} min.")
        return

    for event in to_prep:
        subject = event.get("subject") or "(no subject)"
        try:
            path = prep_meeting(event)
        except Exception as e:  # noqa: BLE001 — one bad meeting must not kill the rest
            print(f"[!] Failed to prep '{subject}': {e}")
            continue
        _mark_prepped(event["id"])  # only after a successful render
        print(f"Prep written: {path}  ({subject})")


if __name__ == "__main__":
    run_prep()
