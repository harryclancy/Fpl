# FPL Assistant Manager

A weekly dashboard for Fantasy Premier League decisions: fixture runs, form,
captaincy, injuries, and transfer suggestions — built on the free, official
FPL API (no keys required).

## Setup

```bash
pip install -r requirements.txt
```

Optionally set your FPL Team ID so the dashboard can pull your actual squad
(bank, chips, personalised transfer suggestions). Find it in the URL when
viewing your team on fantasy.premierleague.com — the number after `/entry/`,
e.g. `fantasy.premierleague.com/entry/1234567/event/1` → `1234567`.

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
data/cache/        # on-disk API response cache (gitignored)
tests/              # sanity tests against synthetic data, no network needed
```

## Notes on data sources

Everything here comes from the official `fantasy.premierleague.com/api`
endpoints — fixtures, prices, form, ownership, and the editorially
maintained injury/news/chance-of-playing fields. There's no betting-odds or
third-party "expert opinion" integration yet; the fixture-difficulty and
form/xG signals substitute for that for now. If you want to fold in odds or
pundit takes later, the natural place is a new module under `analysis/`
that produces a DataFrame keyed by player or team, the same shape as the
existing ones, so it can slot into the captaincy/transfer scoring.

## Running tests

```bash
pip install pytest
pytest
```
