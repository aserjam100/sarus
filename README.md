```
 ____   __   ____  _  _  ____ 
/ ___) / _\ (  _ \/ )( \/ ___)
\___ \/    \ )   /) \/ (\___ \
(____/\_/\_/(__\_)\____/(____/
```

# Sarus

A personal, **read-only** email triage tool. On a schedule it signs in to your
Microsoft account (read-only), sends recent mail to Claude for categorization +
summary, and writes a styled **HTML** briefing that pops up as a clickable macOS
notification. It can also **prep you for upcoming meetings**: a background poll
briefs each meeting starting soon, straight from your calendar. It runs locally
on your machine with your own credentials. Sarus reports; you act.

> Sarus is named for the sarus crane — a tall, long-necked bird.

## What it can and can't do

- ✅ Reads recent mail and upcoming calendar events, and summarizes them
  (read-only scopes: `Mail.Read`, `Calendars.Read`, `Files.Read.All`).
- ❌ Never sends, deletes, moves, or modifies anything. There is no write access.
- 🔒 Your API key and login token stay on your machine. Nothing is committed to git.

## What a meeting brief includes

For each meeting starting soon, Sarus reads the calendar invite and writes a
tight, scannable brief so you can walk in ready:

- **What & when** — subject, start time, duration, online/in-person.
- **Who** — organizer and attendees with their role (required/optional) and
  response (accepted/declined/tentative), flagging any notable declines.
- **Agenda** — the purpose/agenda drawn from the invite body.
- **Join** — the meeting link or location.
- **What to prepare** — 2–5 concrete prep actions tailored to that meeting.

It sticks to what's in the invite (it won't invent facts) and skips a section
when there's genuinely nothing to say.

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

Sarus writes a dated, styled HTML file to `~/briefings/` (in your home folder)
and shows a macOS notification — click it to open the briefing in your browser.
(The HTML stays in `~/briefings/` if you miss the banner.) Files are named by
type: `digest-<date>.html` and `meeting-<subject>-<hash>-<date>.html`.

## Running on a schedule

`python setup.py` offers to schedule Sarus for you on macOS. It installs two
`launchd` agents (they run in your GUI session, so the clickable notifications
actually appear):

- **Daily digest** at a time you choose (e.g. 07:00) — runs `sarus.py`.
- **Meeting prep** (optional) — runs `prep.py` at **:05 and :35 past every hour**;
  briefs any meeting starting in the next ~35 minutes, exactly once each. (The
  fixed times give a ~25-min heads-up for the usual :00/:30 meeting starts.)

> Notifications need `alerter`:  `brew install alerter`. Without it the HTML
> briefing is still written, just no banner.

On non-macOS / headless hosts, `setup.py` prints the equivalent `cron` lines
instead (note: under cron the notification banner may not appear).

## A note on the Microsoft client ID

The `MS_CLIENT_ID` shipped in setup is Microsoft's public "Graph Command Line
Tools" client — it is **not a secret** and grants no one access to your mail.
Access only happens when *you* sign in and consent for *your own* mailbox. If you
prefer your own app registration (e.g. so the consent screen reads "Sarus"), you
can register a public client in Microsoft Entra and swap the ID in `.env`.

## Privacy

Everything runs locally. Your mail and calendar are sent only to the Anthropic
API for triage/prep, under your own key. `.env` and `token_cache.bin` are
gitignored, your briefings are written to `~/briefings/` (outside the repo), and
nothing leaves your machine via this tool.
