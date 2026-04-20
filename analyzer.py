import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RAW = Path("data/raw.json")
OUTPUT = Path("data/analyzed.json")

# Normalized placement labels in order (best → worst)
PLACEMENTS = ["1st", "2nd", "3rd", "Top 4", "Top 8", "Top 16", "Top 32"]

# Points assigned per placement tier for weighted scoring
PLACEMENT_POINTS = {
    "1st":    7,
    "2nd":    6,
    "3rd":    5,
    "Top 4":  4,
    "Top 8":  3,
    "Top 16": 2,
    "Top 32": 1,
}

ORDINAL_MAP = {
    "1st": "1st", "2nd": "2nd", "3rd": "3rd", "4th": "Top 4",
    "5th": "Top 8", "6th": "Top 8", "7th": "Top 8", "8th": "Top 8",
    "9th": "Top 16", "10th": "Top 16", "11th": "Top 16", "12th": "Top 16",
    "13th": "Top 16", "14th": "Top 16", "15th": "Top 16", "16th": "Top 16",
}


def normalize_placing(raw: str) -> str:
    """
    Convert messy placing strings to a clean PLACEMENTS label.
    Examples:
      "1st (5-0)"   → "1st"
      "!st (3-0)"   → "1st"
      "Top 4 (4-1)" → "Top 4"
      "4-0"         → "1st"   (undefeated record = winner at small events)
      "(4-1)"       → "Top 4" (record only, no label — infer from losses)
    """
    s = raw.strip()

    # Fix common typos
    s = s.replace("!st", "1st")

    # Strip trailing win-loss record like "(5-0)", "(4-1 )", "(4-0 & 3-0)"
    s = re.sub(r"\s*\(.*\)\s*$", "", s).strip()

    # Now check for clean placement labels
    for label in PLACEMENTS:
        if s.lower() == label.lower():
            return label

    # Numeric ordinals: "5th", "12th", etc.
    m = re.match(r"^(\d+)(?:st|nd|rd|th)$", s, re.I)
    if m:
        return ORDINAL_MAP.get(s.lower(), "Top 32")

    # Bare win-loss record with no label remaining, e.g. "4-0" or "5-0"
    if re.match(r"^\d+-\d+$", s):
        wins, losses = map(int, s.split("-"))
        if losses == 0:
            return "1st"
        if losses == 1:
            return "Top 4"
        return "Top 8"

    # "(record)" strings that still survived — infer from losses
    m = re.match(r"^\(?(\d+)-(\d+).*\)?$", raw.strip())
    if m:
        losses = int(m.group(2))
        if losses == 0:
            return "1st"
        if losses == 1:
            return "Top 4"
        return "Top 8"

    return "Top 32"  # fallback


