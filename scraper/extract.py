"""LLM extraction of firm orders from one press release.

Default provider: GitHub Models (free, uses the workflow's GITHUB_TOKEN).
Any OpenAI-compatible endpoint works by setting LLM_BASE_URL / LLM_API_KEY / LLM_MODEL,
e.g. Google Gemini: LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
"""
from __future__ import annotations

import json
import os

from openai import OpenAI
from pydantic import ValidationError

from schema import Extraction

BASE_URL = os.getenv("LLM_BASE_URL", "https://models.github.ai/inference")
API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GITHUB_TOKEN")
MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")

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


def _client() -> OpenAI:
    if not API_KEY:
        raise RuntimeError("No LLM_API_KEY / GITHUB_TOKEN set")
    return OpenAI(base_url=BASE_URL, api_key=API_KEY)


def extract(title: str, date: str, text: str, client: OpenAI | None = None) -> Extraction:
    client = client or _client()
    user = f"TITLE: {title}\nPUBLISHED: {date}\n\nTEXT:\n{text}"
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    last_err = None
    for _ in range(2):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            return Extraction.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"That JSON was invalid: {e}. Return corrected JSON only."},
            ]
    raise RuntimeError(f"Extraction failed after retry: {last_err}")
