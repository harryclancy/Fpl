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

## The principle

This should read as though a hundred FPL experts worked on it — not as
though an algorithm ranked a spreadsheet. The projection is ONE input. A
recommendation resting on it alone is not finished work.

Every pick must combine: data + fixtures + current news + tactical role +
expected minutes + expert opinion + longer-term strategy.

Not good enough:
> "Haaland has the highest projected points."

The standard:
> "Palmer stays because he is still Chelsea's penalty taker, still playing
> as the No.10, and several sources this week flagged his underlying
> numbers despite the blank. Chelsea then face X and Y over the next
> three, so selling after one quiet game likely means buying him back."

## The twenty steps

1. **Load the current squad.** The user's ACTUAL team — never a squad this
   app recommended earlier. Confirm the gameweek it came from.
2. Load bank, free transfers, chips available, current prices.
3. Identify the gameweek and its deadline.
4. Search the verified sources for material on this gameweek.
5. Research every owned player. All fifteen, no exceptions.
6. Research realistic transfer targets.
7. Research injuries, suspensions and team news.
8. Research manager press conferences.
9. Update underlying statistics.
10. Evaluate this gameweek.
11. **Evaluate the next 3-5 gameweeks.**
12. Determine transfers — or that rolling is better.
13. Determine the XI.
14. Determine bench order.
15. Determine the captain.
16. Determine the vice-captain.
17. Write reasoning for every squad player.
18. Write reasoning for every transfer.
19. Run factual verification (below).
20. Record the run:

```bash
python -c "import sys; sys.path.insert(0,'.'); \
from fpl_assistant.research import research_log; \
r = research_log.measure(GW); research_log.save(r); print(r.coverage_line)"
```

