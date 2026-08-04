"""HTTP API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Header

from backend.app.engine.game import get_engine
from backend.app.models.schemas import (
    AdvanceRequest,
    AssignResearchRequest,
    CreateDatasetRequest,
    DistillRequest,
    EventChoiceRequest,
    FireRequest,
    HireRequest,
    LoadGameRequest,
    NewGameRequest,
    PoachRequest,
    PurchaseComputeRequest,
    ReleaseModelRequest,
    SaveGameRequest,
    SetApiPriceRequest,
    StartResearchRequest,
    StartTrainingRequest,
    TrainSkillRequest,
)

router = APIRouter()


def _gid(x_game_id: str | None) -> str:
    if not x_game_id:
        raise HTTPException(400, "缺少 X-Game-Id 头")
    return x_game_id


@router.get("/health")
def health():
    return {"ok": True, "service": "ai-startup-simulator"}


@router.get("/catalog")
def catalog():
    return get_engine().catalog()


@router.post("/game/new")
def new_game(body: NewGameRequest):
    try:
        state = get_engine().new_game(body.model_dump())
        return {"ok": True, "state": state}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/game/state")
def game_state(x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    gid = _gid(x_game_id)
    state = get_engine().get_state(gid)
    if not state:
        raise HTTPException(404, "会话不存在")
    return {"ok": True, "state": state}


@router.post("/game/advance")
def advance(body: AdvanceRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    gid = _gid(x_game_id)
    try:
        state = get_engine().advance(gid, body.days)
        return {"ok": True, "state": state}
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/game/save")
def save_game(body: SaveGameRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    gid = _gid(x_game_id)
    try:
        return get_engine().save(gid, body.slot, body.label)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e)) from e


@router.post("/game/load")
def load_game(body: LoadGameRequest):
    try:
        state = get_engine().load(body.slot)
        return {"ok": True, "state": state}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/game/saves")
def list_saves():
    return {"ok": True, "saves": get_engine().list_saves()}


@router.delete("/game/saves/{slot}")
def delete_save(slot: str):
    ok = get_engine().delete_save(slot)
    if not ok:
        raise HTTPException(404, "存档不存在")
    return {"ok": True}


def _act(gid: str, action: str, payload: dict[str, Any]):
    try:
        return get_engine().action(gid, action, payload)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/hr/refresh")
def hr_refresh(x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "refresh_candidates", {})


@router.post("/hr/hire")
def hr_hire(body: HireRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "hire", body.model_dump())


@router.post("/hr/fire")
def hr_fire(body: FireRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "fire", body.model_dump())


@router.post("/hr/train")
def hr_train(body: TrainSkillRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "train_skill", body.model_dump())


@router.post("/hr/poach")
def hr_poach(body: PoachRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "poach", body.model_dump())


@router.post("/research/start")
def research_start(body: StartResearchRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "start_research", body.model_dump())


@router.post("/research/assign")
def research_assign(body: AssignResearchRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "assign_research", body.model_dump())


@router.post("/research/pause")
def research_pause(body: dict, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "pause_research", body)


@router.post("/compute/purchase")
def compute_purchase(body: PurchaseComputeRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "purchase_compute", body.model_dump())


@router.post("/training/dataset")
def create_dataset(body: CreateDatasetRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "create_dataset", body.model_dump())


@router.post("/training/start")
def start_training(body: StartTrainingRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "start_training", body.model_dump())


@router.post("/training/assign")
def assign_training(body: dict, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "assign_training", body)


@router.post("/training/distill")
def distill(body: DistillRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "distill", body.model_dump())


@router.post("/training/release")
def release_model(body: ReleaseModelRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "release_model", body.model_dump())


@router.post("/training/price")
def set_price(body: SetApiPriceRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "set_api_price", body.model_dump())


@router.post("/events/choose")
def event_choose(body: EventChoiceRequest, x_game_id: str | None = Header(default=None, alias="X-Game-Id")):
    return _act(_gid(x_game_id), "event_choice", body.model_dump())
