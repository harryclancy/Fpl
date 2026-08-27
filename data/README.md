# Research data

Everything the app knows that isn't in the FPL API.

| File | What it holds |
|---|---|
| `consensus/gw{n}.json` | Per-player verdicts: the case, the counter-argument, hard numbers, and what named outlets said. |
| `consensus/teams.json` | Club-wide verdicts. Advice about a club has to be stored as data about the club — written into one player's prose it reaches one player. |
| `odds/gw{n}.json` | Anticipated returns: goalscorer prices, expected captaincy share, and what typically happens when these sides meet. |
| `snapshots/gw{n}.json` | What the app recommended *before* each deadline, so the record can't be rewritten once results are in. |

## How they're refreshed

Type `/refresh` in a Claude Code session on this repo, before a deadline
you care about. That's the whole thing — the command in
`.claude/commands/refresh.md` carries the full brief, so it does the same
job the same way every week.

This costs nothing beyond the session itself. It replaced an automated
workflow that called the Anthropic API on a schedule: that version worked,
but each run cost around $2 and a twice-daily schedule would have been
roughly $30 a week to refresh a JSON file. Not a sane price for what it
does.

Whoever writes these files — a person, or Claude in a session — the rules
in `fpl_assistant/research/validation.py` still apply, and
`tests/test_research_data_quality.py` enforces them against whatever is
committed. Run the tests after any refresh.

**Nothing in this app calls a paid API.** There is no key to set and no
way for it to spend money on its own.

## Why the rules are strict

Every rule in `validation.py` exists because something went wrong in that
shape. Club-wide advice buried in a player's write-up. A recommendation
with no counter-argument. An opinion attributed to "analysts" with no
outlet behind it. A contested pick presented as settled. These are the
failure modes of confident writing, and an agent produces confident
writing every time — so the rules are about evidence and attribution
rather than completeness.
