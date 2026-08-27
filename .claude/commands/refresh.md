---
description: Refresh this gameweek's FPL research from the web — free, no API key
---

Refresh the research files for the upcoming gameweek.

## Why this is a command rather than a button in the app

The app runs on Streamlit Cloud, which is a plain Python process. For it to
research anything itself it would need a metered API key, and this project is
deliberately zero-cost — there is no paid code path anywhere in it, and a test
enforces that. Web search inside a Claude Code session is covered by the
subscription instead, so the research happens here and gets committed.

## Step 1 — work out what actually needs researching

Do NOT start by searching for "who are analysts talking about". That makes the
media cycle decide your coverage, and it is why this file used to cover a dozen
players out of a pool of seven hundred while a differential the model liked went
unmentioned.

Ask the app instead:

```
python -c "
from fpl_assistant import api
from fpl_assistant.analysis import gameweek_state, squad_builder, decision_set
from fpl_assistant.models import events_df, fixtures_df, teams_df, players_df, attach_team_names
b = api.get_bootstrap_static(); fx = fixtures_df(api.get_fixtures())
teams = teams_df(b); players = attach_team_names(players_df(b), teams)
s = gameweek_state.resolve(events_df(b), fx)
scored = squad_builder.score_players(players, fx, teams, s.planning_event)
ds = decision_set.build(scored)
print('GW', s.planning_event, '| live:', s.live_event, '|', len(ds), 'players in the decision set')
for e in ds.entries:
    print(f\"  [{e.depth:7s}] {e.name:16s} {e.team:4s} {e.position:4s} £{e.price:4.1f}m {e.ownership:5.1f}%  {'; '.join(e.reasons)}\")
print()
print('coverage now:', decision_set.coverage(ds, scored))
"
```

That prints the players any decision this week could touch — your squad, the
realistic transfer targets at each position, the template, and anything the
projection rates highly — each tagged `full` or `facts`.

If the FPL API is unreachable, say so and ask which gameweek rather than
guessing. Print that gameweek's fixtures too: research aimed at the wrong
matches is worse than none.

## Step 2 — research that list, at the depth it's tagged

**`full`** — needs a `case`, a real `watch_out`, at least two `key_stats`,
`voices` attributed to named outlets, and `dissent` where opinion genuinely
splits.

**`facts`** — needs only `predicted_start`, `set_pieces` and `role`. Do not
write a case for a squad filler nobody will start; effort spent where no
decision is being made is effort not spent where one is.

Work the list rather than the headlines. A player on it that nobody has written
about this week is still worth a line saying so — "no coverage found, projection
only" is information.

### Prioritise, within that

1. **Predicted line-ups and team news.** Minutes decide more gameweeks than any
   rate does, and the FPL API carries nothing useful about them — availability
   only moves once a club confirms an injury, by which point everyone knows.
   `predicted_start` must be one of: `nailed`, `likely`, `rotation risk`,
   `doubt`, `out`.
2. **Set-piece and penalty order.** FPL's own order fields lag reality by weeks.
   Dedicated trackers publish this properly.
3. **Role changes.** A full-back playing as a winger is the most valuable
   mispricing in the game, and no rate will tell you about it.
4. **Highly owned players analysts are now warning against.**
5. **Genuine splits in expert opinion.**
6. **Club-wide verdicts**, for as many of the twenty as you can support.
7. **Anytime-goalscorer odds and expected captain share** for the
   most-captained attackers. Captain share governs rank and appears nowhere in
   the FPL API, so if you find nothing else, find this.
8. **Head-to-head history** for the notable fixtures.

Cover at least six or seven distinct outlets: Fantasy Football Scout, RotoWire,
AllAboutFPL, Fantasy Football Fix, Fantasy Football Hub, the official Scout,
OneFPL, FPL Pulse. One outlet's view is a take; several agreeing is a consensus,
and the difference is the whole point of the file.

## Step 3 — write the files

- `data/consensus/gw{n}.json` — the decision set, at tagged depth.
- `data/consensus/teams.json` — club `stances`. Update where a verdict has
  changed or expired, and move it when the evidence moves: a club that was an
  avoid and then won deserves a downgrade to caution, not a silent hold.
- `data/odds/gw{n}.json` — goalscorer prices, `captain_share`, `matchups`.
  Write no file at all rather than an invented one.

## Step 4 — validate, then commit

Non-negotiable:

```
python -m pytest tests/test_research_data_quality.py -q
```

If it fails, fix the data — never the rules. Each exists because it caught
something real. Then re-run the coverage line from Step 1 and report the number:
that is the honest measure of whether this refresh did its job.

