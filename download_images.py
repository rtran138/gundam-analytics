import json
import time
from pathlib import Path

import requests

RAW = Path("data/raw.json")
IMG_DIR = Path("assets/card_images")
BASE_URL = "https://deckbuilder.egmanevents.com/card_images/gundam/{card_id}.webp"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def unique_card_ids() -> list[str]:
    data = json.loads(RAW.read_text(encoding="utf-8"))
    ids = {card["card_id"] for deck in data for card in deck["cards"]}
    return sorted(ids)


def download_images():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    card_ids = unique_card_ids()
    total = len(card_ids)
    print(f"Found {total} unique cards. Downloading to {IMG_DIR}/...")

    downloaded = skipped = failed = 0

    for i, card_id in enumerate(card_ids, 1):
        dest = IMG_DIR / f"{card_id}.webp"
        if dest.exists():
            skipped += 1
            continue

        url = BASE_URL.format(card_id=card_id)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                dest.write_bytes(resp.content)
                downloaded += 1
                print(f"  [{i}/{total}] {card_id} OK")
            else:
                failed += 1
                print(f"  [{i}/{total}] {card_id} SKIP (HTTP {resp.status_code})")
        except Exception as e:
            failed += 1
            print(f"  [{i}/{total}] {card_id} ERROR: {e}")

        time.sleep(0.1)

    print(f"\nDone. Downloaded: {downloaded} | Already cached: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    download_images()
