"""Microsoft Graph authentication via MSAL device-code flow with a persistent token cache.

Public-client flow only (no client secret). The token cache is serialized to
token_cache.bin so that after the first device-code login, subsequent runs acquire
a token silently without prompting again.
"""

import sys

import msal

from config import GRAPH_SCOPES, MS_CLIENT_ID, MS_TENANT_AUTHORITY

_CACHE_PATH = "token_cache.bin"


def _load_cache() -> msal.SerializableTokenCache:
    """Load the on-disk MSAL token cache, or start an empty one."""
    cache = msal.SerializableTokenCache()
    try:
        with open(_CACHE_PATH, "r") as f:
            cache.deserialize(f.read())
    except FileNotFoundError:
        pass
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    """Persist the cache to disk only if it changed."""
    if cache.has_state_changed:
        with open(_CACHE_PATH, "w") as f:
            f.write(cache.serialize())


def get_token(allow_interactive: bool = True) -> str:
    """Return a valid Graph access token, prompting device-code login only if needed.

    Tries acquire_token_silent first (uses the cache + refresh token); on miss,
    falls back to the device-code flow and prints the verification URL + code.

    Unattended callers (the meeting-prep poll, scheduled runs) pass
    allow_interactive=False: a silent miss then raises a clear RuntimeError
    instead of starting device-code flow, which would hang forever waiting on a
    code nobody can enter under launchd/cron. Run `python sarus.py` once
    interactively to (re)consent — e.g. after the Graph scopes change.
    """
    if not MS_CLIENT_ID or not MS_TENANT_AUTHORITY:
        raise RuntimeError(
            "MS_CLIENT_ID and MS_TENANT_AUTHORITY must be set in .env. "
            "MS_CLIENT_ID is your Entra app's Application (client) ID; "
            "MS_TENANT_AUTHORITY is e.g. https://login.microsoftonline.com/consumers."
        )

    cache = _load_cache()
    app = msal.PublicClientApplication(
        MS_CLIENT_ID,
        authority=MS_TENANT_AUTHORITY,
        token_cache=cache,
    )

    # 1) Try silently from the cache (this also refreshes via the refresh token).
    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])

    # 2) Fall back to device-code flow — unless this is an unattended run.
    if not result and not allow_interactive:
        raise RuntimeError(
            "No valid token could be acquired silently (the cache is missing, "
            "expired, or lacks the required scopes). This unattended run will not "
            "prompt for device-code login. Run `python sarus.py` once interactively "
            "to sign in / re-consent, then scheduled runs will refresh silently.\n"
            f"Scopes requested: {GRAPH_SCOPES}"
        )

    if not result:
        flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(
                "Failed to start device-code flow. Check that the Entra app has "
                "'Allow public client flows' = Yes.\n"
                f"Raw response: {flow}"
            )
        print(flow["message"])  # human-readable: go to <url> and enter <code>
        sys.stdout.flush()
        result = app.acquire_token_by_device_flow(flow)

    _save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(
            "Authentication failed.\n"
            f"  error: {result.get('error')}\n"
            f"  description: {result.get('error_description')}\n"
            "Hints: verify MS_CLIENT_ID/MS_TENANT_AUTHORITY, that the Mail.Read "
            "delegated permission is granted, and that 'Allow public client flows' = Yes."
        )

    return result["access_token"]


def _smoke_check(allow_interactive: bool = True) -> None:
    """Prove auth + the Mail.Read scope by reading one message from Graph.

    We deliberately do NOT call /me (profile), which would require User.Read —
    reading a single message proves the token works for exactly what Sarus needs.

    With allow_interactive=False (the `--silent` mode), this proves the cached
    token refreshes silently without any prompt — the precondition for the
    unattended prep poll and scheduled digest.
    """
    import requests

    token = get_token(allow_interactive=allow_interactive)
    resp = requests.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={"$top": "1", "$select": "subject,from,receivedDateTime"},
        timeout=30,
    )
    resp.raise_for_status()
    messages = resp.json().get("value", [])
    if not messages:
        print("Authenticated. Mail.Read works — mailbox has no messages.")
        return
    m = messages[0]
    sender = (m.get("from") or {}).get("emailAddress", {}).get("address", "unknown")
    print("Authenticated. Mail.Read works.")
    print(f"Latest message: {sender} — {m.get('subject')!r} ({m.get('receivedDateTime')})")


if __name__ == "__main__":
    # `python auth.py`           interactive smoke check (device-code on first run)
    # `python auth.py --silent`  prove the cached token refreshes with NO prompt
    silent = "--silent" in sys.argv
    if silent:
        print("Silent token check (no device-code prompt will be shown)…")
    _smoke_check(allow_interactive=not silent)
