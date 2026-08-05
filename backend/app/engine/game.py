"""Game engine orchestrator — wires systems, ticks, save/load."""

from __future__ import annotations

import copy
import json
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.app.core.config_loader import SAVES_DIR, get_configs
from backend.app.engine.effects import DefaultEffectApplier
from backend.app.engine.interfaces.base import IGameContext, SystemRegistry
from backend.app.engine.systems.competitors import CompetitorsSystem
from backend.app.engine.systems.compute import ComputeSystem
from backend.app.engine.systems.events import EventSystem
from backend.app.engine.systems.finance import FinanceSystem
from backend.app.engine.systems.hr import HRSystem
from backend.app.engine.systems.market import MarketSystem
from backend.app.engine.systems.research import ResearchSystem
from backend.app.engine.systems.training import TrainingSystem


BASE_CAPITAL = 1_000_000


class GameContext(IGameContext):
    def __init__(self, engine: "GameEngine") -> None:
        self._engine = engine

    def configs(self):
        return self._engine.configs

    def rng(self):
        return self._engine.rng

    def effects(self):
        return self._engine.effects

    def get_system(self, name: str):
        return self._engine.systems.get(name)

    def log(self, message: str, *, level: str = "info", category: str = "game") -> None:
        self._engine.append_log(message, category=category)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self._engine.pending_emits.append({"type": event_type, "payload": payload or {}})


