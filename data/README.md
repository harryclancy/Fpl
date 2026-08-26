# Research data

Everything the app knows that isn't in the FPL API.

| File | What it holds |
|---|---|
| `consensus/gw{n}.json` | Per-player verdicts: the case, the counter-argument, hard numbers, and what named outlets said. |
| `consensus/teams.json` | Club-wide verdicts. Advice about a club has to be stored as data about the club — written into one player's prose it reaches one player. |
| `odds/gw{n}.json` | Anticipated returns: goalscorer prices, expected captaincy share, and what typically happens when these sides meet. |
| `snapshots/gw{n}.json` | What the app recommended *before* each deadline, so the record can't be rewritten once results are in. |

## How they're refreshed

`.github/workflows/research.yml` runs twice a day. Inside a window before
each deadline it searches the web via Claude, validates the result against
`fpl_assistant/research/validation.py`, and commits it.

**Nothing is written unless it passes validation.** A rejected refresh
keeps the previous file: stale research known to be stale beats fresh
research that is wrong, because only one of those announces itself.

The workflow needs an `ANTHROPIC_API_KEY` repository secret. Without it
the research step fails and the app runs on whatever is already committed
— degraded, not broken.

## Why the rules are strict

Every rule in `validation.py` exists because something went wrong in that
shape. Club-wide advice buried in a player's write-up. A recommendation
with no counter-argument. An opinion attributed to "analysts" with no
outlet behind it. A contested pick presented as settled. These are the
failure modes of confident writing, and an agent produces confident
writing every time — so the rules are about evidence and attribution
rather than completeness.
