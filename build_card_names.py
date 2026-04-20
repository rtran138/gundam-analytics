import json
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUTPUT = Path("assets/card_names.json")
BASE_URL = "https://limitlesstcg.com/bandai/gundam"

SETS = [
    "ST01", "ST02", "ST03", "ST04", "ST05", "ST06", "ST07", "ST08", "ST09",
    "GD01", "GD02", "GD03", "GD04",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_set(set_code: str) -> dict[str, dict]:
    url = f"{BASE_URL}/{set_code}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        print(f"  {set_code}: HTTP {resp.status_code} — skipping")
        return {}

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if not table:
        print(f"  {set_code}: no table found — skipping")
        return {}

    results = {}
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        card_id = cells[0].get_text(strip=True)
        name    = cells[1].get_text(strip=True)
        ctype   = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        color   = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        rarity  = cells[4].get_text(strip=True) if len(cells) > 4 else ""
        if card_id:
            results[card_id] = {
                "name":     name,
                "color":    color,
                "cardType": ctype,
                "rarity":   rarity,
            }
    return results


def build() -> dict[str, dict]:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, dict] = {}

    print(f"Fetching card names from {BASE_URL} ...")
    for set_code in SETS:
        cards = fetch_set(set_code)
        mapping.update(cards)
        print(f"  {set_code}: {len(cards)} cards")
        time.sleep(0.2)

    OUTPUT.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {len(mapping)} total cards -> {OUTPUT}")
    return mapping


def check_coverage(mapping: dict[str, dict]):
    raw_path = Path("data/raw.json")
    if not raw_path.exists():
        return
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    all_ids = {card["card_id"] for deck in raw for card in deck["cards"]}
    missing = sorted(all_ids - mapping.keys())
    print(f"\nCoverage: {len(all_ids) - len(missing)}/{len(all_ids)} card IDs matched")
    if missing:
        print(f"Missing ({len(missing)}):", missing)


if __name__ == "__main__":
    mapping = build()
    check_coverage(mapping)
