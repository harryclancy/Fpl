# Deployment and refresh

Everything here is free. No paid hosting, database, scheduler, API or
automation service is used, and none can be introduced without changing
this file.

## Why you were pressing Reboot

**Streamlit Community Cloud already redeploys automatically** when the
watched branch receives a push. That is built-in, free behaviour and this
project has always had it. So the Reboot button was never fixing a broken
deploy.

What it was doing was answering a question the app refused to answer:
*"has my change actually gone live?"* With no way to see which commit was
running, rebooting was the only way to be sure — so it became a habit.

The app now shows the deployed build in a small line under the squad:

```
Gameweek 2 · Updated 28 Aug 2026 · 00:00 UTC · build 1359e73 · 28 Aug 2026 · 11:22 UTC
```

If that short hash matches your last push, the deploy has landed and a
reboot would achieve nothing.

Two genuine reasons a reboot is still occasionally needed, neither of them
routine:

- **A free-tier app sleeps after about a week of inactivity.** Opening it
  wakes it; that is a wake, not a redeploy.
- **A failed dependency install.** If `requirements.txt` changes and the
  build fails, the old version keeps serving. `scripts/preflight.py`
  catches the common cause before it is pushed.

## The deploy contract

Streamlit watches **one repository, one branch, one entry point**:

| | |
|---|---|
| Repository | `harryclancy/Fpl` |
| Branch | `claude/fpl-assistant-manager-fjcupn` (the default branch) |
| Entry point | `fpl_assistant/dashboard/app.py` |

A push to that branch redeploys within a minute or two. Nothing else is
required.

**One-time check, if it is not already on:** in the Streamlit dashboard,
app settings, confirm the branch above is the one being watched. Once set
it never needs revisiting.

## Before every push

```bash
python scripts/preflight.py
```

Five checks: syntax across every file, the critical imports actually load,
every third-party import is declared in `requirements.txt`, the entry point
is intact, and the full app smoke test passes. That last one executes every
rendering path, which is where a `NameError` would otherwise sit until the
live site hit it.

This matters more here than in a normal repo: there is no staging step
between the commit and the live app, so a broken push reaches you directly.

## Refreshing the football data

Two clocks run, and conflating them is what makes the app look stale when
it is not.

**Live FPL data** — prices, injuries, ownership, fixtures — is fetched from
the official API on every load behind short caches. It is never more than
minutes old and needs nothing from you.

**Research** — the write-ups, matchup notes, club stances — is committed to
the repository by a Claude Code session. It only changes when a refresh is
run, so it can genuinely belong to a previous gameweek.

The app now checks this itself and says so:

> The written research on this page is from Gameweek 2, not Gameweek 3.
> Prices, injuries and fixtures below are live; the reasoning is a
> gameweek behind and team news does not survive a deadline.

The **↻ Refresh data** button beside that line clears the in-app caches and
re-fetches. It is free — it clears memory, nothing more — and it works from
the app, never the Streamlit dashboard.

To produce *new* research, run `/refresh` in a Claude Code session. That
commits new files, which pushes, which redeploys.

## Cache invalidation

Caches are keyed on the deployed commit as well as a TTL. A push that
changes the research files therefore produces a different cache key and the
new data appears immediately, rather than after up to half an hour of TTL.
That is the mechanism that replaces "press Reboot".

## What runs on a schedule, and what it costs

One GitHub Actions workflow, every three hours, on the free tier:

- `scripts/fetch_squad.py` — records your current squad, because the FPL
  API is reachable from Actions and not from a Claude Code session
- `scripts/snapshot_gameweek.py` — freezes the pre-deadline recommendation

Public repositories get unlimited free Actions minutes. This is the only
automation in the project.

## Costs

| | |
|---|---|
| Hosting | €0 — Streamlit Community Cloud free tier |
| Database | €0 — none; state is JSON in the repository |
| Scheduling | €0 — GitHub Actions free tier |
| APIs | €0 — the official FPL API is public and needs no key |
| Automation | €0 — one workflow, no third-party service |

**The app makes no LLM API calls.** Claude Code builds it; the deployed app
never calls a metered API. Two tests enforce this: one asserts no paid
package appears in `requirements.txt`, another that no source file
references `anthropic`, `openai` or `api_key`.
