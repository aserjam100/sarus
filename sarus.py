"""Sarus pipeline: authenticate, fetch recent mail, triage it, write the briefing.

Run with `python sarus.py`. This is the full read-only pipeline:
auth (Microsoft Graph) -> fetch -> triage (Claude) -> output (markdown briefing).
"""

from config import LOOKBACK_HOURS, MODEL
from fetch import fetch_recent_mail
from output import emit
from triage import triage


def main() -> None:
    """Run the end-to-end triage pipeline."""
    print(f"Sarus: fetching mail from the last {LOOKBACK_HOURS}h…")
    messages = fetch_recent_mail()
    print(f"Fetched {len(messages)} message(s).")

    print(f"Triaging with {MODEL}…")
    verdict = triage(messages)

    emit(verdict)


if __name__ == "__main__":
    main()