def analyze(decks: list[dict]) -> dict:
    total = len(decks)

    # Normalize placements in-place
    for d in decks:
        d["placing_clean"] = normalize_placing(d["placing"])

    # ── Card-level stats ──────────────────────────────────────────────────────
    card_decks: dict[str, list[dict]] = defaultdict(list)  # card_id → list of deck dicts
    for deck in decks:
        for card in deck["cards"]:
            card_decks[card["card_id"]].append({
                "quantity":    card["quantity"],
                "placing":     deck["placing_clean"],
                "event_type":  deck["event_type"],
                "archetype":   deck["archetype"],
            })

    cards_out = {}
    for card_id, appearances in card_decks.items():
        deck_count = len(appearances)
        total_copies = sum(a["quantity"] for a in appearances)

        # Placement breakdown
        by_placement: dict[str, dict] = defaultdict(lambda: {"decks": 0, "total_copies": 0})
        for a in appearances:
            p = a["placing"]
            by_placement[p]["decks"] += 1
            by_placement[p]["total_copies"] += a["quantity"]

        # Event type breakdown
        by_event: dict[str, dict] = defaultdict(lambda: {"decks": 0, "total_copies": 0})
        for a in appearances:
            e = a["event_type"]
            by_event[e]["decks"] += 1
            by_event[e]["total_copies"] += a["quantity"]

        # Weighted score: sum of placement points across every deck appearance
        weighted_score = sum(
            PLACEMENT_POINTS.get(a["placing"], 0) for a in appearances
        )

        # Archetype spread
        arch_counter: dict[str, int] = defaultdict(int)
        for a in appearances:
            arch_counter[a["archetype"]] += 1

        cards_out[card_id] = {
            "card_id":               card_id,
            "deck_count":            deck_count,
            "appearance_rate":       round(deck_count / total, 4),
            "avg_copies_in_deck":    round(total_copies / deck_count, 2),
            "weighted_score":        weighted_score,
            "by_placement":          {
                p: {
                    "decks": v["decks"],
                    "avg_copies": round(v["total_copies"] / v["decks"], 2),
                }
                for p, v in sorted(
                    by_placement.items(),
                    key=lambda x: PLACEMENTS.index(x[0]) if x[0] in PLACEMENTS else 99,
                )
            },
            "by_event_type":         {
                e: {
                    "decks": v["decks"],
                    "appearance_rate": round(v["decks"] / total, 4),
                }
                for e, v in sorted(by_event.items(), key=lambda x: -x[1]["decks"])
            },
            "top_archetypes":        sorted(arch_counter, key=lambda k: -arch_counter[k])[:5],
        }

    # ── Archetype-level stats ─────────────────────────────────────────────────
    arch_decks: dict[str, list[dict]] = defaultdict(list)
    for deck in decks:
        arch_decks[deck["archetype"]].append(deck)

    archetypes_out = {}
    for arch, arch_deck_list in arch_decks.items():
        count = len(arch_deck_list)
        placement_counter: dict[str, int] = defaultdict(int)
        for d in arch_deck_list:
            placement_counter[d["placing_clean"]] += 1
        archetypes_out[arch] = {
            "archetype":   arch,
            "deck_count":  count,
            "meta_share":  round(count / total, 4),
            "placements":  dict(placement_counter),
            "top_finishes": placement_counter.get("1st", 0) + placement_counter.get("2nd", 0) + placement_counter.get("3rd", 0),
        }

    # ── Placement distribution ────────────────────────────────────────────────
    placement_dist: dict[str, int] = defaultdict(int)
    for d in decks:
        placement_dist[d["placing_clean"]] += 1

    return {
        "meta": {
            "total_decks":            total,
            "total_events":           len({d["event"] for d in decks}),
            "cards_tracked":          len(cards_out),
            "archetypes_tracked":     len(archetypes_out),
            "last_updated":           datetime.now().isoformat(timespec="seconds"),
            "placement_distribution": dict(placement_dist),
        },
        "cards":      cards_out,
        "archetypes": archetypes_out,
    }


def main():
    print(f"Loading {RAW} ...")
    decks = json.loads(RAW.read_text(encoding="utf-8"))
    print(f"Analyzing {len(decks)} decks ...")

    result = analyze(decks)

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved -> {OUTPUT}")

    # Print top 15 cards by weighted score
    cards = sorted(result["cards"].values(), key=lambda c: -c["weighted_score"])
    print(f"\n{'Rank':<5} {'Card ID':<14} {'Decks':>6} {'Rate':>7} {'Wtd Score':>10} {'Avg Copies':>11}")
    print("-" * 58)
    for i, c in enumerate(cards[:15], 1):
        print(
            f"{i:<5} {c['card_id']:<14} {c['deck_count']:>6} "
            f"{c['appearance_rate']:>7.1%} {c['weighted_score']:>10} "
            f"{c['avg_copies_in_deck']:>11.2f}"
        )

    # Print top 10 archetypes by meta share
    archs = sorted(result["archetypes"].values(), key=lambda a: -a["deck_count"])
    print(f"\n{'Archetype':<30} {'Decks':>6} {'Meta%':>7} {'1st/2nd/3rd':>12}")
    print("-" * 58)
    for a in archs[:10]:
        top = a["top_finishes"]
        print(f"{a['archetype']:<30} {a['deck_count']:>6} {a['meta_share']:>7.1%} {top:>12}")


if __name__ == "__main__":
    main()
