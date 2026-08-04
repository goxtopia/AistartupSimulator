"""Pydantic request/response schemas for the API layer."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LogoConfig(BaseModel):
    shape: str = "circle"
    icon: str = "brain"
    layout: str = "icon_center"
    palette: str = "midnight"
    monogram: str = ""
    custom_bg: Optional[str] = None
    custom_fg: Optional[str] = None
    custom_accent: Optional[str] = None


class NewGameRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=48)
    country: str
    founder_name: str = Field(..., min_length=1, max_length=40)
    founder_gender: Literal["male", "female", "other"] = "male"
    founder_background: str = "industrialist"
    logo: LogoConfig = Field(default_factory=LogoConfig)
    seed: Optional[int] = None


class SaveGameRequest(BaseModel):
    slot: str = Field(..., min_length=1, max_length=64)
    label: Optional[str] = None


class LoadGameRequest(BaseModel):
    slot: str


class AdvanceRequest(BaseModel):
    days: int = Field(1, ge=1, le=30)


class HireRequest(BaseModel):
    candidate_id: str


class FireRequest(BaseModel):
    employee_id: str


class TrainSkillRequest(BaseModel):
    employee_id: str
    skill: str
    intensity: float = Field(1.0, ge=0.5, le=2.0)


class AssignResearchRequest(BaseModel):
    research_id: str
    category: str  # model | data | compute
    employee_ids: list[str] = Field(default_factory=list)


class StartResearchRequest(BaseModel):
    research_id: str
    category: str
    employee_ids: list[str] = Field(default_factory=list)


class PurchaseComputeRequest(BaseModel):
    chip_id: str
    quantity: int = Field(1, ge=1, le=1000)
    mode: Literal["buy", "cloud"] = "buy"


class CreateDatasetRequest(BaseModel):
    name: str
    use_open_source_base: bool = True
    data_research_weights: dict[str, float] = Field(default_factory=dict)


class StartTrainingRequest(BaseModel):
    name: str
    model_type: str
    params_b: float
    dataset_id: str
    from_scratch: bool = True
    base_model_id: Optional[str] = None  # open-source or own model id for finetune
    expected_days: int = Field(30, ge=1, le=365)
    employee_ids: list[str] = Field(default_factory=list)


class ReleaseModelRequest(BaseModel):
    model_id: str
    open_source: bool = False
    preview: bool = False
    api_enabled: bool = True
    price_input: Optional[float] = None
    price_output: Optional[float] = None


class DistillRequest(BaseModel):
    name: str
    teacher_model_id: str  # own / competitor / open
    teacher_source: Literal["own", "open", "closed_competitor"] = "own"
    params_b: float
    dataset_id: str
    expected_days: int = Field(14, ge=1, le=180)
    employee_ids: list[str] = Field(default_factory=list)


class PoachRequest(BaseModel):
    target_company_id: str
    offer_multiplier: float = Field(1.5, ge=1.0, le=5.0)


class EventChoiceRequest(BaseModel):
    event_instance_id: str
    choice_id: str


class SetApiPriceRequest(BaseModel):
    model_id: str
    price_input: float = Field(..., ge=0.01, le=500)
    price_output: float = Field(..., ge=0.01, le=500)


class ActionResult(BaseModel):
    ok: bool
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    state: Optional[dict[str, Any]] = None