class GameEngine:
    """In-memory multi-session game host.

    Each browser session gets a game_id. State is a plain dict for easy JSON
    save/load. Systems are cohesive and communicate only via state + context.
    """

    def __init__(self) -> None:
        self.configs = get_configs()
        self.effects = DefaultEffectApplier()
        self.systems = SystemRegistry()
        self._register_systems()
        self.sessions: dict[str, dict[str, Any]] = {}
        self.rng = random.Random()
        self.pending_emits: list[dict] = []
        self._lock = threading.RLock()
        SAVES_DIR.mkdir(parents=True, exist_ok=True)

    def _register_systems(self) -> None:
        # Order matters for ticks:
        # competitors before market (models must exist); after HR helpers available at init
        for sys in (
            HRSystem(),
            CompetitorsSystem(),
            ResearchSystem(),
            ComputeSystem(),
            TrainingSystem(),
            MarketSystem(),
            FinanceSystem(),
            EventSystem(),
        ):
            self.systems.register(sys)

    # ---------- session lifecycle ----------

    def new_game(self, req: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            seed = req.get("seed")
            if seed is None:
                seed = int(time.time() * 1000) % (2**31)
            self.rng = random.Random(seed)

            country_id = req["country"]
            countries = self.configs.load("countries").get("countries", {})
            if country_id not in countries:
                raise ValueError(f"未知国家: {country_id}")
            country = countries[country_id]

            bg_id = req.get("founder_background", "industrialist")
            backgrounds = self.configs.load("founder_backgrounds").get("backgrounds", {})
            if bg_id not in backgrounds:
                raise ValueError(f"未知背景: {bg_id}")
            bg = backgrounds[bg_id]

            capital = BASE_CAPITAL * float(country.get("starting_capital_multiplier", 1.0))
            mods = bg.get("starting_modifiers", {})
            capital = capital * float(mods.get("capital_multiplier", 1.0)) + float(mods.get("capital_bonus", 0))

            logo = req.get("logo") or {}
            game_id = str(uuid.uuid4())
            state: dict[str, Any] = {
                "game_id": game_id,
                "seed": seed,
                "day": 0,
                "version": 1,
                "company": {
                    "name": req["company_name"],
                    "country": country_id,
                    "country_name": country.get("name"),
                    "logo": logo,
                    "capital": round(capital, 2),
                    "founder": {
                        "name": req["founder_name"],
                        "gender": req.get("founder_gender", "male"),
                        "background": bg_id,
                        "background_name": bg.get("name"),
                        "stats": bg.get("stats", {}),
                    },
                    "founder_background_cfg": {
                        "research_speed_multiplier": bg.get("research_speed_multiplier", 1.0),
                        "recruit_cost_multiplier": bg.get("recruit_cost_multiplier", 1.0),
                        "unlock_tags": bg.get("unlock_tags", []),
                    },
                    "tendencies": {
                        "openness": 30 + float(mods.get("openness_bonus", 0)),
                        "gov_relation": float(country.get("starting_gov_relation", 20))
                        + float(mods.get("gov_relation_bonus", 0)),
                        "public_rep": float(country.get("starting_public_rep", 20))
                        + float(mods.get("public_rep_bonus", 0)),
                        "transparency": 25.0,
                        "innovation": 20 + float(mods.get("innovation_bonus", 0)),
                    },
                    "modifiers": {},
                },
                "log": [
                    {
                        "day": 0,
                        "msg": f"{req['company_name']} 在{country.get('name')}成立。创始人：{req['founder_name']}（{bg.get('name')}）",
                        "cat": "system",
                    }
                ],
                "meta": {"created_at": time.time(), "updated_at": time.time()},
            }

            ctx = GameContext(self)
            # Init order: HR first (person generator), then competitors, then the rest.
            # Registration order already encodes this.
            for sys in self.systems.all():
                sys.on_new_game(state, ctx)

            self.sessions[game_id] = state
            return self.public_state(game_id)

    def get_state(self, game_id: str) -> dict[str, Any] | None:
        with self._lock:
            if game_id not in self.sessions:
                return None
            return self.public_state(game_id)

    def advance(self, game_id: str, days: int = 1) -> dict[str, Any]:
        with self._lock:
            state = self._require(game_id)
            # Block if unresolved mandatory events? allow soft block only when queue full
            ctx = GameContext(self)
            tick_events: list[dict] = []
            for _ in range(days):
                state["day"] = int(state.get("day", 0)) + 1
                for sys in self.systems.all():
                    evs = sys.on_tick(state, ctx, days=1) or []
                    tick_events.extend(evs)
                # bankrupt check
                if float(state["company"].get("capital", 0)) < -500_000:
                    state["company"]["bankrupt"] = True
                    state.setdefault("log", []).append(
                        {"day": state["day"], "msg": "公司资不抵债，濒临破产！", "cat": "system"}
                    )
                    break
            state["meta"]["updated_at"] = time.time()
            state["_last_tick_events"] = tick_events[-30:]
            return self.public_state(game_id)

    # ---------- actions (delegate) ----------

    def action(self, game_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self._require(game_id)
            ctx = GameContext(self)
            ok, msg, data = True, "", {}

            hr: HRSystem = self.systems.get("hr")  # type: ignore
            research: ResearchSystem = self.systems.get("research")  # type: ignore
            compute: ComputeSystem = self.systems.get("compute")  # type: ignore
            training: TrainingSystem = self.systems.get("training")  # type: ignore
            market: MarketSystem = self.systems.get("market")  # type: ignore
            finance: FinanceSystem = self.systems.get("finance")  # type: ignore
            events: EventSystem = self.systems.get("events")  # type: ignore

            if action == "refresh_candidates":
                cands = hr.refresh_candidates(state, ctx, count=5)
                cost = 5000
                state["company"]["capital"] -= cost
                ok, msg, data = True, "人才市场已刷新", {"candidates": cands}
            elif action == "hire":
                ok, msg, emp = hr.hire(state, ctx, payload["candidate_id"])
                data = {"employee": emp}
            elif action == "fire":
                ok, msg = hr.fire(state, payload["employee_id"])
            elif action == "train_skill":
                ok, msg = hr.train_skill(
                    state, ctx, payload["employee_id"], payload["skill"], float(payload.get("intensity", 1.0))
                )
            elif action == "set_chief_scientist":
                ok, msg, chief = hr.set_chief_scientist(state, payload.get("employee_id"))
                data = {"chief_scientist": chief}
            elif action == "set_auto_hire":
                ok, msg, automation = hr.set_auto_hire(
                    state,
                    ctx,
                    bool(payload.get("enabled", True)),
                    int(payload.get("max_hires_per_cycle", 3)),
                )
                data = {"automation": automation}
            elif action == "poach":
                ok, msg, emp = hr.try_poach(
                    state, ctx, payload["target_company_id"], float(payload.get("offer_multiplier", 1.5))
                )
                data = {"employee": emp}
            elif action == "start_research":
                ok, msg, job = research.start(
                    state,
                    ctx,
                    payload["research_id"],
                    payload.get("category") or "model",
                    payload.get("employee_ids") or [],
                )
                data = {"job": job}
            elif action == "assign_research":
                ok, msg, job = research.assign(
                    state,
                    ctx,
                    payload["research_id"],
                    payload.get("category"),
                    payload.get("employee_ids") or [],
                )
                data = {"job": job}
            elif action == "pause_research":
                ok, msg = research.pause(state, payload["research_id"])
            elif action == "set_research_auto":
                ok, msg, automation = research.set_auto(
                    state,
                    ctx,
                    payload["research_id"],
                    payload.get("category") or "model",
                    bool(payload.get("enabled", True)),
                )
                data = {"automation": automation}
            elif action == "purchase_compute":
                ok, msg = compute.purchase(
                    state, ctx, payload["chip_id"], int(payload.get("quantity", 1)), payload.get("mode", "buy")
                )
            elif action == "create_dataset":
                ok, msg, ds = training.create_dataset(
                    state,
                    ctx,
                    payload["name"],
                    bool(payload.get("use_open_source_base", True)),
                    payload.get("data_research_weights") or {},
                    payload.get("employee_ids") or [],
                    int(payload.get("expected_days", 20)),
                )
                data = {"dataset": ds}
            elif action == "assign_dataset":
                ok, msg, job = training.assign_dataset(
                    state, payload["job_id"], payload.get("employee_ids") or []
                )
                data = {"job": job}
            elif action == "start_training":
                ok, msg, job = training.start_training(
                    state,
                    ctx,
                    name=payload["name"],
                    model_type=payload["model_type"],
                    params_b=float(payload["params_b"]),
                    dataset_id=payload["dataset_id"],
                    from_scratch=bool(payload.get("from_scratch", True)),
                    base_model_id=payload.get("base_model_id"),
                    expected_days=int(payload.get("expected_days", 30)),
                    employee_ids=payload.get("employee_ids") or [],
                )
                data = {"job": job}
            elif action == "assign_training":
                ok, msg, job = training.assign(
                    state, payload["job_id"], payload.get("employee_ids") or []
                )
                data = {"job": job}
            elif action == "distill":
                ok, msg, job = training.start_training(
                    state,
                    ctx,
                    name=payload["name"],
                    model_type=payload.get("model_type", "text"),
                    params_b=float(payload["params_b"]),
                    dataset_id=payload["dataset_id"],
                    from_scratch=False,
                    expected_days=int(payload.get("expected_days", 14)),
                    employee_ids=payload.get("employee_ids") or [],
                    distill={
                        "teacher_model_id": payload["teacher_model_id"],
                        "teacher_source": payload.get("teacher_source", "own"),
                    },
                )
                data = {"job": job}
            elif action == "improve_model":
                ok, msg, job = training.start_improvement(
                    state,
                    ctx,
                    model_id=payload["model_id"],
                    method=payload["method"],
                    name=payload.get("name"),
                    dataset_id=payload.get("dataset_id"),
                    teacher_model_id=payload.get("teacher_model_id"),
                    teacher_source=payload.get("teacher_source", "own"),
                    expected_days=int(payload.get("expected_days", 14)),
                    employee_ids=payload.get("employee_ids") or [],
                )
                data = {"job": job}
            elif action == "set_auto_distill":
                ok, msg, automation = training.set_auto_distill(
                    state,
                    ctx,
                    model_id=payload["model_id"],
                    enabled=bool(payload.get("enabled", True)),
                    mode=payload.get("mode", "open"),
                )
                data = {"automation": automation}
            elif action == "set_auto_rl":
                ok, msg, automation = training.set_auto_rl(
                    state,
                    ctx,
                    enabled=bool(payload.get("enabled", True)),
                )
                data = {"automation": automation}
            elif action == "release_model":
                ok, msg, model = training.release(
                    state,
                    ctx,
                    payload["model_id"],
                    open_source=bool(payload.get("open_source", False)),
                    preview=bool(payload.get("preview", False)),
                    api_enabled=bool(payload.get("api_enabled", True)),
                    price_input=payload.get("price_input"),
                    price_output=payload.get("price_output"),
                )
                data = {"model": model}
            elif action == "set_api_price":
                ok, msg = training.set_price(
                    state, ctx, payload["model_id"], float(payload["price_input"]), float(payload["price_output"])
                )
            elif action == "set_auto_price":
                ok, msg, model = market.set_auto_pricing(
                    state,
                    ctx,
                    payload["model_id"],
                    bool(payload.get("enabled", True)),
                )
                data = {"model": model}
            elif action == "sign_contract":
                ok, msg, contract = market.sign_contract(
                    state,
                    ctx,
                    payload["offer_id"],
                    payload["model_id"],
                    int(payload["duration_years"]),
                )
                data = {"contract": contract}
            elif action == "borrow":
                ok, msg, loan = finance.borrow(
                    state, ctx, payload["product_id"], float(payload["amount"])
                )
                data = {"loan": loan}
            elif action == "repay_loan_early":
                ok, msg, loan = finance.repay_early(state, payload["loan_id"])
                data = {"loan": loan}
            elif action == "use_funding_tool":
                ok, msg, funding = finance.use_funding_tool(state, ctx, payload["tool_id"])
                data = {"funding": funding}
            elif action == "event_choice":
                ok, msg, logs = events.choose(state, ctx, payload["event_instance_id"], payload["choice_id"])
                data = {"logs": logs}
            else:
                ok, msg = False, f"未知操作: {action}"

            if ok and msg:
                self.append_log(msg, category="action", state=state)
            state["meta"]["updated_at"] = time.time()
            return {"ok": ok, "message": msg, "data": data, "state": self.public_state(game_id)}

    # ---------- save / load ----------

    def save(self, game_id: str, slot: str, label: str | None = None) -> dict[str, Any]:
        with self._lock:
            state = self._require(game_id)
            slot = _safe_slot(slot)
            path = SAVES_DIR / f"{slot}.json"
            blob = {
                "slot": slot,
                "label": label or state["company"]["name"],
                "saved_at": time.time(),
                "day": state.get("day", 0),
                "company_name": state["company"]["name"],
                "capital": state["company"]["capital"],
                "state": state,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(blob, f, ensure_ascii=False, indent=2)
            return {"ok": True, "slot": slot, "path": str(path)}

    def load(self, slot: str) -> dict[str, Any]:
        with self._lock:
            slot = _safe_slot(slot)
            path = SAVES_DIR / f"{slot}.json"
            if not path.exists():
                raise FileNotFoundError(f"存档不存在: {slot}")
            with open(path, encoding="utf-8") as f:
                blob = json.load(f)
            state = blob["state"]
            # rebind rng
            self.rng = random.Random(state.get("seed", 0) + state.get("day", 0))
            gid = state.get("game_id") or str(uuid.uuid4())
            state["game_id"] = gid
            self.sessions[gid] = state
            return self.public_state(gid)

    def list_saves(self) -> list[dict[str, Any]]:
        saves = []
        for path in sorted(SAVES_DIR.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    blob = json.load(f)
                saves.append(
                    {
                        "slot": blob.get("slot", path.stem),
                        "label": blob.get("label", path.stem),
                        "day": blob.get("day", 0),
                        "company_name": blob.get("company_name", ""),
                        "capital": blob.get("capital", 0),
                        "saved_at": blob.get("saved_at", 0),
                    }
                )
            except Exception:
                continue
        return saves

    def delete_save(self, slot: str) -> bool:
        path = SAVES_DIR / f"{_safe_slot(slot)}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # ---------- public projection ----------

    def public_state(self, game_id: str) -> dict[str, Any]:
        state = self.sessions[game_id]
        ctx = GameContext(self)
        systems_out = {}
        for sys in self.systems.all():
            systems_out[sys.name] = sys.serialize_public(state, ctx)

        # recompute live tendencies display
        from backend.app.engine.calculators.scores import compute_company_tendencies

        live_t = compute_company_tendencies(state, self.configs)
        # merge gov/public from stored (those are stateful)
        stored = state["company"].get("tendencies", {})
        tendencies = {
            "openness": live_t["openness"],
            "gov_relation": stored.get("gov_relation", live_t["gov_relation"]),
            "public_rep": stored.get("public_rep", live_t["public_rep"]),
            "transparency": live_t["transparency"],
            "innovation": live_t["innovation"],
        }

        return {
            "game_id": game_id,
            "day": state.get("day", 0),
            "company": {
                **{k: v for k, v in state["company"].items() if k != "founder_background_cfg"},
                "tendencies": tendencies,
            },
            "systems": systems_out,
            "log": list(reversed(state.get("log", [])[-50:])),
            "tick_events": state.get("_last_tick_events", []),
            "bankrupt": bool(state["company"].get("bankrupt")),
        }

    def catalog(self) -> dict[str, Any]:
        return {
            "countries": self.configs.load("countries").get("countries", {}),
            "backgrounds": self.configs.load("founder_backgrounds").get("backgrounds", {}),
            "logo_parts": self.configs.load("logo_parts"),
            "skills": self.configs.load("employees").get("skills", {}),
            "tendencies": self.configs.load("employees").get("tendencies", {}),
            "hidden_tags": self.configs.load("employees").get("hidden_tags", {}),
            "model_types": self.configs.load("model_types").get("model_types", {}),
            "param_presets": self.configs.load("model_types").get("param_presets", []),
            "chips": self.configs.load("chips").get("chips", {}),
            "api_segments": self.configs.load("market").get("api_segments", {}),
            "eval_benchmarks": self.configs.load("market").get("eval_benchmarks", {}),
            "competitor_strategies": self.configs.load("competitors").get("strategies", {}),
            "loan_products": self.configs.load("finance").get("loan_products", {}),
            "rivals_seed": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "strategy": r.get("strategy"),
                    "country": r.get("country"),
                    "tier": r.get("tier"),
                    "personality": r.get("personality", ""),
                }
                for r in self.configs.load("competitors").get("rivals", [])
            ],
        }

    def append_log(self, message: str, category: str = "game", state: dict | None = None) -> None:
        if state is None:
            return
        state.setdefault("log", []).append(
            {"day": state.get("day", 0), "msg": message, "cat": category}
        )

    def _require(self, game_id: str) -> dict[str, Any]:
        if game_id not in self.sessions:
            raise KeyError("游戏会话不存在，请新建或读档")
        return self.sessions[game_id]


def _safe_slot(slot: str) -> str:
    cleaned = "".join(c for c in slot if c.isalnum() or c in ("-", "_")).strip()
    if not cleaned:
        raise ValueError("无效存档名")
    return cleaned[:64]


# Singleton engine for the API process
_engine: GameEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> GameEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = GameEngine()
    return _engine
