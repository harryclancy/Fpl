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
from fpl_assistant.analysis import brief as brief_mod
from fpl_assistant.analysis import player_facts as pf
from fpl_assistant.analysis import squad_decision as sd
from fpl_assistant.analysis import strategy as st
from fpl_assistant.analysis import writeup as writeup_mod
from fpl_assistant.analysis.squad_builder import score_players
from fpl_assistant.models import attach_team_names, events_df, fixtures_df, players_df, teams_df
from fpl_assistant.research import corpus as corpus_mod, evidence

ROOT = Path(__file__).resolve().parent.parent
SQUAD = ROOT / "data" / "squad" / "current.json"
WRITEUPS = ROOT / "data" / "research" / "writeups.json"
SEASONS = ROOT / "data" / "history" / "seasons.json"
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
        gameweek_projections=list(live.get("series") or []),
        baseline=float(live.get("baseline", 0) or 0),
        positional_baseline=float(live.get("positional_baseline", 0) or 0),
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

        # The same runs, structured. A write-up cannot say what a
        # fixture MEANS from the string "SUN (H)" — it needs the opponent,
        # the venue and the difficulty as separate facts.
        labels, runs = {}, {}
        for team_id in teams.index:
            run, structured = [], []
            for gw in range(next_event, next_event + 5):
                played = fixtures[
                    (fixtures["event"] == gw)
                    & ((fixtures["team_h"] == team_id) | (fixtures["team_a"] == team_id))
                ]
                for _, fixture in played.iterrows():
                    home = fixture["team_h"] == team_id
                    opponent = fixture["team_a"] if home else fixture["team_h"]
                    short = (teams.loc[opponent, "short_name"]
                             if opponent in teams.index else "?")
                    run.append(f"{short} ({'H' if home else 'A'})")
                    structured.append({
                        "opponent": short, "opponent_id": int(opponent),
                        "home": bool(home),
                        "difficulty": float(fixture["team_h_difficulty"] if home
                                            else fixture["team_a_difficulty"]),
                    })
            labels[team_id] = run
            runs[team_id] = structured

        # Where each side sits in the league for attack and defence, as a
        # percentile rather than FPL's raw 1000-1400 number. A percentile
        # is what lets the prose say "one of the meanest defences in the
        # league" and be held to it, instead of asserting it.
        strength_ranks = _strength_ranks(teams)
    except Exception as exc:
        return None, f"the FPL data could not be assembled ({exc.__class__.__name__}: {exc})"

    # The app's own expected-points model, not FPL's `ep_next`. That field
    # is empty this early in a season, which is why every projection came
    # back zero and the completeness gate correctly refused to certify the
    # run. The model here is the same one the squad optimiser uses, so the
    # transfer engine and the selection engine agree on what a player is
    # worth.
    projections, series_by_id = {}, {}
    try:
        scored = score_players(players_df(bootstrap), fixtures, teams, next_event)
        # The model publishes a per-gameweek series, each entry already
        # adjusted for THAT gameweek's fixture. Carrying it through is the
        # calibration fix: the engine used to take one number and re-shade
        # it by difficulty itself, applying fixtures twice.
        gw_columns = [c for c in scored.columns if c.startswith("xp_gw")]
        gw_columns.sort(key=lambda c: int(c.replace("xp_gw", "")))
        for _, row in scored.iterrows():
            pid = int(row["id"])
            projections[pid] = float(row.get("xp_next", 0) or 0)
            series_by_id[pid] = [float(row.get(c, 0) or 0) for c in gw_columns[:5]]
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
            "series": series_by_id.get(int(element["id"]), []),
            # The player's own recent scoring rate, used to regress a
            # projection that has run far ahead of it.
            "baseline": float(element.get("points_per_game") or 0),
            "element_type": int(element.get("element_type", 0) or 0),
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
            # Underlying rates, for the part of a write-up that asks what
            # he does with the chances rather than whether he gets them.
            "xgi90": float(element.get("expected_goal_involvements_per_90") or 0),
            "xgc90": float(element.get("expected_goals_conceded_per_90") or 0),
            "defcon90": float(element.get("defensive_contribution_per_90") or 0),
            "penalties": _is_taker(element.get("penalties_order")),
            "set_pieces": (_is_taker(element.get("direct_freekicks_order"))
                           or _is_taker(
                               element.get("corners_and_indirect_freekicks_order"))),
            "five_gw": round(sum(series_by_id.get(int(element["id"]), [])[:5]), 2),
            # The real full name, which is what lets the evidence layer
            # tell this player apart from everybody else who shares his
            # web_name. Without it "Nobel Mendy" and "David Raya" look
            # like the same shape of phrase.
            "full_name": " ".join(part for part in (
                str(element.get("first_name") or ""),
                str(element.get("second_name") or "")) if part).strip(),
        }
        by_id[int(element["id"])] = record
        by_name[str(element.get("web_name", ""))] = record

    # The median scoring rate per position, among players who have
    # actually featured. This is what a thin sample is shrunk toward.
    medians = {}
    for kind in POSITIONS:
        rates = sorted(r["points_per_game"] for r in by_id.values()
                       if r.get("element_type") == kind and r["minutes"] >= 180)
        medians[kind] = rates[len(rates) // 2] if rates else 0.0
    for record in by_id.values():
        record["positional_baseline"] = medians.get(record.get("element_type", 0), 0.0)

    # The same idea for the underlying rates, so "well clear of a typical
    # midfielder" is measured against the league rather than asserted.
    rate_medians = {}
    for kind in POSITIONS:
        for key in ("xgi90", "defcon90", "five_gw"):
            values = sorted(r[key] for r in by_id.values()
                            if r.get("element_type") == kind and r["minutes"] >= 180)
            rate_medians[(kind, key)] = (values[len(values) // 2]
                                         if values else 0.0)

    return {
        "by_id": by_id, "by_name": by_name, "team_games": team_games,
        "positional_medians": medians,
        "next_event": next_event, "fixture_table": table, "teams": teams,
        "fixture_labels": labels, "fixture_runs": runs,
        "strength_ranks": strength_ranks,
        "rate_medians": rate_medians,
    }, ""


def _fixture_label(live, player: dict) -> str:
    labels = _fixture_labels(live, player, 1)
    return labels[0] if labels else ""


def _fixture_labels(live, player: dict, count: int) -> list[str]:
    record = live["by_id"].get(int(player.get("id", 0) or 0)) or {}
    team_id = record.get("team")
    return list(live.get("fixture_labels", {}).get(team_id, []))[:count]


def last_season(name: str, club: str) -> tuple[int, int]:
    """Minutes and appearances in the last completed season, at THIS club.

    The record is keyed by the club the player is at now, so a player who
    has moved does not match and correctly comes back with nothing —
    which is the behaviour we want. A season built somewhere else is not
    evidence about the shirt he is wearing today.
    """
    try:
        payload = json.loads(SEASONS.read_text())
    except (OSError, json.JSONDecodeError):
        return 0, 0
    for record in payload.get("players", []):
        if record.get("name") != name or record.get("team") != club:
            continue
        seasons = record.get("seasons") or []
        if not seasons:
            return 0, 0
        latest = seasons[0]
        return (int(latest.get("minutes", 0) or 0),
                int(latest.get("appearances", 0) or 0))
    return 0, 0


def joined_recently(facts) -> str:
    """A published line saying he has changed clubs, or nothing.

    Detected from what someone actually wrote rather than inferred from a
    thin appearance count, because "he has not played much" and "he is
    new here" call for different write-ups and only one of them is a
    reason to distrust his previous record.
    """
    return _first_claim(facts, pf.ARRIVAL)


def brief_inputs(facts, signal, player: dict, live, rec, assessments,
                 squad: list[dict], plans) -> "brief_mod.BriefInputs":
    """Assembles everything one judgement is allowed to use.

    Every field is sourced rather than assumed: the fixture run and the
    opponents' strength from the official data, the prior season from the
    committed history, the transfer status from something a journalist
    wrote, and the alternatives from the plans the transfer engine
    actually built and refused. Nothing here is a placeholder.
    """
    record = {}
    if live:
        record = live["by_id"].get(int(player.get("id", 0) or 0)) \
            or live["by_name"].get(signal.name, {})
    team_id = record.get("team")
    kind = record.get("element_type", 0)
    ranks = (live or {}).get("strength_ranks", {})
    medians = (live or {}).get("rate_medians", {})

    fixtures = []
    for entry in ((live or {}).get("fixture_runs", {}).get(team_id) or [])[:5]:
        fixtures.append(brief_mod.Fixture(
            opponent=entry["opponent"], home=entry["home"],
            difficulty=entry["difficulty"]))

    club_short = str(record.get("club") or signal.club)
    minutes, appearances = last_season(signal.name, club_short)
    joined = joined_recently(facts)

    opponent_id = (((live or {}).get("fixture_runs", {}).get(team_id) or [{}])[0]
                   .get("opponent_id") if fixtures else None)
    mine = ranks.get(team_id, {})
    theirs = ranks.get(opponent_id, {}) if opponent_id is not None else {}

    return brief_mod.BriefInputs(
        player=signal.name, club=club_short,
        club_name=_club_name(live, team_id) or club_short,
        position=signal.position, price=signal.price,
        starts=int(record.get("starts", 0) or 0),
        minutes_played=int(record.get("minutes", 0) or 0),
        team_games=int((live or {}).get("team_games", 0) or 0),
        status=str(record.get("status", "a") or "a"),
        chance_of_playing=record.get("chance_of_playing_next_round"),
        minutes_category=signal.minutes_category,
        prior_minutes=minutes, prior_appearances=appearances,
        new_club_evidence=joined,
        rotation_evidence=_first_claim(facts, pf.ROTATION),
        injury_evidence=_first_claim(facts, pf.INJURY),
        transfer_evidence="" if joined else _first_claim(facts, pf.TRANSFER),
        fixtures=fixtures,
        team_attack_rank=mine.get("attack"), team_defence_rank=mine.get("defence"),
        opponent_attack_rank=theirs.get("attack"),
        opponent_defence_rank=theirs.get("defence"),
        points_per_game=float(record.get("points_per_game", 0) or 0),
        positional_ppg=float(record.get("positional_baseline", 0) or 0),
        total_points=int(record.get("total_points", 0) or 0),
        xgi90=float(record.get("xgi90", 0) or 0),
        positional_xgi90=float(medians.get((kind, "xgi90"), 0) or 0),
        xgc90=float(record.get("xgc90", 0) or 0),
        defcon90=float(record.get("defcon90", 0) or 0),
        set_pieces=bool(record.get("set_pieces")),
        penalties=bool(record.get("penalties")),
        projection=float(record.get("projection", 0) or 0),
        five_gw=float(record.get("five_gw", 0) or 0),
        positional_five_gw=float(medians.get((kind, "five_gw"), 0) or 0),
        on_bench=bool(player.get("on_bench")),
        captain=bool(player.get("is_captain")),
        vice=bool(player.get("is_vice_captain")),
        being_sold=signal.name in rec.out_names,
        sell_urgency=next((a.sell_urgency for a in assessments
                           if a.name == signal.name), 0.0),
        hold_strength=next((a.hold_strength for a in assessments
                            if a.name == signal.name), 0.0),
        bench_alternatives=_bench_alternatives(signal, player, squad, live),
        transfer_alternatives=_transfer_alternatives(signal, plans),
    )


def _club_name(live, team_id) -> str:
    teams = (live or {}).get("teams")
    if teams is None or team_id not in teams.index:
        return ""
    return str(teams.loc[team_id, "name"])


def _bench_alternatives(signal, player: dict, squad: list[dict],
                        live) -> list:
    """Who he is actually picked ahead of, or behind — same position only.

    A comparison against a player who cannot fill his slot is not a
    comparison, and "he starts" without one is a statement rather than a
    decision.
    """
    if not live:
        return []
    # A starter is measured against the BENCH he is picked ahead of; a
    # benched player against the eleven he is behind. The comparison was
    # the wrong way round, so a starting forward was told another
    # starting forward projected higher — true, irrelevant, and not a
    # selection decision he can act on.
    wanted = not player.get("on_bench")
    others = []
    for other in squad:
        if other["name"] == signal.name or other.get("position") != signal.position:
            continue
        if bool(other.get("on_bench")) != wanted:
            continue
        record = live["by_id"].get(int(other.get("id", 0) or 0)) \
            or live["by_name"].get(other["name"], {})
        runs = live.get("fixture_runs", {}).get(record.get("team")) or []
        detail = ""
        if runs:
            games = int(live.get("team_games", 0) or 0)
            detail = (f"{int(record.get('starts', 0) or 0)} of {games} started, "
                      f"{runs[0]['opponent']} "
                      f"{'at home' if runs[0]['home'] else 'away'}")
        others.append(brief_mod.Alternative(
            name=other["name"], detail=detail,
            five_gw=float(record.get("five_gw", 0) or 0)))
    others.sort(key=lambda a: a.five_gw, reverse=True)
    return others[:2]


def _transfer_alternatives(signal, plans) -> list:
    """The replacement the engine actually costed, and what it decided.

    Taken off the plans rather than invented, so a write-up that raises a
    better-looking option can also say what happened to it — which is the
    difference between analysis and a loose end.
    """
    found = []
    for plan in plans:
        for move in plan.moves:
            if move.out_name != signal.name:
                continue
            reason = ""
            if plan.rejection_reasons:
                reason = plan.rejection_reasons[0].split(": ", 1)[-1]
            found.append(brief_mod.Alternative(
                name=move.in_name, five_gw=move.in_5gw,
                rejected_because=reason))
    found.sort(key=lambda a: a.five_gw, reverse=True)
    return found[:1]


def brief_quality(judgement) -> list[str]:
    """The user's own final test, run before anything is saved.

    A write-up that fails these is not shipped with a caveat — it is
    reported as a quality problem and fails the completeness gate, the
    same as any other bad output.
    """
    problems = []
    if not judgement.why:
        problems.append("the brief does not say why he is in the team")
    if not judgement.case_for:
        problems.append("the brief makes no case for him")
    if len(judgement.against.split()) < 8:
        problems.append("the brief has no real case against him")
    if not judgement.verdict_label:
        problems.append("the brief reaches no decision")
    if "\u2192" not in judgement.verdict:
        problems.append("the brief does not look past this gameweek")
    if not (brief_mod.MIN_WORDS <= judgement.words <= brief_mod.MAX_WORDS):
        problems.append(
            f"the brief is {judgement.words} words, outside "
            f"{brief_mod.MIN_WORDS}-{brief_mod.MAX_WORDS}")
    return problems


def _first_claim(facts, *buckets) -> str:
    for claim in facts.claims:
        if claim.player_named and set(buckets) & set(claim.buckets):
            return claim.text
    return ""


def _is_taker(order) -> bool:
    """FPL publishes a set-piece ORDER; anything but first choice is noise."""
    try:
        return int(order) <= 2
    except (TypeError, ValueError):
        return False


def _strength_ranks(teams) -> dict:
    """Each side's attack and defence as a 0-1 position in the league.

    Averaged across home and away, because a write-up's claim about a
    club ("one of the meanest defences") is a claim about the side, not
    about one venue — the venue is already in the fixture difficulty.
    """
    ranks = {}
    for kind, columns in (
            ("attack", ("strength_attack_home", "strength_attack_away")),
            ("defence", ("strength_defence_home", "strength_defence_away"))):
        values = {}
        for team_id in teams.index:
            row = teams.loc[team_id]
            numbers = [float(row[c]) for c in columns
                       if c in teams.columns and row[c] == row[c]]
            if numbers:
                values[team_id] = sum(numbers) / len(numbers)
        if not values:
            continue
        order = sorted(values, key=lambda t: values[t])
        last = len(order) - 1
        for position, team_id in enumerate(order):
            # A higher FPL strength is a better side, for both attack and
            # defence, so a high rank means "good at this" either way.
            ranks.setdefault(team_id, {})[kind] = (
                position / last if last else 0.5)
    return ranks


def _fixture_scores(live, team_id) -> list[float]:
    if team_id is None:
        return []
    return list(live["fixture_table"].get(team_id, []))[:5]


KIND_MAP = {pf.FACT: st.FACT, pf.STATISTICAL: st.STATISTIC,
            pf.EXPERT: st.EXPERT, pf.INFERENCE: st.INFERENCE}


def reasons_from(facts: pf.PlayerFacts) -> list[st.Reason]:
    """Turns one player's structured facts into arguments about HIM.

    Every claim already survived player_facts.classify, which drops
    anything not about this player. What is added here is the level: a
    claim drawn from the fixture, team-strength or clean-sheet buckets is
    true of the whole club, so it cannot separate two of its players.
    """
    reasons = []
    for claim in facts.claims:
        if not claim.player_named:
            continue
        level = (st.CLUB_LEVEL if set(claim.buckets) & pf.CLUB_LEVEL_BUCKETS
                 else st.PLAYER_LEVEL)
        reasons.append(st.Reason(
            text=claim.text, about=facts.player, level=level,
            kind=KIND_MAP.get(claim.kind, st.INFERENCE),
            direction=claim.direction, source=claim.source))
    return reasons


def squad_state(squad_payload: dict, squad: list[dict]) -> st.SquadState:
    """The real state, or an honest record of what is missing from it.

    Selling price, not market price: FPL returns only half of any rise
    since purchase, so a plan costed on the listed value can be
    unaffordable in reality. A zero here makes the state incomplete rather
    than silently substituting the market price.
    """
    selling, purchase = {}, {}
    for player in squad:
        name = player["name"]
        selling[name] = float(player.get("selling_price") or 0.0)
        purchase[name] = float(player.get("purchase_price") or 0.0)
    return st.SquadState(
        bank=float(squad_payload.get("bank", 0) or 0),
        free_transfers=int(squad_payload.get("free_transfers", 1) or 1),
        event=int(squad_payload.get("planning_gameweek", 0) or 0),
        squad_size=len(squad), selling_values=selling,
        purchase_values=purchase,
        selling_basis=str(squad_payload.get("selling_value_basis") or "unknown"))


def legacy_view(rec: st.Recommendation) -> tuple[dict, list[dict]]:
    """The old winner/options shape, DERIVED from the one recommendation.

    Not a second engine. Every field here is read off `rec`, so the older
    parts of the page cannot disagree with the newer ones — which is
    precisely how the page once printed ROLL at the top and "make the
    move" three sections down.
    """
    def as_option(plan: st.Plan) -> dict:
        move = plan.moves[0] if plan.moves else None
        return {
            "kind": "roll" if plan.kind == "roll" else "transfer",
            "label": plan.label,
            "classification": plan.kind.title(),
            "out": move.out_name if move else "",
            "in": move.in_name if move else "",
            "gain_this_gw": round(plan.gain_gw1, 2),
            "gain_3gw": round(plan.gain_3gw, 2),
            "gain_5gw": round(plan.gross_5gw, 2),
            "gross_gain_5gw": round(plan.gross_5gw, 2),
            "hit_points": plan.hit,
            "net_gain_5gw": plan.net_5gw,
            "bank_after": plan.bank_after,
            "hits": plan.paid_transfers,
            "rejected": plan.rejected,
            "rejection_reason": "; ".join(plan.rejection_reasons),
            "score": plan.net_5gw,
            "confidence": plan.confidence,
            "reasons": plan.notes + [r.text for m in plan.moves for r in m.reasons][:3],
            "risks": plan.rejection_reasons,
            "components": {},
        }

    return as_option(rec.winner), [as_option(p) for p in
                                   [rec.winner] + rec.alternatives + rec.rejected]


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

    # THE DIAGNOSIS COMES FIRST. Nothing about the market has been read
    # at this point, so the squad is graded on its own merits rather than
    # against whatever happens to look exciting this week.
    assessments = sd.rank(signals)

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
                gameweek_projections=list(record.get("series") or []),
                baseline=float(record.get("baseline", 0) or 0),
                positional_baseline=float(record.get("positional_baseline", 0) or 0),
                appearances=int(record.get("appearances", 0) or 0),
                team_games=live["team_games"],
                source_count=1,
                fixture_scores=_fixture_scores(live, record.get("team")),
            ))

    # Structured facts, then prose from them. The homepage renders only
    # from this, so an article sentence about one player cannot reach
    # another player's card.
    facts_out, quality, target_facts_out, built = {}, {}, {}, {}
    reasons: list[st.Reason] = []
    for signal, player in zip(signals, squad):
        entry = entries.get(signal.name, {})
        live_record = {}
        if live:
            live_record = live["by_id"].get(int(player.get("id", 0) or 0)) \
                or live["by_name"].get(signal.name, {})
        assessment = pf.build(
            signal.name, signal.club, signal.position, signal.price,
            full_name=str(live_record.get("full_name") or ""),
            quotes=entry.get("quotes") or [],
            availability=(pf.OUT if signal.flagged else
                          pf.DOUBT if signal.minutes_category in
                          ("Significant concern", "Major doubt") else pf.FIT),
            expected_minutes=signal.minutes_category,
            sell_urgency=next((a.sell_urgency for a in assessments
                               if a.name == signal.name), 0.0),
            sell_band=next((a.band for a in assessments
                            if a.name == signal.name), ""),
            fixture=_fixture_label(live, player) if live else "",
            next_fixtures=_fixture_labels(live, player, 4) if live else [],
            form=(f"{signal.points_per_game:.1f} points a game this season"
                  if signal.points_per_game else ""),
            starting=not player.get("on_bench"),
            captain=bool(player.get("is_captain")),
            vice=bool(player.get("is_vice_captain")),
        )
        built[signal.name] = assessment
        reasons.extend(reasons_from(assessment))


    # The same treatment for every realistic target, so a move is argued
    # from evidence about BOTH players or from neither.
    for target in targets:
        found = evidence.search(target.name, target.club, store.items)
        # The same sentence extraction the squad's write-ups use, so an
        # incoming player is argued from published prose rather than from
        # headlines — and, like theirs, only from sentences that name him.
        target_full = str((live["by_name"].get(target.name, {}) if live
                           else {}).get("full_name") or "")
        quotes = writeup_mod.quotes_for(target.name, target.club,
                                        found.substantive_items, target_full)
        target_facts = pf.build(
            target.name, target.club, target.position, target.price,
            full_name=target_full,
            quotes=[q.as_dict() for q in quotes[:12]],
            expected_minutes=target.minutes_category,
            fixture="", form="")
        target.source_count = len({c.source for c in target_facts.claims}) or 1
        reasons.extend(reasons_from(target_facts))
        target_facts_out[target.name] = target_facts.as_dict()

    # --- one state, one decision ---------------------------------------
    state = squad_state(squad_payload, squad)
    plans = st.generate_plans(assessments, targets, state, reasons)
    rec = st.choose(plans, state)
    explanation = st.explain(rec)

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
        "15/15 sell urgency scores": len(assessments) == len(squad) == 15,
        "Real selling prices for all 15": state.complete,
        "Roll transfer included": any(p.kind == "roll" for p in plans),
        "5-GW comparison calculated": all(
            p.gross_5gw is not None for p in plans),
        "Every plan's arithmetic verified": all(
            not st.verify_arithmetic(p) for p in plans if not p.rejected),
        "Exactly one recommendation": rec.winner is not None,
    }

    # THE WRITE-UPS ARE COMPOSED LAST, FROM THE DECISION.
    # This is the ordering that makes a contradiction impossible rather
    # than detectable: a card cannot say "the one to move on" while the
    # plan keeps him, because the verdict it renders is read off the plan
    # instead of being computed a second time from the same evidence.
    for name, assessment in built.items():
        if name in rec.out_names:
            assessment.verdict = pf.SELL_VERDICT
            line = "Selling him this week — see the transfer plan above."
        elif rec.incomplete:
            line = "No transfer decision this week."
        else:
            if assessment.verdict == pf.SELL_VERDICT:
                assessment.verdict = (pf.MONITOR if assessment.sell_urgency >= 45
                                      else pf.KEEP)
            line = "Keeping him this week."
        record = assessment.as_dict()
        record["decision_line"] = line

        # THE JUDGEMENT. Built last, from the decision and from every
        # structured input the run has — the fixture and its difficulty,
        # the opponent's strength, last season at THIS club, the bench
        # player he is picked ahead of, the transfer the engine costed and
        # refused. The research is the input; this is the conclusion.
        signal = next(s for s in signals if s.name == name)
        owner = next(p for p in squad if p["name"] == name)
        judgement = brief_mod.build(brief_inputs(
            assessment, signal, owner, live, rec, assessments, squad, plans))
        record["brief"] = judgement.as_dict()

        # The old one-paragraph form stays as the compact summary shown
        # above the fold; the brief is what opens underneath it.
        record["prose"] = writeup_mod.from_facts(assessment)
        problems = writeup_mod.quality_check(assessment)
        problems += brief_quality(judgement)
        if problems:
            quality[name] = problems
        facts_out[name] = record

    # --- the write-ups must agree with the decision --------------------
    # Generated last, scanned before anything is written. A page whose
    # prose argues with its own recommendation is not published.
    blocks = [(f"{name} write-up", record.get("prose", ""))
              for name, record in facts_out.items() if isinstance(record, dict)]
    blocks.extend((f"decision {key}", value) for key, value in explanation.items())
    squad_names = set(built)
    clashes = st.contradictions(rec, blocks, squad_names)
    audit = st.trust_audit(rec, blocks, squad_names)
    checks["Every write-up passes its own quality test"] = not quality
    checks["No text contradicts the recommendation"] = not clashes
    checks["Manual trust audit passed"] = st.audit_passed(audit)
    complete = all(checks.values())

    winner_view, option_views = legacy_view(rec)
    payload = {
        "sell_urgency_ranking": [a.as_dict() for a in assessments],
        "recommendation": rec.as_dict(),
        "explanation": explanation,
        "trust_audit": [{"question": q, "passed": ok, "detail": detail}
                        for q, ok, detail in audit],
        "contradictions": clashes,
        # Derived from the recommendation above, never computed separately,
        # so the older sections of the page cannot disagree with it.
        "winner": winner_view,
        "options": option_views,
        "sanity_checks": rec.notes,
    }
    payload["note"] = (
        "One decision, chosen between complete plans rather than between individual "
        "swaps. Every plan carries its own hit, its own bank and its own free "
        "transfers, and any plan that fails one of the twelve rejection rules is out "
        "rather than shown with a caveat. Evidence may only argue for a move if it is "
        "about one of the two players in it."
    )
    payload["gameweek"] = squad_payload.get("planning_gameweek")
    payload["generated_from_corpus"] = len(store)
    payload["completeness"] = {"complete": complete, "checks": checks,
                               "live_data_error": live_error}
    # A league-wide sanity view. The distribution is where an inflated
    # model shows itself: a defender above the best forward, or a
    # non-playing squad filler in the top ten, is visible here long before
    # it reaches a recommendation.
    if live:
        market = []
        for name, record in live["by_name"].items():
            series = record.get("series") or []
            if not series:
                continue
            market.append({
                "player": name, "club": record.get("club", ""),
                "position": record.get("position", ""),
                "price": record.get("price", 0.0),
                "five_gw": round(sum(series[:5]), 2),
                "per_gw": round(series[0], 2),
                "minutes": record.get("minutes", 0),
                "sample": record.get("minutes_category", ""),
            })
        by_position = {}
        for position, top in (("GKP", 10), ("DEF", 15), ("MID", 15), ("FWD", 10)):
            ranked = sorted((m for m in market if m["position"] == position),
                            key=lambda m: m["five_gw"], reverse=True)
            by_position[position] = ranked[:top]
        payload["market_projections"] = by_position

    if live:
        payload["team_strength"] = {
            str(live["teams"].loc[team_id, "short_name"]): {
                "attack_rank": round(kinds.get("attack", 0.0), 3),
                "defence_rank": round(kinds.get("defence", 0.0), 3)}
            for team_id, kinds in live.get("strength_ranks", {}).items()
            if team_id in live["teams"].index}
    payload["player_facts"] = facts_out
    payload["target_facts"] = target_facts_out
    payload["quality_problems"] = quality

    payload["projection_audit"] = {
        s.name: {
            "series": s.gameweek_projections,
            "baseline_ppg": s.baseline,
            "shrunk_baseline": sd.shrunk_baseline(s),
            "positional_median": s.positional_baseline,
            "regressed_to": sd.regress(s)[0],
            "regression_note": sd.regress(s)[1],
            "news_discount": round(sd.news_discount(s), 3),
            "confidence": sd.projection_confidence(s),
            "horizon": sd.horizon_points(s),
            "five_gw_total": round(sum(sd.horizon_points(s)), 2),
        }
        for s in signals}
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
    for index, a in enumerate(assessments, 1):
        s = a.signals
        print(f"{index:>2}. {a.name:<12}{s.position:<5}{s.price:>6.1f}"
              f"{s.points_per_game:>6.1f}{s.projection:>6.1f}  "
              f"{a.sell_urgency:>4.0f}{a.hold_strength:>6.0f}  "
              f"{s.minutes_category:<20} {a.band}")
    print("\nTHE DECISION")
    print(f"  {explanation['headline']}")
    for key in ("problem", "gain", "cost", "changes"):
        if explanation.get(key):
            print(f"    {key}: {explanation[key]}")
    if rec.alternatives:
        print("\n  Alternatives considered")
        for plan in rec.alternatives[:4]:
            print(f"    {plan.label:<40} net {plan.net_5gw:+6.2f} over 5 GW")
    if rec.rejected:
        print(f"\n  Rejected plans: {len(rec.rejected)}")
        for plan in rec.rejected[:5]:
            print(f"    {plan.label:<40} {plan.rejection_reasons[0]}")

    print("\nMANUAL TRUST AUDIT")
    for question, passed, detail in audit:
        print(f"  [{'x' if passed else ' '}] {question}")
        print(f"      {detail}")
    if clashes:
        print("\nCONTRADICTIONS")
        for clash in clashes:
            print(f"  - {clash}")
    if not st.audit_passed(audit):
        print("\nDO NOT SHIP — the trust audit did not pass.")

    print(f"\nWrote {OUT}")
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
