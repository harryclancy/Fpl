---
description: Refresh this gameweek's FPL research from the web — free, no API key
---

Refresh the research files for the upcoming gameweek.

## Why this is a command rather than a button in the app

The app runs on Streamlit Cloud, which is a plain Python process. For it to
research anything itself it would need a metered API key, and this project
is deliberately zero-cost — there is no paid code path anywhere in it, and a
test enforces that. Web search inside a Claude Code session is covered by the
subscription instead, so the research happens here and gets committed.

## Do this

1. **Work out which gameweek to research.** Run:

   ```
   python -c "
   from fpl_assistant import api
   from fpl_assistant.analysis import gameweek_state
   from fpl_assistant.models import events_df, fixtures_df, teams_df
   b = api.get_bootstrap_static()
   s = gameweek_state.resolve(events_df(b), fixtures_df(api.get_fixtures()))
   print('plan for GW', s.planning_event, '| live:', s.live_event)
   "
   ```

   If the FPL API is unreachable, ask which gameweek rather than guessing.
   Print that gameweek's fixtures too — research aimed at the wrong matches
   is worse than none.

2. **Search the web.** Cover Fantasy Football Scout, RotoWire, AllAboutFPL,
   Fantasy Football Fix, Fantasy Football Hub, the official Scout, OneFPL.
   Prioritise, in this order:

   - **Late team news and injuries.** This dates fastest and matters most.
   - **Highly owned players analysts are now warning against.** The most
     valuable thing this file holds.
   - **Genuine splits in expert opinion.**
   - **Club-wide verdicts** ("avoid this club until the fixtures turn").
   - **Anytime-goalscorer odds and expected captain share** for the
     most-captained attackers.
   - **Head-to-head history** for the notable fixtures — what typically
     happens when these two meet.

3. **Write the files**, matching the existing structure exactly:

   - `data/consensus/gw{n}.json` — 12-16 players. Each needs a `case`, a real
     `watch_out`, at least two `key_stats`, and `voices` attributed to named
     outlets.
   - `data/consensus/teams.json` — update club `stances` where a verdict has
     changed or expired. Every stance needs an `until_gameweek`.
   - `data/odds/gw{n}.json` — goalscorer prices, `captain_share`, `matchups`.

4. **Validate before committing.** Non-negotiable:

   ```
   python -m pytest tests/test_research_data_quality.py -q
   ```

   If it fails, fix the data — never the rules. They exist because each one
   caught something real.

5. **Commit and push** to the current branch.

## The rules that matter most

- **Attribute every opinion to a named outlet.** "Analysts say" is not a
  source; it is how an unchecked claim survives.
- **Every player needs a genuine counter-argument.** A recommendation you
  can't argue against is not advice. If you can't find a risk, look harder.
- **Record disagreement as disagreement** in `dissent`, rather than averaging
  two views into a bland middle. A `must_have` can never carry a dissent —
  that tier locks a player in and is only for near-unanimity.
- **Club-wide advice belongs in `teams.json`,** never in a player's prose.
  Written into one write-up it reaches one player, and the optimiser goes on
  picking the club's other twenty. This has happened before.
- **Prefer checkable specifics.** "18 clean sheets, three more than any other
  defender" beats "excellent defensive record".
- **Leave a player out rather than pad.** A short accurate file beats a long
  padded one.
- **Say what you couldn't verify.** Ending with the gaps is more useful than
  implying full coverage.
