"""Data model for one press release and the orders extracted from it."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ReleaseType = Literal[
    "single_order",        # one firm order (may cover several turbines / one wind farm)
    "multi_order",         # several firm orders bundled in one release (roundups by country/region)
    "intake_summary",      # quarterly / annual order intake figures (aggregate, NOT a deal)
    "framework_agreement", # framework / conditional / "up to" agreements, not firm
    "not_an_order",        # results, voting rights, acquisitions, commissioning, etc.
]


class Order(BaseModel):
    mw: Optional[float] = Field(None, description="Capacity of this firm order in MW, as stated. null if not stated.")
    mw_is_approximate: bool = Field(False, description="True if the text says approx., around, about, nearly, more than, almost, some, roughly, etc.")
    mw_text: Optional[str] = Field(None, description="The exact wording the MW figure came from, e.g. 'approx. 154 MW'.")
    turbine_count: Optional[int] = None
    turbine_model: Optional[str] = Field(None, description="Nordex turbine type exactly as written, e.g. 'N163/6.X'. If several types, join with ' + '.")
    country: Optional[str] = Field(None, description="Country in English, e.g. 'Germany', 'Türkiye', 'United States'. null if not disclosed.")
    customer: Optional[str] = Field(None, description="Customer / buyer company name. null if 'not disclosed' or not named.")
    wind_farm: Optional[str] = None
    previously_announced: bool = Field(False, description="True if the release says this order was already announced earlier (e.g. 'as reported in October').")
    firmed_period_text: Optional[str] = Field(None, description="When the order was received/firmed if stated, e.g. 'December 2025', 'Q3 2026', 'end of the year 2025'.")


class IntakeFigure(BaseModel):
    period: str = Field(description="Period the intake refers to, e.g. 'Q3 2026', '9M 2026', 'FY 2025'.")
    gw: float = Field(description="Order intake in GW for that period.")


class Extraction(BaseModel):
    release_type: ReleaseType
    orders: list[Order] = Field(default_factory=list, description="Empty unless release_type is single_order or multi_order.")
    intake_figures: list[IntakeFigure] = Field(default_factory=list, description="Only for intake_summary releases.")
    headline_total_mw: Optional[float] = Field(None, description="Total MW stated in the headline/lead for the whole release, if any.")
    notes: Optional[str] = Field(None, description="One short sentence on anything ambiguous.")
