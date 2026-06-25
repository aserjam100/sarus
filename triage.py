"""Triage mail with Claude.

Sends the fetched messages to the Anthropic API and returns a parsed verdict:
an overall summary plus a per-email category and reason. The model returns only
JSON; we parse it in Python (the model does no arithmetic — guardrail #4).
"""

import json

from anthropic import Anthropic

from config import MODEL

_CATEGORIES = ("URGENT", "NEEDS_REPLY", "FYI", "NOISE")

_SYSTEM_PROMPT = (
    "You are an email triage assistant. You receive a list of recent emails and "
    "classify each one to help a busy person decide what needs attention.\n\n"
    "Categories (use exactly these):\n"
    "  URGENT      — time-sensitive; needs action very soon.\n"
    "  NEEDS_REPLY — a real person expects a response, but not urgently.\n"
    "  FYI         — informational; worth seeing, no action needed.\n"
    "  NOISE       — newsletters, promotions, automated notifications, spam.\n\n"
    "Be terse. This is a scannable briefing, not prose.\n"
    "  - overall_summary: ONE short sentence, ~12 words max. No preamble "
    "(no 'You have', 'There are', 'This inbox'). Just the gist.\n"
    "  - sender: the short label you were given (name if present, else the address).\n"
    "  - subject: copy it through, trimmed if very long.\n"
    "  - reason: a fragment of AT MOST 6 words. No full sentence, no trailing "
    "period, no filler ('requires', 'indicates', 'this is a'). E.g. "
    "'verify Singapore login', 'reply by Friday', 'promo'.\n\n"
    "Respond with ONLY valid JSON — no markdown fences, no prose, no commentary. "
    "Shape:\n"
    "{\n"
    '  "overall_summary": "<one short sentence>",\n'
    '  "emails": [\n'
    '    {"sender": "<short sender>", "subject": "<subject>", '
    '"category": "<one of URGENT|NEEDS_REPLY|FYI|NOISE>", '
    '"reason": "<=6 word fragment>"}\n'
    "  ]\n"
    "}\n"
    "Include every email you are given, once each."
)


def _strip_code_fences(text: str) -> str:
    """Strip a leading/trailing markdown code fence if the model added one.

    The system prompt asks for bare JSON, but models occasionally wrap it in
    ```json ... ``` anyway. We strip that one known wrapper deterministically;
    anything still unparseable falls through to the loud raise in triage().
    """
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]  # drop the opening ``` (or ```json) line
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]  # drop the closing ``` line
    return "\n".join(lines).strip()


def _format_emails(messages: list[dict]) -> str:
    """Render fetched Graph messages into a compact text block for the model."""
    lines = []
    for i, m in enumerate(messages, 1):
        ea = (m.get("from") or {}).get("emailAddress", {})
        # Prefer the display name (e.g. "Microsoft account team") over the long
        # noreply address — keeps the briefing's sender column readable.
        sender = ea.get("name") or ea.get("address") or "unknown"
        lines.append(
            f"[{i}] From: {sender}\n"
            f"    Subject: {m.get('subject')}\n"
            f"    Received: {m.get('receivedDateTime')}\n"
            f"    Unread: {not m.get('isRead', True)}  Attachments: {m.get('hasAttachments', False)}\n"
            f"    Preview: {(m.get('bodyPreview') or '').strip()[:500]}"
        )
    return "\n\n".join(lines)


def triage(messages: list[dict]) -> dict:
    """Classify messages with Claude and return the parsed verdict dict.

    Raises ValueError (including the raw model text) if the response is not valid
    JSON — guardrail #5: fail loudly rather than swallow unparseable output.
    """
    if not messages:
        return {"overall_summary": "No mail in the lookback window.", "emails": []}

    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Here are {len(messages)} recent emails:\n\n{_format_emails(messages)}",
            }
        ],
    )

    raw = response.content[0].text.strip()
    try:
        verdict = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude did not return valid JSON ({e}). Raw response:\n{raw}"
        ) from e

    _validate(verdict, raw)
    return verdict


def _validate(verdict: dict, raw: str) -> None:
    """Sanity-check the parsed verdict shape; fail loudly with the raw text."""
    if not isinstance(verdict, dict) or "emails" not in verdict:
        raise ValueError(f"Unexpected verdict shape. Raw response:\n{raw}")
    for item in verdict.get("emails", []):
        if item.get("category") not in _CATEGORIES:
            raise ValueError(
                f"Email has invalid category {item.get('category')!r}. Raw response:\n{raw}"
            )


if __name__ == "__main__":
    from fetch import fetch_recent_mail

    verdict = triage(fetch_recent_mail())
    print(json.dumps(verdict, indent=2))
