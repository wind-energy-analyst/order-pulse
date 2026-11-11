"""LLM extraction of firm orders from one press release.

Default provider: Groq free tier (console.groq.com, no credit card), model openai/gpt-oss-120b.
(GitHub Models, the original choice, was retired by GitHub on 30 July 2026.)
Any OpenAI-compatible endpoint works by setting LLM_BASE_URL / LLM_API_KEY / LLM_MODEL,
e.g. Google Gemini: LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
"""
from __future__ import annotations

import json
import os
import re
import time

import requests
from pydantic import ValidationError

from schema import Extraction

BASE_URL = os.getenv("LLM_BASE_URL") or "https://api.groq.com/openai/v1"
API_KEY = os.getenv("LLM_API_KEY")  # never fall back to GITHUB_TOKEN: it must not be sent to a third party
MODEL = os.getenv("LLM_MODEL") or "openai/gpt-oss-120b"
MAX_TEXT_CHARS = 6000  # keeps each call well under the free tier's tokens-per-minute limit

SYSTEM = """You extract FIRM wind turbine orders from Nordex Group press releases.
Return ONLY a JSON object with this shape:

{
  "release_type": "single_order" | "multi_order" | "intake_summary" | "framework_agreement" | "not_an_order",
  "orders": [
    {"mw": number|null, "mw_is_approximate": bool, "mw_text": string|null,
     "turbine_count": int|null, "turbine_model": string|null,
     "country": string|null, "customer": string|null, "wind_farm": string|null,
     "previously_announced": bool, "firmed_period_text": string|null}
  ],
  "intake_figures": [{"period": string, "gw": number}],
  "headline_total_mw": number|null,
  "notes": string|null
}

Rules:
1. release_type:
   - single_order: one firm order (one customer/project, may be several turbines).
   - multi_order: several firm orders in one release (e.g. "orders totalling 414 MW in France, Belgium and Portugal").
   - intake_summary: quarterly/half-year/annual ORDER INTAKE totals (e.g. "order intake rises to 2.8 GW in Q3").
     Put the totals in intake_figures and leave orders EMPTY. Never list individual orders from these, they were
     already announced or are aggregates.
   - framework_agreement: framework, conditional, preferred-supplier, "up to X MW" or "aims to place" agreements
     that are not yet firm. Leave orders EMPTY. BUT if the release ALSO contains firm orders, use single_order/
     multi_order and list only the firm part.
   - not_an_order: everything else (results, acquisitions, voting rights, installations, service-only, commissioning).
     Quarterly RESULTS releases that mention order intake are not_an_order unless the release is primarily about intake.
2. One entry in orders per distinct firm order you can separate. Split by country when the release gives MW per country.
   If only a total is given for several countries/customers, return ONE order with that total and country = the single
   country if there is only one, otherwise a comma-separated list of countries (e.g. "France, Belgium, Portugal").
   The MW values of all orders must add up to the release total; never list a total AND its parts.
3. mw: copy the number as written (convert "1.2 GW" to 1200). Do not compute MW from turbine count.
   mw_is_approximate = true for approx., around, about, nearly, almost, more than, over, some, roughly, c., ~, "up to".
4. country = the PROJECT country, not the customer's home country. English names (Türkiye, United States, etc.).
5. customer = null when the release says the customer is not disclosed or does not name one. Do not guess.
6. turbine_model exactly as written (e.g. "N163/6.X", "N133/4.8"). Several types: join with " + ".
7. previously_announced = true only if the text says the order was announced/reported before.
8. firmed_period_text: when the order was received, if stated ("In December 2025", "end of the year 2025", "in Q2").
9. Use null for anything not stated. Never invent values."""


class RateLimited(Exception):
    """Free-tier quota or requests-per-minute limit reached; resume on the next run."""


class LLMError(Exception):
    pass


def _retry_after(r) -> float | None:
    v = r.headers.get("retry-after") if hasattr(r, "headers") and r.headers else None
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def _chat(messages: list[dict], json_mode: bool = True, _attempt: int = 0) -> str:
    """One OpenAI-compatible chat/completions call with plain HTTP (no SDK, so no version surprises)."""
    if not API_KEY:
        raise LLMError("No LLM_API_KEY set. Add your Groq API key as the repo secret LLM_API_KEY.")
    body = {"model": MODEL, "messages": messages, "temperature": 0}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(
        BASE_URL.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json", "Accept": "application/json"},
        json=body,
        timeout=120,
    )
    if r.status_code == 429:
        wait = _retry_after(r)
        # per-minute limit: wait it out and retry; daily limit (long or unknown wait): stop, resume next run
        if wait is not None and wait <= 90 and _attempt < 3:
            time.sleep(wait + 1)
            return _chat(messages, json_mode, _attempt + 1)
        raise RateLimited(r.text[:300])
    if r.status_code == 400 and json_mode and "response_format" in r.text:
        return _chat(messages, json_mode=False)  # model without JSON mode; the prompt already asks for JSON only
    if r.status_code >= 400:
        raise LLMError(f"HTTP {r.status_code} from {BASE_URL}: {r.text[:300]}")
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except Exception:
        raise LLMError(f"Unexpected response from {BASE_URL}: {r.text[:300]}")


def _parse(raw: str) -> Extraction:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())  # tolerate fenced JSON
    return Extraction.model_validate(json.loads(raw))


def extract(title: str, date: str, text: str) -> Extraction:
    user = f"TITLE: {title}\nPUBLISHED: {date}\n\nTEXT:\n{text[:MAX_TEXT_CHARS]}"
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    last_err = None
    for _ in range(2):
        raw = _chat(messages)
        try:
            return _parse(raw)
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"That JSON was invalid: {e}. Return corrected JSON only."},
            ]
    raise LLMError(f"Invalid JSON after retry: {last_err}")
