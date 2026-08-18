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
data/cache/        # on-disk API response cache (gitignored)
data/reports/       # weekly odds/expert-take reports, gw{N}.md (gitignored)
tests/              # sanity tests against synthetic data, no network needed
```

## Notes on data sources

Fixtures, prices, form, ownership, and the editorially maintained
injury/news/chance-of-playing fields all come straight from the official
`fantasy.premierleague.com/api` — free, no key needed, and reliable enough
to run analysis code against directly.

**Betting odds and expert/community sentiment work differently.** Bookmaker
and forum sites are generally locked down against scraping (anti-bot
protection, and often against their terms of service), so this repo doesn't
scrape them. Instead, each gameweek, ask Claude to **"refresh the gameweek
report"** — it runs live web searches for current odds and pundit/community
captaincy takes, synthesises them with sources cited, and writes the result
to `data/reports/gw{N}.md`, which the dashboard's "Odds & Expert Take" tab
then displays. Treat that tab as directional sentiment, not verified stats —
it's a research summary, not scraped raw data.

If you later want structured odds numbers feeding directly into the
captaincy/transfer scoring (not just a read-only summary tab), the natural
upgrade is a paid odds API (e.g. the-odds-api.com) — that's a separate
decision since it costs money, and would live as a new module under
`analysis/` producing a DataFrame keyed by player/team, the same shape as
the existing ones.

## Running tests

```bash
pip install pytest
pytest
```
