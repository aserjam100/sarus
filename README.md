```
⠀⠀⠀⠀⠀⠀⠀⠘⣿⣆⠀⠈⢻⣷⡄⠀⠀⠀⠀⠀⠀⠀⠀⣀⣴⣾⠛⢻⣿⣶⠾⠛⠋⠉⠀⠀⠀⠀⠾⠋⠁⠀⣼⡿⠀⠀⠀⠀⣠⣴⣦⣄⡀
⠀⠀⠀⠀⠀⠀⠀⠀⣻⣷⣶⣶⣶⣬⣿⣷⣶⣟⣩⡾⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢿⣿⣷⡀⠀⠀⠀⠀⠀⣀⣼⠟⠋⠀⢀⣾⡟⠁⠀⠀⠈⠛
⠀⠀⠀⠀⠀⠀⠀⣴⡾⠋⠀⠀⠀⠀⠀⠀⠀⠈⠉⠙⠛⠀⠶⣶⣶⣦⣤⣤⣀⣀⡀⠈⢿⣟⢿⣆⠀⠀⣠⡾⠛⠁⠀⠀⢠⣾⡟⠀⠀⠀⠀⠀⠀
⠀⠀⢀⣴⣿⣿⡵⠾⠛⠁⠀⠀⠀⠀⠀⠀⠀⢀⣀⣤⣤⣤⣤⣤⣤⣤⣤⣤⣴⡿⠁⠀⠀⠀⠀⣰⣿⠟⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⣿⣿⣿⠿⠶⠶⠶⠶⠿⢿⣿⡿⠛⠛⠛⠙⠻⣯⣍⣉⣥⣶⠾⠟⠋⠁⠀⣾⠁⠀⠀⠀⣠⣾⡿⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
```

# Sarus

A personal, **read-only** email triage tool. On a schedule it signs in to your
Microsoft mailbox (read-only), sends recent mail to Claude for categorization +
summary, and writes a markdown briefing. It runs locally on your machine with
your own credentials. Sarus reports; you act.

> Sarus is named for the sarus crane — a tall, long-necked bird.

## What it can and can't do

- ✅ Reads recent mail (`Mail.Read` only) and summarizes it.
- ❌ Never sends, deletes, moves, or modifies mail. There is no write access.
- 🔒 Your API key and login token stay on your machine. Nothing is committed to git.

## Requirements

- Python 3.10+
- An **Anthropic API key** — from <https://console.anthropic.com>
- A **Microsoft account with a mailbox** (Outlook.com / Hotmail / Live work out of
  the box; a work/school account also works but may need your IT admin's approval)

## Setup for a new user

### 1. Get the code and install

```bash
git clone <repo-url> sarus
cd sarus
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the onboarding screen

```bash
python setup.py
```

This opens a small terminal UI. The Microsoft settings are **already filled in**
for you — you only paste your **Anthropic API key** (input is hidden). Press
**Save & Continue** and it writes a local `.env` file.

> Using a **work/school** account? After setup, open `.env` and change
> `MS_TENANT_AUTHORITY` from `.../consumers` to `.../common` (or your tenant ID).
> Your organization's admin may need to approve the app the first time you sign in.

### 3. Sign in to Microsoft

```bash
python sarus.py
```

On first run it prints a URL and a code. Open the URL in a browser, enter the
code, sign in with your Microsoft account, and approve the **read your mail**
permission. That's a one-time step — the login is cached locally
(`token_cache.bin`), so future runs don't prompt.

### 4. Read your briefing

Sarus writes a dated markdown file to `briefings/` and prints it to the terminal.

## Running on a schedule

Add a cron entry (adjust the path):

```cron
0 7,18 * * *  cd /path/to/sarus && /path/to/sarus/venv/bin/python sarus.py >> sarus.log 2>&1
```

That runs Sarus at 7am and 6pm daily, logging to `sarus.log`. On macOS, if cron
misbehaves, use a `launchd` agent instead.

## A note on the Microsoft client ID

The `MS_CLIENT_ID` shipped in setup is Microsoft's public "Graph Command Line
Tools" client — it is **not a secret** and grants no one access to your mail.
Access only happens when *you* sign in and consent for *your own* mailbox. If you
prefer your own app registration (e.g. so the consent screen reads "Sarus"), you
can register a public client in Microsoft Entra and swap the ID in `.env`.

## Privacy

Everything runs locally. Your mail is sent only to the Anthropic API for
triage, under your own key. `.env`, `token_cache.bin`, and `briefings/` are
gitignored and never leave your machine via this tool.
