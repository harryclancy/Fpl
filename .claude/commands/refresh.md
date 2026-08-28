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
   app recommended earlier, and never "the decision set" as a substitute.

   ```bash
   python -c "import sys; sys.path.insert(0,'.'); \
   from fpl_assistant.analysis import my_squad; s = my_squad.load_stored(); \
   print(s.summary if s else 'NOT AVAILABLE'); \
   print([f\"{p['name']} ({p['team']} {p['position']})\" for p in (s.players if s else [])])"
   ```

   `data/squad/current.json` is written by `scripts/fetch_squad.py` in the
   snapshot workflow, because GitHub Actions can reach the FPL API and a
   Claude Code session cannot — the egress proxy refuses
   fantasy.premierleague.com. If the file is missing or stale, say so and
   ask for the fifteen names rather than quietly researching something
   else. Every player below means every player in THAT list.
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

## Research every player like a journalist — not like a tips aggregator

**No owned player may end the week with an empty profile.** "No write-up
found", "no expert opinion found", "insufficient research" describe ONE
failed search. They are never the final output for a player in the squad.

The question is not *"did one of our sources publish an FPL article about
him?"* It is *"what is currently happening with this footballer, and what
does that mean for Fantasy?"*

**Football news IS Fantasy news.** Each of these changes an
expected-minutes picture without any FPL writer mentioning it:

- omitted from a matchday squad · manager declining to commit to him
- a bid, active talks, a player asking to leave
- 90 minutes in a cup tie · a full-back suddenly at left wing
- losing corners · a new striker signed · a centre-back returning
- a manager saying someone "needs minutes" · training away from the group

### The escalation — research until resolved

Run these in order and STOP when the picture is clear, not when the first
search comes back empty.

**Pass 1 — FPL specialists.** Recommendations, ownership, transfers,
captaincy, fixtures, underlying data, sentiment.

**Pass 2 — his official club site.** Squad news, press conference, injury
update, manager comments, match preview, match report, interviews. All
twenty club sites are readable and they are a day ahead of the aggregators.

**Pass 3 — current football news.** Search HIS NAME, not "GW3 tips":
`[player] latest` · `[player] injury` · `[player] team news` ·
`[player] manager comments` · `[player] transfer` · `[player] expected to
start` · `[player] lineup` · `[player] set pieces` · `[player] penalties`.
Skip the redundant ones once a question is settled.

**Pass 4 — match evidence.** Latest XI, bench, minutes, substitution
timing, previous league appearance, cup appearance, formation, role.

**Pass 5 — reasoned inference.** Best evidence-based assessment, with the
three kinds of statement kept apart (below).

The verified hundred remain the PRIMARY universe — but they are not a
closed world. If a question about an owned player cannot be answered from
them, search reputable readable sources beyond the list: national sports
media, local football reporting, press agencies, club sites, match
reports, team sheets, tactical analysis. Record anything that works:

```bash
python -c "import sys; sys.path.insert(0,'.'); from fpl_assistant.research import sources; \
sources.record_discovered('NAME','domain.com','what it answered', GW)"
```

### Security is EARNED, never assumed

A player is **never** labelled "Secure starter" because a model expects 80
minutes. The default is `Unknown — not yet checked`, and "Secure" has to be
earned by positive evidence: a researched starting call, or a confirmed
recent start.

This exists because of a real failure. Enzo Fernández came on as a
substitute rather than starting the opener, was then omitted from a cup
squad entirely a day after his manager said he expected him to be
involved, with Manchester City interest live — and the page called him a
SECURE STARTER with an empty reasons list, because nothing in our files
contradicted it. Absence of evidence was reading as evidence of security.

Before assigning any minutes status, answer: did he start the last league
game · did he make the latest matchday squad · has he been omitted · is
there an injury · is there transfer speculation · has the manager
discussed him · is there new competition · has his role changed · is
reliable reporting questioning his involvement · is there a match near the
transfer deadline.

**Every minutes call carries a reason.** A label with nothing behind it is
the bug.

### Recency conflict

When a stored expectation says "nailed" and fresh evidence says omitted,
benched, injured, in transfer talks or a manager non-committal, the
dossier raises a **recency conflict** and the fresh evidence wins. Do not
publish the stored label over the top of it.

### Sell urgency FIRST, then a replacement

Transfer logic runs in this order and no other:

