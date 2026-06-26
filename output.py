"""Unified output pipeline: render a brief to styled HTML, then notify + open.

Every Sarus output — the mail digest and the meeting-prep brief — flows through
the same two functions so they look like one product:

  render_brief(md_text, title, kind) -> Path     markdown -> self-contained HTML
  notify_and_open(html_path, title, message)     alerter banner -> open in browser

The digest path (render_markdown + emit) turns the triage verdict into markdown,
then hands it to render_brief. There is no markdown-file or full-terminal output
anymore — only the HTML in briefings/ plus a one-line stdout summary for logs.
"""

import html
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from markdown_it import MarkdownIt

# alerter blocks until the banner is clicked or this timeout elapses, then reports
# the action on stdout. 60s per spec; we keep unattended runs moving regardless.
_ALERTER_TIMEOUT = 60

# Briefings live in the user's home dir (~/briefings), not inside the repo — so
# the output is the same wherever Sarus is cloned and never lands in git.
_BRIEFINGS_DIR = Path.home() / "briefings"

# Sections in priority order, with the heading shown for each category.
_SECTION_ORDER: list[tuple[str, str]] = [
    ("URGENT", "Urgent"),
    ("NEEDS_REPLY", "Needs reply"),
    ("FYI", "FYI"),
    ("NOISE", "Noise"),
]

# One shared, self-contained stylesheet so every brief looks identical. System
# font stack, readable measure, lightly styled headings/links/blockquotes/lists.
_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica,
               Arial, sans-serif;
  line-height: 1.55;
  color: #1d1d1f;
  background: #fbfbfd;
  margin: 0;
  padding: 2.5rem 1rem;
}
.sheet {
  max-width: 720px;
  margin: 0 auto;
  background: #fff;
  border: 1px solid #e5e5ea;
  border-radius: 14px;
  padding: 2rem 2.25rem;
}
.brief-header { border-bottom: 1px solid #eee; padding-bottom: 0.75rem; margin-bottom: 1.25rem; }
.brief-kind { font-size: 1.5rem; font-weight: 700; margin: 0; letter-spacing: -0.01em; }
.brief-date { color: #8a8a8e; font-size: 0.9rem; margin-top: 0.15rem; }
h1, h2, h3 { line-height: 1.25; letter-spacing: -0.01em; }
h2 { font-size: 1.15rem; margin-top: 1.75rem; }
h3 { font-size: 1rem; margin-top: 1.25rem; }
a { color: #0b66c3; text-decoration: none; }
a:hover { text-decoration: underline; }
ul { padding-left: 1.25rem; }
li { margin: 0.25rem 0; }
blockquote {
  margin: 1rem 0; padding: 0.5rem 1rem;
  border-left: 3px solid #d2d2d7; color: #515154; background: #f7f7f9;
}
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em; }
hr { border: none; border-top: 1px solid #eee; margin: 1.5rem 0; }
@media (prefers-color-scheme: dark) {
  body { color: #f5f5f7; background: #161617; }
  .sheet { background: #1d1d1f; border-color: #2c2c2e; }
  .brief-header { border-color: #2c2c2e; }
  .brief-date { color: #98989d; }
  a { color: #6cb4ff; }
  blockquote { border-color: #3a3a3c; color: #c7c7cc; background: #242426; }
}
"""

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<main class="sheet">
<header class="brief-header">
<p class="brief-kind">{kind}</p>
<p class="brief-date">{date}</p>
</header>
{body}
</main>
</body>
</html>
"""

# Markdown renderer shared by every brief (independent of textual/rich).
_MD = MarkdownIt("commonmark", {"linkify": True}).enable("linkify")


def render_markdown(verdict: dict) -> str:
    """Render the triage verdict dict as the digest's markdown body.

    No top-level title — render_brief supplies the header (kind + date).
    """
    emails = verdict.get("emails", [])
    lines = [verdict.get("overall_summary", "(no summary)"), ""]

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


def _sanitize_filename(text: str, fallback: str = "brief") -> str:
    """Make a string safe for a filename: drop illegal chars, collapse to kebab-case.

    Shared by both producers (digest + meeting prep) so naming is consistent.
    Strips '/', ':', and other filesystem-illegal characters, lowercases, and
    collapses whitespace/punctuation to single hyphens.
    """
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = text[:60].strip("-")
    return text or fallback


def render_brief(md_text: str, title: str, kind: str) -> Path:
    """Render markdown to a styled, self-contained HTML file in ~/briefings.

    The file is named <sanitized-title>-<date>.html, so callers control the
    leading word (digest briefs start "digest", meeting briefs start "meeting").
    `kind` is the header label + browser-tab title; `title` drives the filename.
    Returns the written path.
    """
    _BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    body_html = _MD.render(md_text)
    document = _HTML_TEMPLATE.format(
        title=html.escape(kind),
        css=_CSS,
        kind=html.escape(kind),
        date=date.today().isoformat(),
        body=body_html,
    )
    path = _BRIEFINGS_DIR / f"{_sanitize_filename(title)}-{date.today().isoformat()}.html"
    path.write_text(document, encoding="utf-8")
    return path


def _applescript_str(s: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify_and_open(html_path: Path, title: str, message: str) -> None:
    """Fire an alerter banner; on click, open the HTML brief in the browser.

    alerter blocks until the banner is clicked or --timeout elapses, then prints
    the action on stdout — on @CONTENTCLICKED we `open` the file in the default
    browser. Falls back to a plain osascript notification (no click handling)
    when alerter is absent. All best-effort: a notification failure never breaks
    the pipeline, and the HTML always remains in briefings/.
    """
    try:
        if shutil.which("alerter"):
            result = subprocess.run(
                ["alerter", "--title", title, "--message", message,
                 "--timeout", str(_ALERTER_TIMEOUT), "--sound", "default"],
                check=False, timeout=_ALERTER_TIMEOUT + 5,
                capture_output=True, text=True,
            )
            if (result.stdout or "").strip() == "@CONTENTCLICKED":
                subprocess.run(["open", str(html_path.resolve())],
                               check=False, timeout=10)
        else:
            script = (f"display notification {_applescript_str(message)} "
                      f"with title {_applescript_str(title)}")
            subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass  # notifications are optional — never let them break the pipeline


def emit(verdict: dict) -> Path:
    """Render the digest to HTML, log one line, and notify. Returns the path."""
    markdown = render_markdown(verdict)
    path = render_brief(markdown, title="digest", kind="Morning digest")
    print(f"Digest written: {path}")

    emails = verdict.get("emails", [])
    total = len(emails)
    urgent = sum(1 for e in emails if e.get("category") == "URGENT")
    if total:
        notify_and_open(path, "Sarus digest", f"{total} message(s), {urgent} urgent")
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
