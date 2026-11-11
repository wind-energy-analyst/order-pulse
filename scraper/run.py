"""Daily pipeline: fetch new releases -> LLM-extract candidates -> rebuild dashboard data.

Usage:
  python scraper/run.py                 # normal daily run
  python scraper/run.py --no-fetch      # only extract pending + rebuild
  python scraper/run.py --reextract     # clear cached extractions (after prompt change), then extract again
Env:
  BACKFILL_FROM   first date to fetch when the cache is empty (default 2024-01-01)
  MAX_LLM_CALLS   cap per run so the free tier is never exceeded (default 40); the rest resumes next run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RELEASES = ROOT / "data" / "releases"
BACKFILL_FROM = os.getenv("BACKFILL_FROM", "2024-01-01")
MAX_LLM_CALLS = int(os.getenv("MAX_LLM_CALLS", "40"))
LLM_PAUSE_S = float(os.getenv("LLM_PAUSE_S", "6"))  # stay under free-tier requests/minute


def _path(rid: str) -> Path:
    return RELEASES / f"{rid}.json"


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def fetch_new() -> int:
    from fetch import iter_posts

    RELEASES.mkdir(parents=True, exist_ok=True)
    dates = [json.loads(p.read_text())["date"] for p in RELEASES.glob("*.json")]
    if dates:
        after = (datetime.fromisoformat(max(dates)) - timedelta(days=14)).isoformat()  # re-check recent edits
    else:
        after = f"{BACKFILL_FROM}T00:00:00"
    print(f"[fetch] posts after {after}")
    n = 0
    for post in iter_posts(after=after):
        if post["date"] < f"{BACKFILL_FROM}T00:00:00":
            break
        post["text_hash"] = _hash(post["text"])
        p = _path(post["id"])
        if p.exists():
            old = json.loads(p.read_text())
            if old.get("text_hash") == post["text_hash"]:
                continue
            print(f"[fetch] changed: {post['title'][:70]}")
        post["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        p.write_text(json.dumps(post, indent=1, ensure_ascii=False))
        n += 1
    print(f"[fetch] {n} new/changed releases")
    return n


def extract_pending() -> int:
    from extract import MODEL, RateLimited, extract

    pending = []
    for p in sorted(RELEASES.glob("*.json")):
        r = json.loads(p.read_text())
        if r.get("is_candidate") and not r.get("extraction"):
            pending.append((p, r))
    pending.sort(key=lambda x: x[1]["date"], reverse=True)  # newest first
    print(f"[extract] {len(pending)} pending, cap {MAX_LLM_CALLS}")
    done, fails_in_a_row = 0, 0
    for p, r in pending[:MAX_LLM_CALLS]:
        try:
            ex = extract(r["title"], r["date"], r["text"])
        except RateLimited as e:
            print(f"[extract] rate limited; stopping, will resume next run. {e}")
            break
        except Exception as e:  # keep going on single failures
            print(f"[extract] FAILED {r['title'][:60]}: {e}")
            fails_in_a_row += 1
            if fails_in_a_row >= 3 and done == 0:
                print("[extract] 3 failures in a row before any success: the error looks systematic, stopping "
                      "to save the free quota. Fix the error above and run again.")
                break
            time.sleep(LLM_PAUSE_S)
            continue
        fails_in_a_row = 0
        r["extraction"] = ex.model_dump()
        r["extraction_model"] = MODEL
        r["extracted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        p.write_text(json.dumps(r, indent=1, ensure_ascii=False))
        done += 1
        print(f"[extract] {ex.release_type:20s} {len(ex.orders)} orders  {r['title'][:60]}")
        time.sleep(LLM_PAUSE_S)
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-extract", action="store_true")
    ap.add_argument("--reextract", action="store_true")
    a = ap.parse_args()

    import vault
    pw = vault.password()
    if os.getenv("REQUIRE_PASSWORD") == "true" and not pw:
        sys.exit("DASHBOARD_PASSWORD secret is not set. Refusing to run so no plaintext data is published.")
    if pw:
        print(f"[vault] restored {vault.unpack_state(pw)} cached releases")

    if a.reextract:
        for p in RELEASES.glob("*.json"):
            r = json.loads(p.read_text())
            r.pop("extraction", None)
            p.write_text(json.dumps(r, indent=1, ensure_ascii=False))
    if not a.no_fetch:
        fetch_new()
    if not a.no_extract:
        extract_pending()
    out = build.build()
    (ROOT / "data" / "last_run.txt").write_text(out["generated_at"] + "\n")  # heartbeat keeps the schedule alive
    if pw:
        vault.encrypt_dashboard(pw)
        print(f"[vault] encrypted dashboard data and {vault.pack_state(pw)} cached releases")
    print(f"[build] {len(out['deals'])} deals, {out['pending_extraction']} pending, {len(out['warnings'])} warnings")


if __name__ == "__main__":
    main()
