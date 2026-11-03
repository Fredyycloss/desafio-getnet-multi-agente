from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ingest import DEFAULT_URLS, ROOT, crawl_official_site


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the committed Getnet official-site knowledge snapshot.")
    parser.add_argument("--max-pages", type=int, default=24)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    pages = crawl_official_site(DEFAULT_URLS, args.max_pages, args.timeout)
    if not pages:
        print("No official pages were fetched. Existing corpus was left unchanged.")
        return 2
    target = ROOT / "site_snapshot.json"
    target.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(pages)} official pages to {target.name}; review changes before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
