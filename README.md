# FPL Assistant Manager

A weekly dashboard for Fantasy Premier League decisions: fixture runs, form,
captaincy, injuries, and transfer suggestions — built on the free, official
FPL API (no keys required).

## Setup

```bash
pip install -r requirements.txt
```

Optionally set your FPL Team ID so the dashboard can pull your actual squad
(bank, chips, personalised transfer suggestions). To find it: sign in at
fantasy.premierleague.com, open **Pick Team → Gameweek History**, and check
the URL — it looks like `fantasy.premierleague.com/en/entry/1234567/history`.
The number is your Team ID. (Verify by opening
`fantasy.premierleague.com/api/entry/YOUR-ID/` — it should show your team
name.)

```bash
cp .env.example .env   # then edit FPL_TEAM_ID
```

You can also just type your Team ID into the sidebar each time you run the
dashboard — the `.env` value is only a convenient default.

## Run

```bash
streamlit run fpl_assistant/dashboard/app.py
```

Opens at http://localhost:8501. Tabs:

- **My Squad** (if Team ID set) — current squad, captain, bank, team value
- **Captaincy** — next-gameweek captaincy candidates, scored on form, fixture, and threat
- **Fixtures** — rolling fixture-difficulty ticker, best/worst runs over the next 6 gameweeks
- **Watchlist** — in-form players, best value (points per million), differentials (low ownership)
- **Injuries** — availability news for your squad and league-wide
- **Odds & Expert Take** — this gameweek's betting-market context and pundit/community captaincy consensus (see below)
- **Transfers** (if Team ID set) — flagged weak spots in your squad and affordable replacements

## Project layout

```
fpl_assistant/
  api.py          # FPL API client (cached to disk, see cache.py)
  models.py       # raw JSON -> pandas DataFrames / Squad dataclass
  analysis/
    fixtures.py   # fixture difficulty & run-of-games
    form.py       # in-form / value / differential player lists
    captaincy.py  # captaincy scoring
    transfers.py  # squad weaknesses & replacement suggestions
    injuries.py   # availability flags
  dashboard/
    app.py        # Streamlit UI
  reports.py      # finds/reads the weekly odds & expert-take report (see below)
data/cache/        # on-disk API response cache (gitignored, rebuilds itself)
data/reports/       # weekly odds/expert-take reports, gw{N}.md (committed — see Deploying)
tests/              # sanity tests against synthetic data, no network needed
```

## How much this season counts, and how much last season does

Two gameweeks into a season, the model's biggest risk is believing what it
can see. One match is not a sample, and treating it as one produced a real
failure: after Gameweek 1 of 2026/27 the app sold Haaland, who had taken
five shots without scoring — ignoring that he had just won the Golden Boot
with 27 goals and has been the top-scoring player in the game after six
gameweeks in all four of his seasons at Manchester City.

The projection now carries a prior. Each player's last two completed
seasons sit behind the current one, and how much this season's record is
believed grows with how much of it exists:

| Games played | This season | Last two seasons |
|---|---|---|
| 1  | 14% | 86% |
| 3  | 33% | 67% |
| 6  | 50% | 50% |
| 12 | 67% | 33% |
| 25 | 81% | 19% |

A player with no Premier League record — promoted, newly signed, a
teenager — gets **no prior rather than a prior of zero**. Unknown is not
the same as bad, and scoring it as bad would be the same mistake pointing
the other way.

`data/history/seasons.json` holds the records, refreshed weekly from the
official FPL API by `.github/workflows/history.yml` (free, no key).
`data/history/trends.json` holds what the 2024/25 and 2025/26 seasons
taught, with the concrete rule each lesson implies — the app shows it on
the front page.

## Three words the app uses that don't explain themselves

**Snapshot.** A file recording exactly what the app recommended for a
gameweek, written *before* that gameweek's deadline and never touched
afterwards. It exists because player stats update live: on the Sunday of a
gameweek the model can see who scored on the Saturday, and it will happily
"recommend" them — advice that was impossible at the only moment it could
have been used. The snapshot is the version you could actually have acted
on. It gets rewritten as often as you like while the deadline is still
ahead (late team news is exactly when the advice improves), and is frozen
solid the second the first ball is kicked. It doubles as the receipt the
Track record tab marks the app against.