Commit and push to the current branch.

## The most important thing this file does

**Lead with what people are saying, and split it into the two piles a
manager actually weighs.** Every researched player gets `talking_points`:

```json
"talking_points": {
  "for":     [{"point": "...", "source": "Named Outlet"}],
  "against": [{"point": "...", "source": "Named Outlet"}]
}
```

These are individual arguments, not a synthesis. The register to aim for is
tactical and observational, the way a pundit or a forum post talks:

- *"He has been playing deeper, in a double pivot alongside Gravenberch — a
  long way from the advanced role that produced his returns."*
- *"Brighton conceded 46 last season, their best in five years; only City
  and Arsenal were tighter."*
- *"Palace are missing Riad and Sarr, so it's a reshuffled back three being
  asked to handle Haaland."*

Not: *"his xGI ranks 4th among midfielders"*. Numbers belong in `key_stats`,
where they support the argument rather than replacing it.

**Club-level commentary goes in `matchups_gw{N}.json`, not in a player's
write-up.** "Brighton have a strong defence" is a fact about a fixture and
is true for every attacker who faces them. Write it once against the
fixture and it reaches all of them; write it into one player's prose and it
reaches one. Each fixture records what people say about both clubs' attack
and defence, attributed. An attacker is then shown the opposition's
defence, a defender the opposition's attack.

**Record against this specific opponent** goes in `record_vs`, as prose.
"He usually scores against them" is the first thing anyone says when
arguing for a captain, and the FPL API knows nothing about it — it carries
only this season, only in aggregate. Look it up:

- *"Eight goals in five Premier League meetings with Crystal Palace — he has
  scored in every one, including a hat-trick, and four were at Selhurst."*
- *"Scored or assisted three of Forest's last six goals at Anfield."*

If the record is thin, say so. *"One assist in two appearances — not a
reason to buy him on its own"* is useful; silence is not.

Aim for **at least three arguments on each side** for any player at `full`
depth, and cover every fixture that a decision could turn on.

## Keep the season-history prior even across positions

`data/history/seasons.json` is the memory the projection falls back on when
this season is only a few games old. It must cover **all four positions**,
at least four players each — `history.coverage()` reports it and a test
fails if it's thin.

This is not tidiness. A player with a prior is judged on two seasons; a
player without one is judged on a single gameweek. So a prior covering only
attackers does not merely miss defenders, it actively marks them down — the
app recommended selling Gabriel, the highest-scoring defender in the game
the previous season on 209 points, purely because he had no memory and a
striker did. If you add players here, add them across the pitch.

## The rules that matter most

- **Attribute every opinion to a named outlet.** "Analysts say" is not a source;
  it is how an unchecked claim survives.
- **Every `full` player needs a genuine counter-argument.** A recommendation you
  can't argue against is not advice. If you can't find a risk, look harder.
- **Record disagreement as disagreement** in `dissent` rather than averaging two
  views into a bland middle, and say which *kind* of disagreement it is:
  - `"kind": "output"` (the default) — they disagree about whether he'll score.
    This damps the player's weighting and blocks the `must_have` tier.
  - `"kind": "rank"` — they agree he'll score and argue about whether owning a
    heavily-owned premium gains you anything. This is surfaced just as loudly but
    does **not** touch the projection, because marking a player down for being
    popular is backwards. Haaland at 71% ownership is the standing example.
- **Weigh multi-season evidence above this season's, early on.** Two gameweeks in,
  what a player did across the last two full seasons is far better evidence than
  what he did last Saturday. A blank from a proven asset is noise; a haul from an
  unproven one is a hypothesis. Lead the `case` with the durable record and treat
  the recent week as context — the app dropped a Golden Boot winner on one blank,
  and the research file made it easier by tiering him as merely "strong".
- **Structural beats statistical in the first month.** A confirmed penalty or
  set-piece appointment, a positional change, a starter out for two months — these
  are worth more than any amount of one-week xG. Say which one you're relying on.
- **Club-wide advice belongs in `teams.json`,** never in a player's prose.
  Written into one write-up it reaches one player, and the optimiser goes on
  picking the club's other twenty. This has actually happened.
- **Prefer checkable specifics.** "18 clean sheets, three more than any other
  defender" beats "excellent defensive record".
- **Never invent a number.** No sourced odds means no odds file. A missing figure
  is honest; a plausible invented one is the failure this project exists to
  avoid.
- **Report what you couldn't cover.** Ending with the gaps is more useful than
  implying the list is complete.
