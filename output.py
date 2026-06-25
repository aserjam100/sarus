"""Render the triage verdict as a markdown briefing and write it to disk.

Takes the parsed verdict from triage.py, renders it as markdown (summary line,
then category sections ordered URGENT -> NEEDS_REPLY -> FYI -> NOISE), writes it
to briefings/YYYY-MM-DD.md, prints it to the terminal, and optionally fires a
macOS notification with the message + urgent counts.
"""

import shlex
import shutil
import subprocess
from datetime import date
from pathlib import Path

# alerter auto-closes the banner after this many seconds (it blocks until the
# banner is clicked or times out, so this keeps unattended/scheduled runs moving).
_ALERTER_TIMEOUT = 10

_BRIEFINGS_DIR = Path("briefings")

# Sections in priority order, with the heading shown for each category.
_SECTION_ORDER: list[tuple[str, str]] = [
    ("URGENT", "Urgent"),
    ("NEEDS_REPLY", "Needs reply"),
    ("FYI", "FYI"),
    ("NOISE", "Noise"),
]


def render_markdown(verdict: dict) -> str:
    """Render the verdict dict as a markdown briefing string."""
    today = date.today().isoformat()
    emails = verdict.get("emails", [])

    lines = [f"# Sarus — {today}", ""]
    lines.append(verdict.get("overall_summary", "(no summary)"))
    lines.append("")

    if not emails:
        lines.append("_No mail in the lookback window._")
        return "\n".join(lines) + "\n"

    by_category = _group_by_category(emails)
    for category, heading in _SECTION_ORDER:
        items = by_category.get(category, [])
        if not items:
            continue
        lines.append(f"## {heading} ({len(items)})")
        lines.append("")
        for item in items:
            sender = item.get("sender", "unknown")
            subject = _truncate(item.get("subject", "(no subject)"))
            reason = item.get("reason", "")
            lines.append(f"- **{sender}** — {subject} · _{reason}_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _truncate(text: str, limit: int = 60) -> str:
    """Trim a long subject to keep briefing lines scannable."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _group_by_category(emails: list[dict]) -> dict[str, list[dict]]:
    """Bucket emails by their category string."""
    buckets: dict[str, list[dict]] = {}
    for item in emails:
        buckets.setdefault(item.get("category", "NOISE"), []).append(item)
    return buckets


def _briefing_path() -> Path:
    """Path to today's briefing file (shared by write + the click-to-open action)."""
    return _BRIEFINGS_DIR / f"{date.today().isoformat()}.md"


def write_briefing(markdown: str) -> Path:
    """Write the briefing to briefings/YYYY-MM-DD.md and return its path."""
    _BRIEFINGS_DIR.mkdir(exist_ok=True)
    path = _briefing_path()
    path.write_text(markdown, encoding="utf-8")
    return path


def _applescript_str(s: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _open_in_terminal(path: Path) -> None:
    """Open the briefing in a new Terminal window via `less` (best-effort)."""
    if not path.exists():
        return
    shell_cmd = f"less {shlex.quote(str(path.resolve()))}"
    do_script = f"tell application \"Terminal\" to do script {_applescript_str(shell_cmd)}"
    activate = 'tell application "Terminal" to activate'
    try:
        subprocess.run(["osascript", "-e", do_script, "-e", activate],
                       check=False, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass  # opening is a convenience — never let it break the pipeline


def notify(verdict: dict, briefing_path: Path | None = None) -> None:
    """Fire a macOS notification with total + urgent counts (best-effort).

    Prefers `alerter` (works on current macOS, including 26, via the modern
    notification API; shows + plays a sound and auto-closes after a timeout).
    Because alerter blocks and reports the click action, clicking the banner
    opens the briefing in a new Terminal window via `less`. Falls back to
    `osascript` (no click handling — its notification is owned by Script Editor,
    so it shows that icon and clicking opens Script Editor; cosmetic). Silently
    does nothing if neither is available (e.g. not macOS). The banner is only a
    "new briefing" ping — the briefing itself is the terminal output and
    briefings/YYYY-MM-DD.md.
    """
    emails = verdict.get("emails", [])
    total = len(emails)
    urgent = sum(1 for e in emails if e.get("category") == "URGENT")
    if total == 0:
        return

    if briefing_path is None:
        briefing_path = _briefing_path()

    title = "Sarus briefing"
    body = f"{total} message(s), {urgent} urgent"
    try:
        if shutil.which("alerter"):
            # alerter blocks until clicked or --timeout; give subprocess a little
            # more headroom than the alerter timeout so it's never killed early.
            result = subprocess.run(
                ["alerter", "--title", title, "--message", body,
                 "--timeout", str(_ALERTER_TIMEOUT), "--sound", "default"],
                check=False, timeout=_ALERTER_TIMEOUT + 5,
                capture_output=True, text=True,
            )
            if (result.stdout or "").strip() == "@CONTENTCLICKED":
                _open_in_terminal(briefing_path)
        else:
            script = f'display notification "{body}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass  # notifications are optional — never let them break the pipeline


def emit(verdict: dict) -> Path:
    """Render, print, write, and notify. Returns the briefing path."""
    markdown = render_markdown(verdict)
    print(markdown)
    path = write_briefing(markdown)
    print(f"Wrote {path}")
    notify(verdict, path)
    return path


if __name__ == "__main__":
    # Smoke check with a fixed sample verdict — no auth or API call needed.
    _sample = {
        "overall_summary": "Two real items need attention; the rest is noise.",
        "emails": [
            {
                "sender": "boss@example.com",
                "subject": "Budget sign-off needed today",
                "category": "URGENT",
                "reason": "explicit same-day deadline",
            },
            {
                "sender": "teammate@example.com",
                "subject": "Re: design review",
                "category": "NEEDS_REPLY",
                "reason": "asks for your feedback",
            },
            {
                "sender": "newsletter@example.com",
                "subject": "Weekly digest",
                "category": "NOISE",
                "reason": "automated newsletter",
            },
        ],
    }
    emit(_sample)