**Workflow.** A small job GitHub runs on a schedule, on GitHub's own
computers, for free. This repo has one: every three hours it checks
whether a gameweek deadline is coming up, and if so it writes that
gameweek's snapshot and commits it. That's all it does. It matters because
snapshots have to be written before a deadline, and nobody wants to
remember to open the app at 11pm on a Friday to make that happen. It costs
nothing and needs no API key.

**Horizon decay.** Projections run five gameweeks ahead, but the further
out you look the less those numbers are worth — fixtures get rearranged,
players get injured, form turns, and crucially *you get to make the
decision again* before that gameweek arrives. So each week further out is
multiplied by 0.84: next week counts fully, the week after at 84%, the one
after that at 71%, and so on. Without it the optimiser treats a projection
for five weeks' time as being as reliable as one for Saturday, and starts
making expensive moves today for gains that may never materialise.

## Notes on data sources

Fixtures, prices, form, ownership, and the editorially maintained
injury/news/chance-of-playing fields all come straight from the official
`fantasy.premierleague.com/api` — free, no key needed, and reliable enough
to run analysis code against directly.

**Betting odds and expert/community sentiment work differently.** Reddit,
YouTube, and bookmaker sites are generally locked down against scraping
(anti-bot protection, and often against their terms of service), so this
repo doesn't scrape them directly. Instead, each gameweek, ask Claude to
**"refresh the gameweek report"** — it runs live multi-source web research
(major FPL content sites like Fantasy Football Scout, RotoWire, Fantasy
Football Fix/Hub, which themselves aggregate Reddit/YouTube/cross-manager
ownership sentiment) and writes two things to `data/reports/`:

- `gw{N}.md` — the big-picture page shown in the "Odds & Expert Take" tab:
  captaincy consensus, a **Player notes** section with per-player qualitative
  reasoning (why managers/analysts are picking or avoiding them), fixture
  notes, and sources.
- The same file also feeds `analysis/rationale.py`, which cross-references
  each Starting XI pick against the report by name (trying web_name, surname,
  and full name, since FPL's compact `web_name` often won't literally match
  how a report refers to a player) and surfaces the matching line as a
  **"What FPL managers & analysts are saying"** paragraph directly under that
  player's case — so the reasoning blends quantitative signals (price,
  ownership, fixture difficulty, form once the season's under way) with real
  qualitative research, not just one number. Each starter's card also has a
  **"📅 Fixtures & form"** dropdown with their next 5 gameweeks and underlying
  stats, kept separate from the main reasoning so that stays readable.

Treat all of it as directional sentiment, not verified stats or literal
scraped Reddit comments — it's real multi-source research, just relayed
through publications rather than pulled straight from a subreddit thread.

If you later want structured odds numbers feeding directly into the
captaincy/transfer scoring (not just a read-only summary tab), the natural
upgrade is a paid odds API (e.g. the-odds-api.com) — that's a separate
decision since it costs money, and would live as a new module under
`analysis/` producing a DataFrame keyed by player/team, the same shape as
the existing ones.

## Deploying (so you can use it from your phone)

Streamlit Community Cloud hosts this for free and gives you a permanent
URL — no need to keep a computer running:

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. **New app** → pick the `harryclancy/Fpl` repo → branch `claude/fpl-assistant-manager-fjcupn`
   (or `main`, once this is merged) → main file path `fpl_assistant/dashboard/app.py`.
3. Before/after deploying, open **Settings → Secrets** on the app and add:
   ```toml
   FPL_TEAM_ID = "5617068"
   ```
4. Mark the app **private** if you don't want it publicly visible (free tier
   allows one private app); add your own email/Google account under
   **Settings → Sharing** to be able to view it.
5. Deploy. You'll get a URL like `https://your-app-name.streamlit.app` —
   bookmark it on your phone, or add it to your home screen for an app-like
   icon.

The free tier sleeps an app after 12 hours of no visits and wakes it (a
~30 second delay) on the next open — fine for a once-or-twice-a-week check-in.

**To update the live app**: push a commit to the branch it's deployed from
(e.g. after I regenerate `data/reports/gw{N}.md` for a new gameweek) —
Streamlit Cloud redeploys automatically within a minute or two.

## Running tests

```bash
pip install pytest
pytest
```