1. Score all fifteen owned players 0-5 for sell urgency.
2. Rank them. Identify where the squad genuinely needs improvement.
3. Only then find the best replacement.

Never: find an attractive target, then look for whoever the money works
against. That is how a settled starter in an elite attack gets sold to
fund another midfielder while a player in the middle of a transfer saga is
kept.

`0` no reason · `1` minor concern · `2` monitor · `3` genuine candidate ·
`4` strong sell · `5` urgent. Deliberately blind to the projection — a
projection cannot see an omission, a bid, or a manager declining to commit.

**Protected assets.** A player who starts regularly, plays for a strong
attack, has no injury or transfer concern and holds set-piece duty is
capped at urgency 1. The bar for selling him is high, not average.

**Every transfer must answer "why him and not the other one?"** The
ranking produces that sentence. If the chosen player is not the most
urgent sale, the page says so in writing and challenges the move. A
transfer that cannot survive that sentence is not recommended.

### "Nothing specific" is banned where specific news exists

For each player's CASE FOR SELLING, search for things that WEAKEN him —
not just for articles recommending a sale. Reduced starting certainty, a
squad omission, a transfer situation, uncertainty before a deadline, the
opportunity cost of the money. Those appear even when the verdict is KEEP.

### The final sanity check

Before publishing, ask: *would a knowledgeable FPL manager who read
today's football news look at any label on this page and think it was
obviously wrong?* If yes, research again. The page must never call a
player a secure starter while very recent evidence questions it.

### Fact, inference, unconfirmed — never collapsed

> **FACT** He was omitted from the squad. There is reported interest.
> The manager has not guaranteed his next start.
> **INFERENCE** His expected minutes are therefore less secure.
> **NOT AN INFERENCE** "He definitely won't play."

Grade it instead: `MINUTES: Significant concern`, `TRANSFER: Active talks`.

### The Enzo Fernández standard

Nobody publishes "Enzo Fernández FPL GW2 advice". That is not an absence
of information. Omitted from the squad + active transfer talks + a manager
calling it a selection decision without ruling him out = a **MONITOR**
with an elevated minutes risk, written out in full. Not "no write-up".

### Every player ends with

STATUS · THIS GAMEWEEK · WHY HE'S IN OUR SQUAD · CASE FOR KEEPING · CASE
FOR SELLING · NEXT 3-5 GWs · LATEST DEVELOPMENTS · EXPERT VIEW · RISKS ·
OUR VERDICT (KEEP/SELL/MONITOR/BENCH/CAPTAIN/VICE-CAPTAIN) · CONFIDENCE ·
SOURCES USED.

`analysis/dossier.py` assembles all of it. Fill these fields per player:

```json
"events": [{"kind": "not in squad", "detail": "…", "source": "Chelsea", "when": "22 Aug"}],
"transfer": {"status": "Active talks", "detail": "…"},
"claims": [{"text": "…", "kind": "fact|inference|unconfirmed", "source": "…"}],
"research_depth": "fpl|club news|football news|match evidence|inference"
```

Event kinds: not in squad, benched, started, substituted, injury, returned
to training, suspension, red card, transfer bid, transfer talks, player
wants move, club open to sale, manager quote, position change, set-piece
change, penalty change, new competition for position, teammate injury,
teammate return, new signing, cup minutes, european minutes.

Transfer levels, in order: None · Low-level rumour · Credible interest ·
Active talks · Bid expected · Bid made · Advanced · Transfer imminent ·
Confirmed. Grade it — do not believe it or dismiss it.

**Current news beats the model on minutes.** A statistical estimate
summarises the past; an omission is the present.

### Before publishing — the completeness gate

```bash
python -c "import sys; sys.path.insert(0,'.'); \
from fpl_assistant.research import completeness; print(completeness.CHECKS)"
```

Fourteen checks per owned player: recent news, official club, availability,
latest appearance, expected minutes, transfer situation, tactical role,
this fixture, next 3-5 fixtures, statistics, expert opinion, risks,
keep/sell reasoning, sources. **If a player fails, do not publish — go back
and research him.** The gate names the exact searches that would close his
gaps.

### What changed since last week

Do not regenerate the same profiles. For every player, compare against the
previous gameweek's file and lead with what MOVED: an injury, a transfer
link, an omission, a promotion to starter, a set-piece change, a fixture
swing, a shift in sentiment.

## What to research, per player

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
