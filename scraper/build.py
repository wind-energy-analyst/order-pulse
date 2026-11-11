"""Turn cached releases + extractions into the dashboard dataset.

Quarter logic: a deal belongs to the quarter in which Nordex PUBLISHED the release
(announcement quarter), even if it was firmed in an earlier quarter.

Double-counting guards (each excluded row stays visible in the table with a reason):
  1. intake_summary releases never create deals (they are aggregates); their GW figures are
     kept separately as Nordex's officially reported intake for reconciliation.
  2. framework / "up to" agreements never create deals.
  3. the same release posted twice (e.g. ad hoc + corporate news) is counted once.
  4. orders the release itself flags as previously announced are excluded.
  5. cross-release repeats: same customer (or same wind farm) + same country + MW within 2%
     inside 365 days -> later one excluded as possible duplicate.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASES = ROOT / "data" / "releases"
OUT_DIR = ROOT / "docs" / "data"
OVERRIDES = ROOT / "data" / "overrides.json"


def quarter_of(date_iso: str) -> str:
    d = datetime.fromisoformat(date_iso[:19])
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def norm_title(t: str) -> str:
    return norm(re.sub(r"^\s*Nordex SE:\s*", "", t))


def platform_of(model: str | None) -> tuple[str | None, str | None]:
    """Return (normalized turbine model, family)."""
    if not model:
        return None, None
    if "+" in model:
        return model.strip(), "Mixed"
    m = re.sub(r"\s+", "", model).upper()
    rating = re.search(r"/(\d+(?:\.\d+)?)", m)
    mw = float(rating.group(1)) if rating else 0.0
    mw = mw / 1000 if mw > 100 else mw  # N131/3900 is kW
    family = "Delta4000" if (".X" in m or mw >= 4.0) else "Delta / older"
    return m, family


def parse_period_quarter(period: str) -> str | None:
    m = re.search(r"Q([1-4])\s*[/ -]?\s*(\d{4})|(\d{4})\s*[/ -]?\s*Q([1-4])", period, re.I)
    if not m:
        return None
    q, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    return f"{y}-Q{q}"


def load_releases() -> list[dict]:
    rels = [json.loads(p.read_text()) for p in RELEASES.glob("*.json")]
    return sorted(rels, key=lambda r: r["date"])


def build() -> dict:
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    releases = load_releases()

    # Guard 3: same release published twice
    seen_titles: dict[str, tuple[str, datetime]] = {}
    for r in releases:
        key, d = norm_title(r["title"]), datetime.fromisoformat(r["date"][:19])
        prev = seen_titles.get(key)
        if prev and abs((d - prev[1]).days) <= 3:
            r["duplicate_of"] = prev[0]
        else:
            seen_titles[key] = (r["id"], d)

    deals, intake, warnings = [], {}, []
    for r in releases:
        ex = r.get("extraction")
        if not ex:
            continue
        rtype = ex["release_type"]

        if rtype == "intake_summary" and not r.get("duplicate_of"):
            for f in ex.get("intake_figures", []):
                q = parse_period_quarter(f["period"])
                if q:
                    intake[q] = {"mw": round(f["gw"] * 1000), "source": r["link"], "period": f["period"]}
            continue
        if rtype not in ("single_order", "multi_order"):
            continue

        orders = ex.get("orders", [])
        total = sum(o["mw"] or 0 for o in orders)
        if ex.get("headline_total_mw") and total and abs(total - ex["headline_total_mw"]) / ex["headline_total_mw"] > 0.05:
            warnings.append(f"{r['link']}: orders sum {total} MW vs headline {ex['headline_total_mw']} MW")

        for i, o in enumerate(orders):
            did = f"{r['id']}-{i}"
            o = {**o, **overrides.get(did, {})}  # manual corrections win
            model, family = platform_of(o.get("turbine_model"))
            deal = {
                "id": did,
                "announced": r["date"][:10],
                "quarter": quarter_of(r["date"]),
                "mw": o.get("mw"),
                "mw_approx": bool(o.get("mw_is_approximate")),
                "mw_text": o.get("mw_text"),
                "country": o.get("country") or None,
                "customer": o.get("customer") or None,
                "turbine_model": model,
                "platform_family": family,
                "turbine_count": o.get("turbine_count"),
                "wind_farm": o.get("wind_farm"),
                "firmed_period": o.get("firmed_period_text"),
                "release_type": rtype,
                "title": r["title"],
                "link": r["link"],
                "counted": True,
                "excluded_reason": None,
            }
            if o.get("exclude"):
                deal["counted"], deal["excluded_reason"] = False, o.get("exclude_reason", "manual override")
            elif r.get("duplicate_of"):
                deal["counted"], deal["excluded_reason"] = False, "same release published twice"
            elif o.get("previously_announced"):
                deal["counted"], deal["excluded_reason"] = False, "release says previously announced"
            deals.append(deal)

    # Guard 5: cross-release repeats
    counted = [d for d in deals if d["counted"]]
    for i, d in enumerate(counted):
        if not d["mw"]:
            continue
        for e in counted[:i]:
            if not e["counted"] or not e["mw"] or e["link"] == d["link"]:
                continue
            days = (datetime.fromisoformat(d["announced"]) - datetime.fromisoformat(e["announced"])).days
            same_party = (d["customer"] and norm(d["customer"]) == norm(e["customer"])) or \
                         (d["wind_farm"] and norm(d["wind_farm"]) == norm(e["wind_farm"]))
            if same_party and norm(d["country"]) == norm(e["country"]) and \
               abs(d["mw"] - e["mw"]) / max(e["mw"], 1) <= 0.02 and 0 <= days <= 365:
                d["counted"], d["excluded_reason"] = False, f"possible repeat of {e['announced']} ({e['title'][:60]})"
                break

    # Quarterly rollup
    quarters: dict[str, dict] = {}
    for d in deals:
        q = quarters.setdefault(d["quarter"], {"quarter": d["quarter"], "announced_mw": 0.0, "exact_mw": 0.0,
                                               "approx_mw": 0.0, "deals": 0, "deals_without_mw": 0, "excluded": 0})
        if not d["counted"]:
            q["excluded"] += 1
            continue
        q["deals"] += 1
        if d["mw"] is None:
            q["deals_without_mw"] += 1
            continue
        q["announced_mw"] += d["mw"]
        q["approx_mw" if d["mw_approx"] else "exact_mw"] += d["mw"]
    for k, v in intake.items():
        quarters.setdefault(k, {"quarter": k, "announced_mw": 0.0, "exact_mw": 0.0, "approx_mw": 0.0,
                                "deals": 0, "deals_without_mw": 0, "excluded": 0})
    # fill empty quarters so the chart shows gaps instead of skipping them
    if quarters:
        y, n = map(int, min(quarters).split("-Q"))
        last = quarter_of(datetime.now().isoformat())
        while f"{y}-Q{n}" <= max(max(quarters), last):
            quarters.setdefault(f"{y}-Q{n}", {"quarter": f"{y}-Q{n}", "announced_mw": 0.0, "exact_mw": 0.0,
                                              "approx_mw": 0.0, "deals": 0, "deals_without_mw": 0, "excluded": 0})
            y, n = (y + 1, 1) if n == 4 else (y, n + 1)
    for q in quarters.values():
        for f in ("announced_mw", "exact_mw", "approx_mw"):
            q[f] = round(q[f], 1)
        rep = intake.get(q["quarter"])
        q["reported_intake_mw"] = rep["mw"] if rep else None
        q["reported_intake_source"] = rep["source"] if rep else None
        q["announced_share_of_reported"] = round(q["announced_mw"] / rep["mw"], 3) if rep and rep["mw"] else None

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "releases_scanned": len(releases),
        "releases_extracted": sum(1 for r in releases if r.get("extraction")),
        "pending_extraction": sum(1 for r in releases if r.get("is_candidate") and not r.get("extraction")),
        "quarters": sorted(quarters.values(), key=lambda q: q["quarter"]),
        "deals": sorted(deals, key=lambda d: d["announced"], reverse=True),
        "warnings": warnings,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "deals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    cols = ["announced", "quarter", "mw", "mw_approx", "country", "customer", "turbine_model", "platform_family",
            "turbine_count", "wind_farm", "firmed_period", "counted", "excluded_reason", "title", "link"]
    with open(OUT_DIR / "deals.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out["deals"])
    return out


if __name__ == "__main__":
    o = build()
    print(f"{len(o['deals'])} deals across {len(o['quarters'])} quarters; {len(o['warnings'])} warnings")