Step 1 is the one that has actually gone wrong: check what needs
researching by asking the app, not by reading the headlines.

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
print('GW', s.planning_event, '|', len(ds), 'players in the decision set')
for e in ds.entries:
    print(f\"  [{e.depth:7s}] {e.name:16s} {e.team:4s} {e.position:4s} £{e.price:4.1f}m {e.ownership:5.1f}%\")
"
```

If the FPL API is unreachable, say so and ask which gameweek rather than
guessing.

## What to research, per player

Availability and role first, because they void everything else:

- injuries, doubts, suspensions, expected minutes, starting likelihood
- manager press-conference quotes
- tactical role, position on the pitch, recent starts and substitutions
- set pieces: penalties, corners, free-kicks — separately, not as one field

Then output and context:

- form, xG, xA, xGI, shots, shots in the box, big chances, chances created
- clean-sheet prospects, defensive-contribution potential, bonus potential
- ownership, price, price-change risk, transfers in and out
- fixture difficulty and the upcoming RUN, rotation and European rotation
- who experts are buying, selling, captaining, and disagreeing about

## Verify before you publish

Claude has previously been wrong about roles, injuries, fixtures, set
pieces, transfers and team status. Before writing any of these as fact:

> "X takes penalties" · "X is injured" · "X has lost his place" ·
> "X is playing deeper" · "X is suspended" · "X's next three are…"

**find it stated, and for the important ones find it twice.** Minutes and
set-piece claims are the two that change a decision on their own — the
quality-control gate reports which of them rest on a single source.

When sources conflict, do NOT silently pick one:

```json
"dissent": {"kind": "output", "case": "Sources disagree here: A says…, B says…", "sources": [...]}
```

When something cannot be confirmed, write **"Unconfirmed"** rather than
presenting it as fact. An honest gap is usable; a confident guess is not.

Never fabricate consensus. Two outlets in favour and eight against is not
"analysts like him" — it is a split, and saying so is the useful part.

## Freshness

- **Team news:** last ~72 hours. Older is background, not evidence.
- **Press conferences:** the latest one, not last week's.
- **FPL advice:** pieces about THIS gameweek specifically.
- **Statistics:** this season and recent matches.

An evergreen article can give background but must never override current
information. If an official club source contradicts an FPL blog, the club
source normally wins.

## Look ahead 3-5 gameweeks, always

No transfer is judged on one Saturday. For each proposed move ask:

- Does the incoming player have more than one good fixture?
- Are we buying immediately before a hard run?
- Will we want to sell him again next week?
- Does the outgoing player have a good fixture coming?
- Would rolling be better?
- Does this block a more important move next week?
- Does it leave enough money for the next one?
- Is a hit genuinely justified?

`analysis/transfer_case.py` computes the horizon comparison, the
alternative and the roll verdict. `analysis/planner.py` does the
multi-week ILP. Use them — but the words are yours.

## Writing standard

Numbers support the write-up; they never replace it.

> ✅ "Watkins has not scored yet, but the underlying picture is better than
> the returns suggest…"
> ❌ "Watkins xGI = 1.37. Projection = 5.82."

Attribute properly — "three of the sources reviewed this week", "Villa's
manager confirmed in his press conference", "according to Liverpool's own
preview". Never "analysts say".

## The homepage has exactly three sections

1. **This week's suggested team** — pitch, C and VC marked, bench beneath.
2. **Suggested transfers** — SELL → BUY, then why-sell, why-buy,
   why-this-swap, short-term, next 3-5 GWs, alternative, roll?, confidence.
   If rolling is right, say ROLL THE TRANSFER and explain. Never invent a
   move to fill the space.
3. **Why each player is in the team** — all fifteen, own card, specific
   prose, sources collapsed behind a quiet "Sources used: N".

Nothing else goes above these. Everything else belongs on another tab.

## Before publishing

`analysis/quality_control.py` runs the checklist: squad size and vintage,
availability, expected minutes, bank, free transfers, transfer reasoning,
look-ahead, a write-up per player, one captain, and that the captain is a
midfielder or forward. Blockers are shown to the reader rather than
silently swallowed. **If a check fails, resolve it — do not publish over it.**

## Where to research from — the 100 verified sources, and nothing else

`data/sources/verified_sources.json` holds exactly 100 domains. Every one
was tested by running a domain-scoped search against it and confirming it
returned readable article text. **Search only these.**

```bash
python -c "import sys; sys.path.insert(0,'.'); from fpl_assistant.research import sources; \
p=sources.plan(); print(sources.summary(p)); \
[print(g.label, g.domains) for g in p.groups]"
```

This is not a preference, it is a capability constraint. A domain the
search API rejects fails the **entire search it appears in** — one blocked
publisher in a group of six silently loses the other five as well. That is
why the file exists and why nothing outside it may be searched.

**Permanently excluded. Do not add them back:**

- **YouTube, X** — a search cannot read a video transcript or a social
  timeline.
- **Reddit** — post text is not reliably retrievable.
- **Crawler-blocked publishers** — football.london, Manchester Evening
  News, Liverpool Echo, Birmingham Live, Chronicle Live, Nottingham Post,
  Hull Live, Coventry Telegraph, The Argus, Sunderland Echo, Bournemouth
  Echo, Yorkshire Evening Post, MyLondon, EADT, Evening Standard, Daily
  Mail, The Sun, talkSPORT, BBC, Guardian, Independent, Metro, Reuters,
  Transfermarkt. Each confirmed by the API rejecting it by name.

**The clubs' own sites are the sharpest source and all twenty work.** They
carry the manager's press conference verbatim, and several publish their
own FPL content weekly: Manchester City run an "FPL Scout Report" per
gameweek, Liverpool publish "five players to watch", Aston Villa put out a
pre-match FPL preview. That is a day ahead of the aggregators.

## Work the gameweek in this order

Availability first, because everything downstream is void for a player who
is not playing — and a confident write-up on a player who has been ruled
out is worse than no write-up.

1. **Official club news and press conferences** (tier 2)
2. **Injury and expected-minutes information** (tiers 2, 3)
3. **FPL expert recommendations** (tier 1)
4. **Captaincy consensus** (tier 1)
5. **Transfer recommendations** (tier 1)
6. **Differentials** (tier 1)
7. **Underlying statistics** (tier 3)
8. **Fixture analysis** (tiers 1, 4)
9. **Price changes and ownership** (tier 1)
10. **Conflicting opinions** (tiers 1, 4)

`sources.plan()` returns the scoped searches already in this order.

**Never record a source as researched unless you actually retrieved
readable information from it.** Listing a domain you searched but which
returned nothing is the same failure as an unattributed quote. In the
sign-off, say which sources produced content and which came back empty.

## Research the squad the user OWNS first

Before anything else, get the owned fifteen and cover every one of them.
The front page has a section explaining why the user holds each player
they actually hold — including anyone the plan wants to sell, with the
case against, so they can disagree with the sale rather than just accept
it. That section falls back to a bare projection for anyone missing from
the research, which is precisely the complaint this file exists to answer.

Order of work:
1. **Every player in the owned squad.** All fifteen, no exceptions.
2. Players the plan wants to buy.
3. The rest of the decision set (`analysis/decision_set.py`).

A gameweek where all fifteen owned players are covered and only six
candidates are is a better week's work than the reverse.

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

## Transfers: the app decides how many, not the user

`analysis/transfer_budget.py` sets the ceiling: **two in a normal week**,
rising only when enough of the fifteen is genuinely unavailable that
patching is not optional. Do not add a control that hands that choice
back to the reader — a slider there is the app declining to do its job
and calling it flexibility.

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
