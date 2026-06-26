"""Single dispatch point for LLM calls.

Every model call in Sarus goes through summarize(), so swapping or adding a
provider is a one-file change. Today only Anthropic is wired up (the project's
core dep); the PROVIDER config value selects the backend, and an unimplemented
provider fails loudly rather than silently doing nothing.
"""

from config import MODEL, PROVIDER

# Generous enough for both the triage JSON verdict and a longer meeting-prep brief.
_MAX_TOKENS = 2000


def summarize(prompt: str) -> str:
    """Send a single prompt to the configured LLM and return its text response.

    Raises RuntimeError for a provider that isn't implemented yet — callers
    should never silently get an empty result.
    """
    provider = (PROVIDER or "anthropic").strip().lower()
    if provider == "anthropic":
        return _summarize_anthropic(prompt)
    raise RuntimeError(
        f"PROVIDER={provider!r} is not supported. Only 'anthropic' is implemented. "
        "Set PROVIDER=anthropic in .env (or add the provider in provider.py)."
    )


def _summarize_anthropic(prompt: str) -> str:
    """Anthropic backend. Reads ANTHROPIC_API_KEY from the environment."""
    from anthropic import Anthropic

    client = Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


if __name__ == "__main__":
    # Smoke check — one tiny live call.
    print(summarize("Reply with exactly the word: ok"))
