"""Runs the transfer decision engine on the committed squad and corpus.

Everything it reads is already in the repository: the squad the workflow
fetched, the corpus the research pipeline collected, and the write-ups
Stage B composed. It writes data/research/decision.json, which the
homepage renders.

    python scripts/decide_transfers.py [--gameweek N]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fpl_assistant import api
from fpl_assistant.analysis import fixtures as fixtures_analysis
from fpl_assistant.analysis import minutes as minutes_mod
from fpl_assistant.analysis import squad_decision as sd
from fpl_assistant.analysis.squad_builder import score_players
from fpl_assistant.models import attach_team_names, events_df, fixtures_df, players_df, teams_df
from fpl_assistant.research import corpus as corpus_mod, evidence

ROOT = Path(__file__).resolve().parent.parent
SQUAD = ROOT / "data" / "squad" / "current.json"
WRITEUPS = ROOT / "data" / "research" / "writeups.json"
OUT = ROOT / "data" / "research" / "decision.json"

# Terms that say a specific thing happened, used to set the event flags the
# urgency model reads. Kept here rather than in the engine so the engine
# stays a scoring function over evidence, testable without any corpus.
INJURY = ("injury", "injured", "ruled out", "sidelined", "hamstring",
          "a knock", "undergo a scan", "surgery", "fitness doubt",
          "major doubt", "is a doubt", "out for")
OMISSION = ("omitted", "left out", "not in the squad", "dropped", "excluded")
ROTATION = ("rotation", "rotated", "rested", "squad depth")
# A CLUB transfer, not an FPL one. "Transfer" is the most overloaded word
# in this corpus: every FPL article is about transfers, so matching the
# bare word flagged Haaland and Ndiaye as transfer-linked on the strength
# of "whether to roll a transfer". Real club-transfer reporting uses a
# narrower vocabulary, and the FPL sense is excluded explicitly.
TRANSFER = ("bid for", "a bid", "medical", "release clause", "agreed terms",
            "transfer fee", "move to join", "set to join", "completed a move",
            "transfer request", "asking price", "swoop", "linked with a move")
FPL_TRANSFER_SENSE = ("free transfer", "roll a transfer", "roll the transfer",
                      "transfers in", "transfers out", "transferred in",
                      "transferred out", "transfer tips", "wildcard",
                      "take a hit", "your transfer", "one transfer")
SET_PIECES = ("set piece", "corner", "free kick", "dead ball")
# How many replacement candidates to carry per position. Enough to give the
# engine a real choice; small enough that the comparison stays readable.
TARGETS_PER_POSITION = 6
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
PENALTIES = ("penalt", "spot kick", "from the spot")


def _club_transfer_talk(text: str) -> bool:
    """Is a real club transfer being reported, or just FPL housekeeping?"""
    if not any(term in text for term in TRANSFER):
        return False
    # If the only transfer language present is the FPL sense, it is not a
    # transfer situation — it is an article about using your free transfer.
    return not all(
        any(sense in sentence for sense in FPL_TRANSFER_SENSE)
        for sentence in text.split(".")
        if any(term in sentence for term in TRANSFER)
    )


def signals_for(player: dict, entry: dict, found, live: dict | None = None,
                fixture_scores: list[float] | None = None,
                team_games: int = 0) -> sd.PlayerSignals:
    """Corpus evidence plus live FPL data, as the engine's input record.

    `live` is the player's row from the official bootstrap. Without it the
    output is evidence-only and the completeness gate below will say so
    rather than presenting the ranking as final.
    """
    quotes = entry.get("quotes") or []
    text = " ".join(q["text"].lower() for q in quotes)
    items = getattr(found, "substantive_items", [])

    live = live or {}
    injury = any(t in text for t in INJURY)
    omission = any(t in text for t in OMISSION)
    rotation = any(t in text for t in ROTATION)
    club_transfer = _club_transfer_talk(text)
    team_news = any(e.kind == "team news" for e in items)

    assessment = minutes_mod.assess(
        starts=int(live.get("starts", 0) or 0),
        appearances=int(live.get("appearances", 0) or 0),
        minutes=int(live.get("minutes", 0) or 0),
        team_games=team_games,
        status=str(player.get("status", "a")),
        chance_of_playing=live.get("chance_of_playing_next_round"),
        injury_talk=injury, omission_talk=omission, rotation_talk=rotation,
        transfer_talk=club_transfer,
        positive_team_news=team_news and not injury,
    )

    return sd.PlayerSignals(
        name=str(player.get("name", "")),
        club=str(player.get("team", "")),
        position=str(player.get("position", "")),
        price=float(player.get("price", 0) or 0),
        player_id=int(player.get("id", 0) or 0),
        on_bench=bool(player.get("on_bench")),
        is_captain=bool(player.get("is_captain")),
        status=str(live.get("status", player.get("status", "a"))),
        chance_of_playing=live.get("chance_of_playing_next_round"),
        projection=float(live.get("projection", 0) or 0),
        form=float(live.get("form", 0) or 0),
        points_per_game=float(live.get("points_per_game", 0) or 0),
        total_points=int(live.get("total_points", 0) or 0),
        starts=int(live.get("starts", 0) or 0),
        appearances=int(live.get("appearances", 0) or 0),
        minutes_played=int(live.get("minutes", 0) or 0),
        team_games=team_games,
        minutes_category=assessment.category,
        minutes_confidence=assessment.confidence,
        fixture_scores=list(fixture_scores or []),
        evidence_count=len(items),
        source_count=len(entry.get("sources_used") or []),
        positive_quotes=sum(1 for q in quotes if q.get("tone") == "positive"),
        negative_quotes=sum(1 for q in quotes if q.get("tone") == "negative"),
        minutes_assessed=assessment.assessed,
        team_news_found=team_news,
        injury_talk=injury,
        omission_talk=omission,
        rotation_talk=rotation,
        transfer_talk=club_transfer,
        set_pieces=any(t in text for t in SET_PIECES),
        penalties=any(t in text for t in PENALTIES),
        latest_evidence=str(entry.get("latest_evidence", "")),
    )


def _live_data():
    """The official FPL picture, or a stated reason it is unavailable.

    Reads `bootstrap["elements"]` directly rather than the trimmed
    players_df, because the fields this engine needs — `starts`, `ep_next`,
    `minutes`, `form` — are native FPL columns that players_df does not
    carry. The first production run failed here silently: the script raised
    before writing its output, so the committed decision file was the stale
    local one and the completeness gate reported on the wrong data.

    Every failure returns a reason instead of propagating, so the gate can
    say what was missing rather than the job dying with a traceback.
    """
    try:
        bootstrap = api.get_bootstrap_static()
    except Exception as exc:
        return None, f"the FPL API is unreachable from here ({exc.__class__.__name__})"

    try:
        fixtures = fixtures_df(api.get_fixtures())
        teams = teams_df(bootstrap)
        events = events_df(bootstrap)

        finished = events[events["finished"] == True] if "finished" in events else events.iloc[:0]
        team_games = int(len(finished))
        upcoming = events[events["finished"] != True] if "finished" in events else events
        next_event = int(upcoming.iloc[0]["id"]) if len(upcoming) else 1
        # Difficulty per team for the next five gameweeks, built here from
        # the fixtures frame rather than read out of team_fixture_table.
        # That table's cells are opponent LABELS ("CHE (H)") with the
        # numbers in a parallel set of columns — the first production run
        # died on float("CHE (H)"). Computing it directly cannot break on
        # a column-naming assumption.
        table = {}
        for team_id in teams.index:
            run = []
            for gw in range(next_event, next_event + 5):
                played = fixtures[
                    (fixtures["event"] == gw)
                    & ((fixtures["team_h"] == team_id) | (fixtures["team_a"] == team_id))
                ]
                if played.empty:
                    continue
                scores = []
                for _, fixture in played.iterrows():
                    home = fixture["team_h"] == team_id
                    scores.append(float(
                        fixture["team_h_difficulty"] if home
                        else fixture["team_a_difficulty"]))
                run.append(sum(scores) / len(scores))
            table[team_id] = run
    except Exception as exc:
        return None, f"the FPL data could not be assembled ({exc.__class__.__name__}: {exc})"

    # The app's own expected-points model, not FPL's `ep_next`. That field
    # is empty this early in a season, which is why every projection came
    # back zero and the completeness gate correctly refused to certify the
    # run. The model here is the same one the squad optimiser uses, so the
    # transfer engine and the selection engine agree on what a player is
    # worth.
    projections = {}
    try:
        scored = score_players(players_df(bootstrap), fixtures, teams, next_event)
        for _, row in scored.iterrows():
            projections[int(row["id"])] = float(row.get("xp_next", 0) or 0)
    except Exception as exc:
        return None, f"the projection model failed ({exc.__class__.__name__}: {exc})"

    by_name, by_id = {}, {}
    for element in bootstrap.get("elements", []):
        minutes_played = int(element.get("minutes", 0) or 0)
        starts = int(element.get("starts", 0) or 0)
        candidate_minutes = minutes_mod.assess(
            starts=starts,
            appearances=max(starts, 1 if minutes_played else 0),
            minutes=minutes_played, team_games=team_games,
            status=element.get("status", "a"),
            chance_of_playing=element.get("chance_of_playing_next_round"),
        )
        record = {
            "status": element.get("status", "a"),
            "chance_of_playing_next_round": element.get("chance_of_playing_next_round"),
            "projection": projections.get(int(element["id"]), 0.0),
            "form": float(element.get("form") or 0),
            "points_per_game": float(element.get("points_per_game") or 0),
            "total_points": int(element.get("total_points", 0) or 0),
            "minutes": minutes_played,
            "starts": starts,
            # FPL does not publish an appearance count. Starts plus a
            # single substitute appearance is the closest honest proxy.
            "appearances": max(starts, 1 if minutes_played else 0),
            "team": element.get("team"),
            "price": float(element.get("now_cost", 0) or 0) / 10.0,
            "position": POSITIONS.get(int(element.get("element_type", 0) or 0), ""),
            "club": str(teams.loc[element["team"], "short_name"])
            if element.get("team") in teams.index else "",
            "minutes_category": candidate_minutes.category,
            "minutes_confidence": candidate_minutes.confidence,
        }
        by_id[int(element["id"])] = record
        by_name[str(element.get("web_name", ""))] = record

    return {
        "by_id": by_id, "by_name": by_name, "team_games": team_games,
        "next_event": next_event, "fixture_table": table, "teams": teams,
    }, ""


def _fixture_scores(live, team_id) -> list[float]:
    if team_id is None:
        return []
    return list(live["fixture_table"].get(team_id, []))[:5]


def main() -> int:
    try:
        squad_payload = json.loads(SQUAD.read_text())
        writeups = json.loads(WRITEUPS.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error title=Missing inputs::{exc}")
        return 1

    squad = squad_payload.get("squad", [])
    store = corpus_mod.load()
    entries = writeups.get("players", {})
    live, live_error = _live_data()

    signals = []
    for player in squad:
        name = player["name"]
        found = evidence.search(name, player.get("team", ""), store.items)
        record = {}
        fixture_scores = []
        if live:
            record = live["by_id"].get(int(player.get("id", 0) or 0)) \
                or live["by_name"].get(name, {})
            fixture_scores = _fixture_scores(live, record.get("team"))
        try:
            signals.append(signals_for(
                player, entries.get(name, {}), found, record, fixture_scores,
                live["team_games"] if live else 0))
        except Exception as exc:
            # One malformed player must not cost the whole run its output.
            # The completeness gate will report the shortfall.
            print(f"::warning title=Signal build failed::{name}: "
                  f"{exc.__class__.__name__}: {exc}")
            signals.append(sd.PlayerSignals(
                name=name, club=str(player.get("team", "")),
                position=str(player.get("position", "")),
                price=float(player.get("price", 0) or 0)))

    # Realistic replacements. The engine tests every target against every
    # plausible seller, so the pool only needs to be the players who could
    # actually be bought: best projected in each position, inside the money
    # the squad could raise, and not already owned.
    bank = float(squad_payload.get("bank", 0))
    owned = {s.name for s in signals}
    ceiling = bank + max((s.price for s in signals), default=0.0)
    targets = []
    if live:
        pool = sorted(live["by_name"].items(),
                      key=lambda kv: float(kv[1].get("projection", 0) or 0),
                      reverse=True)
        per_position = {}
        for name, record in pool:
            if name in owned or record.get("status") != "a":
                continue
            if float(record.get("price", 0) or 0) > ceiling:
                continue
            position = record.get("position", "")
            if len(per_position.get(position, [])) >= TARGETS_PER_POSITION:
                continue
            per_position.setdefault(position, []).append(name)
            targets.append(sd.PlayerSignals(
                name=name, club=str(record.get("club", "")), position=position,
                price=float(record.get("price", 0) or 0),
                projection=float(record.get("projection", 0) or 0),
                points_per_game=float(record.get("points_per_game", 0) or 0),
                minutes_category=record.get("minutes_category", "Unassessed"),
                minutes_confidence=record.get("minutes_confidence", 0.6),
                source_count=1,
                fixture_scores=_fixture_scores(live, record.get("team")),
            ))

    decision = sd.decide(signals, targets=targets, bank=bank,
                         free_transfers=int(squad_payload.get("free_transfers", 1)))

    # --- the completeness gate -----------------------------------------
    # A ranking computed on zeros is not a result. Rather than presenting
    # one, the run says exactly which inputs were missing.
    assessed = sum(1 for s in signals if s.minutes_category != "Unassessed")
    checks = {
        "Real FPL data loaded": bool(live),
        "Real current squad loaded": len(squad) == 15,
        "Fixtures loaded": bool(live) and any(s.fixture_scores for s in signals),
        "No projections replaced by zero": all(s.projection > 0 for s in signals),
        "Expected minutes assessed for the majority": assessed > len(signals) / 2,
        "15/15 sell urgency scores": len(decision.assessments) == len(squad) == 15,
        "Roll transfer included": any(o.kind == "roll" for o in decision.options),
        "3-GW comparison calculated": all(
            hasattr(o, "gain_3gw") for o in decision.options),
        "5-GW comparison calculated": all(
            hasattr(o, "gain_5gw") for o in decision.options),
        "Budget effects calculated": all(
            o.kind != "transfer" or o.bank_after is not None for o in decision.options),
    }
    complete = all(checks.values())

    payload = decision.as_dict()
    payload["note"] = (
        "Transfer decisions built from the fifteen players owned rather than from a "
        "shopping list. Sell urgency is scored per player from live FPL data and "
        "corpus evidence; no player is protected by name. Rolling is scored on the "
        "same scale as every move."
    )
    payload["gameweek"] = squad_payload.get("planning_gameweek")
    payload["generated_from_corpus"] = len(store)
    payload["completeness"] = {"complete": complete, "checks": checks,
                               "live_data_error": live_error}
    payload["minutes"] = {
        s.name: {"category": s.minutes_category, "starts": s.starts,
                 "minutes": s.minutes_played, "team_games": s.team_games,
                 "confidence": s.minutes_confidence}
        for s in signals}
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")

    print("COMPLETENESS GATE")
    for label, passed in checks.items():
        print(f"  [{'x' if passed else ' '}] {label}")
    if live_error:
        print(f"  live data: {live_error}")
    if not complete:
        print("\nTRANSFER ENGINE TEST INCOMPLETE — the ranking below is not authoritative.")
    print()

    print(f"SELL URGENCY RANKING (corpus: {len(store)} articles, "
          f"{live['team_games'] if live else 0} team games played)\n")
    print(f"{'#':>2}  {'PLAYER':<12}{'POS':<5}{'£':>6}{'PPG':>6}{'PROJ':>6}  "
          f"{'URG':>4}{'HOLD':>6}  {'MINUTES':<20} BAND")
    for index, a in enumerate(decision.assessments, 1):
        s = a.signals
        print(f"{index:>2}. {a.name:<12}{s.position:<5}{s.price:>6.1f}"
              f"{s.points_per_game:>6.1f}{s.projection:>6.1f}  "
              f"{a.sell_urgency:>4.0f}{a.hold_strength:>6.0f}  "
              f"{s.minutes_category:<20} {a.band}")
    print(f"\nWrote {OUT}")
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
