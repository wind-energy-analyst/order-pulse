"""Offline end-to-end test: fake WP API + fake LLM -> run the real pipeline -> check the rollup.

Run:  python tests/test_pipeline.py
"""
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
FIX = Path(__file__).parent / "fixtures"

import build  # noqa: E402
import extract  # noqa: E402
import fetch  # noqa: E402
import run  # noqa: E402

API_PAGE = json.loads((FIX / "api_page.json").read_text())
ANSWERS = json.loads((FIX / "llm_answers.json").read_text())


def fake_get(url, params=None, headers=None, timeout=None):
    page = (params or {}).get("page", 1)
    after = (params or {}).get("after", "")
    body = [p for p in API_PAGE if p["date"] > after] if page == 1 else []
    return SimpleNamespace(status_code=200, headers={"X-WP-TotalPages": "1"},
                           json=lambda: body, raise_for_status=lambda: None)


class FakeLLM:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.calls = []

    def create(self, model, messages, **kw):
        user = messages[1]["content"]
        self.calls.append(user)
        title = user.split("\n")[0]
        ans = next((v for k, v in ANSWERS.items() if title.startswith(f"TITLE: {k}")),
                   {"release_type": "not_an_order", "orders": []})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(ans)))])


def main():
    tmp = ROOT / "data" / "releases"
    shutil.rmtree(tmp, ignore_errors=True)
    run.BACKFILL_FROM = "2025-01-01"
    run.LLM_PAUSE_S = 0
    fake = FakeLLM()
    with mock.patch.object(fetch.requests, "get", fake_get), \
         mock.patch.object(fetch, "PAUSE_S", 0), \
         mock.patch.object(extract, "_client", lambda: fake):
        run.fetch_new()
        run.extract_pending()
    out = build.build()

    # --- fetch / clean checks
    alb = json.loads((tmp / "204801.json").read_text())
    assert alb["keyword"] == "Incoming Orders", alb["keyword"]
    assert "headquartered" not in alb["text"], "customer About-section must be cut"
    assert "Felix Losada" not in alb["text"], "contacts must be cut"
    br = json.loads((tmp / "204754.json").read_text())
    assert br["is_candidate"] is False, "voting-rights notices must not reach the LLM"
    assert not any("BlackRock" in c for c in fake.calls)

    # --- rollup checks
    q = {x["quarter"]: x for x in out["quarters"]}
    print(json.dumps(q, indent=1))
    assert q["2026-Q4"]["announced_mw"] == 84 + 51.3 + 192, q["2026-Q4"]
    assert q["2026-Q3"]["reported_intake_mw"] == 2800 and q["2026-Q3"]["deals"] == 0, "intake summaries are not deals"
    # 414 MW firmed end-2025 but announced Jan 2026 -> Q1 2026; the UKA recap is excluded as a repeat
    assert q["2026-Q1"]["announced_mw"] == 414 and q["2026-Q1"]["approx_mw"] == 414
    assert q["2025-Q4"]["announced_mw"] == 224.4
    recap = next(d for d in out["deals"] if "recaps" in d["title"])
    assert recap["counted"] is False and "possible repeat" in recap["excluded_reason"]
    vb = next(d for d in out["deals"] if d["customer"] == "VERBUND")
    assert vb["country"] == "Albania" and vb["platform_family"] == "Delta4000"

    # --- encryption: no plaintext left, round trip works, wrong password fails
    import vault
    pw = "test-password-123"
    plain = (ROOT / "docs" / "data" / "deals.json").read_bytes()
    vault.encrypt_dashboard(pw)
    assert not (ROOT / "docs" / "data" / "deals.json").exists() and not (ROOT / "docs" / "data" / "deals.csv").exists()
    blob = json.loads((ROOT / "docs" / "data" / "deals.enc.json").read_text())
    assert vault.decrypt(blob, pw) == plain
    try:
        vault.decrypt(blob, "wrong")
        raise AssertionError("wrong password must fail")
    except Exception as e:
        assert not isinstance(e, AssertionError)
    n = vault.pack_state(pw)
    for p in tmp.glob("*.json"):
        p.unlink()
    assert vault.unpack_state(pw) == n == 9
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
