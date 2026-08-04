"""Research system — Game Dev Tycoon style continuous investment.

Player picks research directions and assigns staff. Progress accumulates
each day while staffed; when a level completes, XP resets and the next
level begins automatically if people remain assigned.
"""

from __future__ import annotations

import uuid
from typing import Any


class ResearchSystem:
    name = "research"

    CATEGORIES = ("model", "data", "compute")
    # Soft cap on concurrent focused topics (staff is the real limit)
    MAX_CONCURRENT = 8

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        cfg = ctx.configs().load("research")
        levels: dict[str, dict] = {}
        for cat_key in ("model_research", "data_research", "compute_research"):
            cat = cat_key.replace("_research", "")
            for rid in cfg.get(cat_key, {}):
                levels[rid] = {
                    "level": 0,
                    "progress": 0.0,
                    "category": cat,
                    "employee_ids": [],
                    "paused": False,
                    "total_invested": 0.0,
                    "started_day": None,
                }
        state["research"] = {
            "levels": levels,
            # legacy alias: "active" = currently staffed / progressing topics
            "active": [],
        }

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        cfg_root = ctx.configs().load("research")
        mapping = {
            "model": "model_research",
            "data": "data_research",
            "compute": "compute_research",
        }
        bg_mult = float(
            state["company"].get("founder_background_cfg", {}).get("research_speed_multiplier", 1.0)
        )
        levels = state["research"]["levels"]

        # Sync active list from levels that have staff
        self._sync_active(state)

        for rid, cur in list(levels.items()):
            if not isinstance(cur, dict):
                continue
            eids = list(cur.get("employee_ids") or [])
            if not eids or cur.get("paused"):
                continue

            cat = cur.get("category") or "model"
            rcfg = cfg_root.get(mapping.get(cat, ""), {}).get(rid)
            if not rcfg:
                continue

            level = int(cur.get("level", 0))
            max_lv = int(rcfg.get("max_level", 10))
            if level >= max_lv:
                # maxed — free staff
                self._free_staff(state, eids)
                cur["employee_ids"] = []
                continue

            needed = self._progress_needed(rcfg, level)
            speed = self._team_speed(state, rid, cat, eids, ctx) * bg_mult
            daily_cost = self._daily_cost(rcfg, level, len(eids))

            for _ in range(days):
                if level >= max_lv:
                    break
                state["company"]["capital"] = float(state["company"].get("capital", 0)) - daily_cost
                cur["progress"] = float(cur.get("progress", 0.0)) + speed
                cur["total_invested"] = float(cur.get("total_invested", 0.0)) + daily_cost
                needed = self._progress_needed(rcfg, level)

                # Level-up loop (in case huge team blasts through)
                while cur["progress"] >= needed and level < max_lv:
                    overflow = cur["progress"] - needed
                    level += 1
                    cur["level"] = level
                    cur["progress"] = max(0.0, overflow * 0.15)  # slight carry, mostly fresh bar
                    name = rcfg.get("name", rid)
                    msg = f"研究突破：{name} → Lv.{level}"
                    events.append(
                        {"type": "research_done", "msg": msg, "research_id": rid, "level": level}
                    )
                    state.setdefault("log", []).append(
                        {"day": state.get("day", 0), "msg": msg, "cat": "research"}
                    )
                    t = state["company"].setdefault("tendencies", {})
                    t["innovation"] = min(100, float(t.get("innovation", 20)) + 1.5)
                    # staff XP on breakthrough
                    for eid in eids:
                        emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
                        if emp:
                            for sk in (emp.get("skill_focus") or [])[:2]:
                                emp["skills"][sk] = round(
                                    min(100, float(emp["skills"].get(sk, 0)) + 1.2), 1
                                )
                    if level >= max_lv:
                        self._free_staff(state, eids)
                        cur["employee_ids"] = []
                        cur["progress"] = 0.0
                        msg2 = f"{name} 已达满级"
                        events.append({"type": "research_max", "msg": msg2, "research_id": rid})
                        break
                    needed = self._progress_needed(rcfg, level)

        self._sync_active(state)
        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        cfg = ctx.configs().load("research")
        out_catalog: dict[str, list] = {"model": [], "data": [], "compute": []}
        mapping = {
            "model": "model_research",
            "data": "data_research",
            "compute": "compute_research",
        }
        bg_mult = float(
            state["company"].get("founder_background_cfg", {}).get("research_speed_multiplier", 1.0)
        )
        levels = state["research"]["levels"]

        for cat_key, cfg_key in mapping.items():
            for rid, rcfg in cfg.get(cfg_key, {}).items():
                cur = levels.get(rid, {})
                if not isinstance(cur, dict):
                    cur = {"level": int(cur or 0), "progress": 0.0, "employee_ids": []}
                level = int(cur.get("level", 0))
                progress = float(cur.get("progress", 0.0))
                needed = self._progress_needed(rcfg, level) if level < int(rcfg.get("max_level", 10)) else 1.0
                eids = list(cur.get("employee_ids") or [])
                speed = (
                    self._team_speed(state, rid, cat_key, eids, ctx) * bg_mult if eids else 0.0
                )
                pct = min(100.0, (progress / needed) * 100.0) if needed > 0 else 0.0
                eta = None
                if speed > 0.01 and level < int(rcfg.get("max_level", 10)):
                    remain = max(0.0, needed - progress)
                    eta = round(remain / speed, 1)

                staff = []
                for eid in eids:
                    emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
                    if emp:
                        staff.append(
                            {
                                "id": emp["id"],
                                "name": emp["name"],
                                "role_name": emp.get("role_name"),
                                "seniority_name": emp.get("seniority_name"),
                            }
                        )

                out_catalog[cat_key].append(
                    {
                        "id": rid,
                        "name": rcfg.get("name"),
                        "description": rcfg.get("description"),
                        "category": cat_key,
                        "level": level,
                        "max_level": rcfg.get("max_level", 10),
                        "progress": round(progress, 2),
                        "needed": round(needed, 2),
                        "progress_pct": round(pct, 1),
                        "speed_per_day": round(speed, 2),
                        "eta_days": eta,
                        "daily_cost": self._daily_cost(rcfg, level, max(1, len(eids))) if eids else self._daily_cost(rcfg, level, 1),
                        "team_cap": rcfg.get("team_cap", 20),
                        "staff": staff,
                        "employee_ids": eids,
                        "focused": bool(eids) and not cur.get("paused"),
                        "paused": bool(cur.get("paused")),
                        "icon": rcfg.get("icon"),
                        "effects": rcfg.get("effects", {}),
                        "required_skills": rcfg.get("required_skills", {}),
                        "total_invested": round(float(cur.get("total_invested", 0)), 0),
                        # backward-compat for old UI expecting active job blob
                        "active": {
                            "progress": progress,
                            "needed": needed,
                            "employee_ids": eids,
                            "progress_pct": pct,
                            "eta_days": eta,
                        }
                        if eids
                        else None,
                    }
                )

        active = [
            {
                "research_id": rid,
                "name": next(
                    (
                        x["name"]
                        for cat in out_catalog.values()
                        for x in cat
                        if x["id"] == rid
                    ),
                    rid,
                ),
                "category": cur.get("category"),
                "level": int(cur.get("level", 0)),
                "progress": float(cur.get("progress", 0)),
                "needed": next(
                    (
                        x["needed"]
                        for cat in out_catalog.values()
                        for x in cat
                        if x["id"] == rid
                    ),
                    100,
                ),
                "employee_ids": list(cur.get("employee_ids") or []),
                "progress_pct": next(
                    (
                        x["progress_pct"]
                        for cat in out_catalog.values()
                        for x in cat
                        if x["id"] == rid
                    ),
                    0,
                ),
                "eta_days": next(
                    (
                        x["eta_days"]
                        for cat in out_catalog.values()
                        for x in cat
                        if x["id"] == rid
                    ),
                    None,
                ),
            }
            for rid, cur in levels.items()
            if isinstance(cur, dict) and cur.get("employee_ids")
        ]
        return {"catalog": out_catalog, "active": active, "max_concurrent": self.MAX_CONCURRENT}

    # ---- actions ----

    def start(
        self,
        state: dict[str, Any],
        ctx,
        research_id: str,
        category: str,
        employee_ids: list[str],
    ) -> tuple[bool, str, dict | None]:
        """Begin or retarget focus on a research direction (GDT-style assign)."""
        return self.assign(state, ctx, research_id, category, employee_ids)

    def assign(
        self,
        state: dict[str, Any],
        ctx,
        research_id: str,
        category: str | None = None,
        employee_ids: list[str] | None = None,
    ) -> tuple[bool, str, dict | None]:
        """Assign staff to a research direction. Empty list = pause/unfocus."""
        if employee_ids is None:
            # legacy signature assign(state, research_id, employee_ids)
            # handled by game.py wrapper
            employee_ids = []
        cfg_root = ctx.configs().load("research")
        mapping = {"model": "model_research", "data": "data_research", "compute": "compute_research"}

        levels = state["research"]["levels"]
        cur = levels.get(research_id)
        if cur is None:
            return False, "未知研究项目", None
        if not isinstance(cur, dict):
            cur = {"level": int(cur or 0), "progress": 0.0, "employee_ids": [], "category": category or "model"}
            levels[research_id] = cur

        cat = category or cur.get("category") or "model"
        rcfg = cfg_root.get(mapping.get(cat, ""), {}).get(research_id)
        if not rcfg:
            # try find in any category
            for ck, mk in mapping.items():
                if research_id in cfg_root.get(mk, {}):
                    rcfg = cfg_root[mk][research_id]
                    cat = ck
                    break
        if not rcfg:
            return False, "未知研究项目", None

        cur["category"] = cat
        level = int(cur.get("level", 0))
        if level >= int(rcfg.get("max_level", 10)):
            return False, "已达最高等级", None

        team_cap = int(rcfg.get("team_cap", 20))
        employee_ids = list(employee_ids or [])[:team_cap]

        # concurrent focus limit (only when adding staff to a new topic)
        focused_others = [
            rid
            for rid, lv in levels.items()
            if rid != research_id and isinstance(lv, dict) and lv.get("employee_ids")
        ]
        if employee_ids and research_id not in [f for f in focused_others] and len(focused_others) >= self.MAX_CONCURRENT:
            if not cur.get("employee_ids"):
                return False, f"同时专注的研究方向最多 {self.MAX_CONCURRENT} 个，请先撤下其他方向的人手", None

        # Free previous assignees on this topic
        old = list(cur.get("employee_ids") or [])
        self._free_staff(state, old)

        # Validate new staff (must be free, or were on this same topic)
        valid = []
        for eid in employee_ids:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if not emp:
                return False, f"员工 {eid} 不存在", None
            assigned = emp.get("assigned_to")
            if assigned and assigned != f"research:{research_id}":
                return False, f"{emp['name']} 已有任务（{assigned}）", None
            valid.append(eid)

        for eid in valid:
            emp = next(e for e in state["employees"] if e["id"] == eid)
            emp["assigned_to"] = f"research:{research_id}"

        cur["employee_ids"] = valid
        cur["paused"] = False
        if valid and cur.get("started_day") is None:
            cur["started_day"] = state.get("day", 0)
        if not valid:
            cur["paused"] = True

        # Small setup cost when first putting people on a fresh direction this level
        setup = 0.0
        if valid and float(cur.get("progress", 0)) <= 0.01 and not old:
            setup = float(rcfg.get("base_cost", 50000)) * 0.08 * (1.2 ** level)
            if state["company"]["capital"] < setup:
                # rollback
                self._free_staff(state, valid)
                cur["employee_ids"] = []
                return False, f"启动资金不足（需要 ${setup:,.0f} 立项费）", None
            state["company"]["capital"] -= setup
            cur["total_invested"] = float(cur.get("total_invested", 0)) + setup

        self._sync_active(state)
        name = rcfg.get("name", research_id)
        if not valid:
            return True, f"已暂停研究：{name}", {"research_id": research_id, "employee_ids": []}

        speed = self._team_speed(state, research_id, cat, valid, ctx)
        needed = self._progress_needed(rcfg, level)
        remain = max(0.0, needed - float(cur.get("progress", 0)))
        eta = round(remain / speed, 1) if speed > 0.01 else None
        msg = f"投入 {len(valid)} 人研究 {name}（Lv.{level}→{level+1}"
        if eta is not None:
            msg += f"，约 {eta} 天"
        msg += "）"
        if setup:
            msg += f" · 立项 ${setup:,.0f}"
        return True, msg, {
            "research_id": research_id,
            "employee_ids": valid,
            "progress": cur.get("progress"),
            "needed": needed,
            "eta_days": eta,
            "setup_cost": setup,
        }

    def pause(self, state: dict[str, Any], research_id: str) -> tuple[bool, str]:
        cur = state["research"]["levels"].get(research_id)
        if not isinstance(cur, dict):
            return False, "未知研究"
        eids = list(cur.get("employee_ids") or [])
        self._free_staff(state, eids)
        cur["employee_ids"] = []
        cur["paused"] = True
        self._sync_active(state)
        return True, "已撤回人手，进度保留"

    # ---- internals ----

    def _sync_active(self, state: dict) -> None:
        active = []
        for rid, cur in state["research"]["levels"].items():
            if isinstance(cur, dict) and cur.get("employee_ids"):
                active.append(
                    {
                        "id": rid,
                        "research_id": rid,
                        "category": cur.get("category"),
                        "employee_ids": list(cur["employee_ids"]),
                        "progress": float(cur.get("progress", 0)),
                        "level_from": int(cur.get("level", 0)),
                    }
                )
        state["research"]["active"] = active

    def _free_staff(self, state: dict, eids: list[str]) -> None:
        for eid in eids:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if emp and str(emp.get("assigned_to") or "").startswith("research:"):
                emp["assigned_to"] = None

    def _progress_needed(self, rcfg: dict, level: int) -> float:
        """Work units required for next level. Scales with level time."""
        base = float(rcfg.get("base_time_days", 14))
        growth = float(rcfg.get("time_growth", 1.2))
        # 10 units ≈ 1 day for a solid ~3-person team at speed ~10
        return max(20.0, base * (growth ** level) * 10.0)

    def _daily_cost(self, rcfg: dict, level: int, n_staff: int) -> float:
        base = float(rcfg.get("base_cost", 50000))
        growth = float(rcfg.get("cost_growth", 1.4))
        # Continuous burn: small fraction of level cost per day, scales with staff
        per = base * (growth ** level) * 0.012
        return round(per * (0.6 + 0.15 * max(1, n_staff)), 1)

    def _level_cost(self, rcfg: dict, level: int) -> float:
        """Displayed 'investment scale' for UI (not charged upfront)."""
        base = float(rcfg.get("base_cost", 50000))
        growth = float(rcfg.get("cost_growth", 1.4))
        return round(base * (growth ** level), 0)

    def _level_time(self, rcfg: dict, level: int) -> float:
        base = float(rcfg.get("base_time_days", 14))
        growth = float(rcfg.get("time_growth", 1.2))
        return base * (growth ** level)

    def _team_speed(
        self, state: dict, research_id: str, category: str, employee_ids: list[str], ctx
    ) -> float:
        """Progress units per day from assigned team."""
        cfg_root = ctx.configs().load("research")
        mapping = {"model": "model_research", "data": "data_research", "compute": "compute_research"}
        rcfg = cfg_root.get(mapping.get(category, ""), {}).get(research_id, {})
        req = rcfg.get("required_skills", {})
        emps = [e for e in state.get("employees", []) if e["id"] in employee_ids]
        if not emps:
            return 0.0

        total = 0.0
        for emp in emps:
            if req:
                skill_score = 0.0
                for sk, need in req.items():
                    skill_score += max(0.0, float(emp.get("skills", {}).get(sk, 0)) / max(need * 20, 1))
                skill_score /= max(len(req), 1)
            else:
                skills = emp.get("skills") or {}
                skill_score = sum(skills.values()) / max(len(skills), 1) / 50.0
            morale = float(emp.get("morale", 70)) / 100.0
            fatigue = 1.0 - float(emp.get("fatigue", 0)) / 200.0
            tag_mult = 1.0
            for tag in emp.get("hidden_tags", []):
                eff = ctx.configs().get("employees", "hidden_tags", tag, "effect", default={}) or {}
                if "research_speed" in eff:
                    tag_mult += float(eff["research_speed"])
                if "quality" in eff:
                    tag_mult += float(eff["quality"]) * 0.25
                if "speed" in eff:
                    tag_mult += float(eff["speed"])
            # Seniority helps a bit
            sen = {"junior": 0.85, "mid": 1.0, "senior": 1.15, "staff": 1.3, "principal": 1.45}.get(
                emp.get("seniority"), 1.0
            )
            total += max(0.08, skill_score * morale * fatigue * tag_mult * sen)

        n = len(emps)
        # Diminishing returns past ~6 people (GDT-like: more people help less)
        efficiency = n / (1.0 + 0.12 * max(0, n - 3))
        # Calibrate: 3 mid researchers ≈ ~8-12 units/day
        return max(0.3, total * (efficiency / max(n, 1)) * 7.5)
