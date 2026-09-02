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

from fpl_assistant.analysis import squad_decision as sd
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


def signals_for(player: dict, entry: dict, found) -> sd.PlayerSignals:
    """Turns one player's corpus evidence into the engine's input record."""
    quotes = entry.get("quotes") or []
    text = " ".join(q["text"].lower() for q in quotes)
    items = getattr(found, "substantive_items", [])

    return sd.PlayerSignals(
        name=str(player.get("name", "")),
        club=str(player.get("team", "")),
        position=str(player.get("position", "")),
        price=float(player.get("price", 0) or 0),
        player_id=int(player.get("id", 0) or 0),
        on_bench=bool(player.get("on_bench")),
        is_captain=bool(player.get("is_captain")),
        status=str(player.get("status", "a")),
        chance_of_playing=player.get("chance_of_playing_next_round"),
        projection=float(player.get("projection", 0) or 0),
        points_per_game=float(player.get("points_per_game", 0) or 0),
        evidence_count=len(items),
        source_count=len(entry.get("sources_used") or []),
        positive_quotes=sum(1 for q in quotes if q.get("tone") == "positive"),
        negative_quotes=sum(1 for q in quotes if q.get("tone") == "negative"),
        minutes_assessed="unassessed" not in (entry.get("expected_minutes") or ""),
        team_news_found=any(e.kind == "team news" for e in items),
        injury_talk=any(t in text for t in INJURY),
        omission_talk=any(t in text for t in OMISSION),
        rotation_talk=any(t in text for t in ROTATION),
        transfer_talk=_club_transfer_talk(text),
        set_pieces=any(t in text for t in SET_PIECES),
        penalties=any(t in text for t in PENALTIES),
        latest_evidence=str(entry.get("latest_evidence", "")),
    )


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

    signals = []
    for player in squad:
        name = player["name"]
        found = evidence.search(name, player.get("team", ""), store.items)
        signals.append(signals_for(player, entries.get(name, {}), found))

    decision = sd.decide(signals, targets=[], bank=float(squad_payload.get("bank", 0)),
                         free_transfers=int(squad_payload.get("free_transfers", 1)))

    payload = decision.as_dict()
    payload["note"] = (
        "Transfer decisions, built from the fifteen players owned rather than from "
        "a shopping list. Sell urgency is scored per player from corpus evidence and "
        "official FPL data; no player is protected by name. Rolling the transfer is "
        "scored on the same scale as every move."
    )
    payload["gameweek"] = squad_payload.get("planning_gameweek")
    payload["generated_from_corpus"] = len(store)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")

    print(f"SELL URGENCY RANKING (corpus: {len(store)} articles)\n")
    print(f"{'#':>2}  {'PLAYER':<12}{'POS':<5}{'£':>6}  {'URG':>5}  {'HOLD':>5}  BAND")
    for index, a in enumerate(decision.assessments, 1):
        print(f"{index:>2}. {a.name:<12}{a.signals.position:<5}"
              f"{a.signals.price:>6.1f}  {a.sell_urgency:>5.0f}  "
              f"{a.hold_strength:>5.0f}  {a.band}")
        for reason in a.reasons[:2]:
            print(f"      · {reason}")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
