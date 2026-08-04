"""Config-driven effect application.

Effects in JSON configs are plain dicts. Handlers are registered by key so
new content can introduce new effect types without rewriting systems.
"""

from __future__ import annotations

from typing import Any, Callable

from backend.app.engine.interfaces.base import EffectApplier, IGameContext

EffectHandler = Callable[[dict[str, Any], Any, IGameContext], str | None]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class DefaultEffectApplier(EffectApplier):
    def __init__(self) -> None:
        self._handlers: dict[str, EffectHandler] = {}
        self._register_builtins()

    def register(self, key: str, handler: EffectHandler) -> None:
        self._handlers[key] = handler

    def apply(self, state: dict[str, Any], effects: dict[str, Any], ctx: IGameContext) -> list[str]:
        logs: list[str] = []
        if not effects:
            return logs
        company = state.setdefault("company", {})
        direct_keys = {
            "capital",
            "gov_relation",
            "public_rep",
            "openness",
            "transparency",
            "innovation",
        }
        for key, value in effects.items():
            handler = self._handlers.get(key)
            if handler:
                msg = handler(state, value, ctx)
                if msg:
                    logs.append(msg)
            elif key in direct_keys:
                if key == "capital":
                    company["capital"] = float(company.get("capital", 0)) + float(value)
                    logs.append(f"资金 {float(value):+.0f}")
                else:
                    tendencies = company.setdefault("tendencies", {})
                    tendencies[key] = _clamp(
                        float(tendencies.get(key, 0)) + float(value), 0, 100
                    )
                    logs.append(f"{key} {float(value):+.1f}")
            else:
                mods = company.setdefault("modifiers", {})
                if isinstance(value, (int, float)):
                    mods[key] = float(mods.get(key, 0)) + float(value)
                    logs.append(f"修正 {key} {float(value):+.3f}")
                elif isinstance(value, dict):
                    nested = mods.setdefault(key, {})
                    if isinstance(nested, dict):
                        for nk, nv in value.items():
                            if isinstance(nv, (int, float)):
                                nested[nk] = float(nested.get(nk, 0)) + float(nv)
                    logs.append(f"修正 {key}")
                else:
                    mods[key] = value
        return logs

    def _register_builtins(self) -> None:
        def morale_all(state: dict, value: Any, ctx: IGameContext) -> str:
            for emp in state.get("employees", []):
                emp["morale"] = _clamp(float(emp.get("morale", 70)) + float(value), 0, 100)
            return f"全员士气 {float(value):+.0f}"

        def talent_pool_boost(state: dict, value: Any, ctx: IGameContext) -> str:
            hr = state.setdefault("hr", {})
            hr["talent_pool_boost"] = int(hr.get("talent_pool_boost", 0)) + int(value)
            return f"人才池 +{int(value)}"

        def grant_chips(state: dict, value: Any, ctx: IGameContext) -> str:
            pool = state.setdefault("compute", {}).setdefault("owned", {})
            if isinstance(value, dict):
                for chip_id, qty in value.items():
                    pool[chip_id] = int(pool.get(chip_id, 0)) + int(qty)
                return f"获得芯片 {value}"
            return ""

        def research_boost(state: dict, value: Any, ctx: IGameContext) -> str:
            levels = state.setdefault("research", {}).setdefault("levels", {})
            if isinstance(value, dict):
                for rid, lv in value.items():
                    cur = levels.get(rid, {"level": 0, "progress": 0.0})
                    if not isinstance(cur, dict):
                        cur = {"level": int(cur), "progress": 0.0}
                    cur["level"] = int(cur.get("level", 0)) + int(lv)
                    levels[rid] = cur
                return f"研究提升 {value}"
            return ""

        def risk_employee_leave(state: dict, value: Any, ctx: IGameContext) -> str:
            emps = state.get("employees", [])
            if not emps:
                return "没有可离职的员工"
            rng = ctx.rng()
            if rng.random() < float(value):
                emp = rng.choice(emps)
                emps.remove(emp)
                state.setdefault("log", []).append(
                    {
                        "day": state.get("day", 0),
                        "msg": f"{emp.get('name')} 被挖走了",
                        "cat": "hr",
                    }
                )
                return f"{emp.get('name')} 离职"
            return "员工选择留下"

        self.register("morale_all", morale_all)
        self.register("talent_pool_boost", talent_pool_boost)
        self.register("grant_chips", grant_chips)
        self.register("research_boost", research_boost)
        self.register("risk_employee_leave", risk_employee_leave)
