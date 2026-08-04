"""Research system — model / data / compute tracks, teams up to 20."""

from __future__ import annotations

import uuid
from typing import Any


class ResearchSystem:
    name = "research"

    CATEGORIES = ("model", "data", "compute")

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        cfg = ctx.configs().load("research")
        levels: dict[str, dict] = {}
        for cat_key in ("model_research", "data_research", "compute_research"):
            for rid in cfg.get(cat_key, {}):
                levels[rid] = {"level": 0, "progress": 0.0, "category": cat_key.replace("_research", "")}
        state["research"] = {"levels": levels, "active": []}

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        active = state.get("research", {}).get("active", [])
        finished = []
        bg_mult = float(state["company"].get("founder_background_cfg", {}).get("research_speed_multiplier", 1.0))

        for job in active:
            speed = self._team_speed(state, job, ctx) * bg_mult
            # capital burn
            daily_cost = float(job.get("daily_cost", 0))
            state["company"]["capital"] -= daily_cost * days * (job.get("progress_left_ratio", 1.0))

            job["progress"] = float(job.get("progress", 0)) + speed * days
            needed = float(job.get("needed", 100))
            if job["progress"] >= needed:
                finished.append(job)

        for job in finished:
            active.remove(job)
            rid = job["research_id"]
            levels = state["research"]["levels"]
            cur = levels.setdefault(rid, {"level": 0, "progress": 0.0, "category": job.get("category")})
            cur["level"] = int(cur.get("level", 0)) + 1
            cur["progress"] = 0.0
            for eid in job.get("employee_ids", []):
                emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
                if emp:
                    emp["assigned_to"] = None
                    # XP
                    for sk in (emp.get("skill_focus") or [])[:2]:
                        emp["skills"][sk] = round(min(100, float(emp["skills"].get(sk, 0)) + 1.5), 1)
            name = job.get("name", rid)
            lv = cur["level"]
            msg = f"研究完成：{name} → Lv.{lv}"
            events.append({"type": "research_done", "msg": msg, "research_id": rid, "level": lv})
            state.setdefault("log", []).append({"day": state.get("day", 0), "msg": msg, "cat": "research"})
            # innovation bump
            t = state["company"].setdefault("tendencies", {})
            t["innovation"] = min(100, float(t.get("innovation", 20)) + 1.5)

        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        cfg = ctx.configs().load("research")
        out_catalog: dict[str, list] = {"model": [], "data": [], "compute": []}
        mapping = {
            "model": "model_research",
            "data": "data_research",
            "compute": "compute_research",
        }
        for cat_key, cfg_key in mapping.items():
            for rid, rcfg in cfg.get(cfg_key, {}).items():
                lv = state["research"]["levels"].get(rid, {})
                level = int(lv.get("level", 0)) if isinstance(lv, dict) else int(lv or 0)
                active_job = next(
                    (j for j in state["research"].get("active", []) if j["research_id"] == rid),
                    None,
                )
                cost = self._level_cost(rcfg, level)
                out_catalog[cat_key].append(
                    {
                        "id": rid,
                        "name": rcfg.get("name"),
                        "description": rcfg.get("description"),
                        "category": cat_key,
                        "level": level,
                        "max_level": rcfg.get("max_level", 10),
                        "next_cost": cost,
                        "next_days_base": self._level_time(rcfg, level),
                        "team_cap": rcfg.get("team_cap", 20),
                        "icon": rcfg.get("icon"),
                        "effects": rcfg.get("effects", {}),
                        "required_skills": rcfg.get("required_skills", {}),
                        "active": active_job,
                    }
                )
        return {"catalog": out_catalog, "active": state["research"].get("active", [])}

    def start(self, state: dict[str, Any], ctx, research_id: str, category: str, employee_ids: list[str]) -> tuple[bool, str, dict | None]:
        cfg_root = ctx.configs().load("research")
        mapping = {"model": "model_research", "data": "data_research", "compute": "compute_research"}
        if category not in mapping:
            return False, "未知研究类别", None
        rcfg = cfg_root.get(mapping[category], {}).get(research_id)
        if not rcfg:
            return False, "未知研究项目", None

        levels = state["research"]["levels"]
        cur = levels.get(research_id, {"level": 0})
        level = int(cur.get("level", 0)) if isinstance(cur, dict) else int(cur)
        if level >= int(rcfg.get("max_level", 10)):
            return False, "已达最高等级", None

        if any(j["research_id"] == research_id for j in state["research"].get("active", [])):
            return False, "该研究已在进行中", None

        # validate employees
        team_cap = int(rcfg.get("team_cap", 20))
        employee_ids = employee_ids[:team_cap]
        emps = []
        for eid in employee_ids:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if not emp:
                return False, f"员工 {eid} 不存在", None
            if emp.get("assigned_to"):
                return False, f"{emp['name']} 已有任务", None
            emps.append(emp)

        cost = self._level_cost(rcfg, level)
        if state["company"]["capital"] < cost:
            return False, f"资金不足（需要 ${cost:,.0f}）", None

        state["company"]["capital"] -= cost
        needed = float(self._level_time(rcfg, level)) * 10  # progress units
        job = {
            "id": str(uuid.uuid4())[:8],
            "research_id": research_id,
            "category": category,
            "name": rcfg.get("name"),
            "level_from": level,
            "progress": 0.0,
            "needed": needed,
            "employee_ids": [e["id"] for e in emps],
            "daily_cost": cost * 0.02,
            "started_day": state.get("day", 0),
        }
        for e in emps:
            e["assigned_to"] = f"research:{research_id}"
        state["research"].setdefault("active", []).append(job)
        return True, f"开始研究 {rcfg.get('name')} Lv.{level + 1}", job

    def assign(self, state: dict[str, Any], research_id: str, employee_ids: list[str]) -> tuple[bool, str]:
        job = next((j for j in state["research"].get("active", []) if j["research_id"] == research_id), None)
        if not job:
            return False, "没有进行中的该研究"
        # free old
        for eid in job.get("employee_ids", []):
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if emp:
                emp["assigned_to"] = None
        valid = []
        for eid in employee_ids[:20]:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if emp and not emp.get("assigned_to"):
                emp["assigned_to"] = f"research:{research_id}"
                valid.append(eid)
        job["employee_ids"] = valid
        return True, f"已分配 {len(valid)} 人"

    def _level_cost(self, rcfg: dict, level: int) -> float:
        base = float(rcfg.get("base_cost", 50000))
        growth = float(rcfg.get("cost_growth", 1.4))
        return round(base * (growth ** level), 0)

    def _level_time(self, rcfg: dict, level: int) -> float:
        base = float(rcfg.get("base_time_days", 14))
        growth = float(rcfg.get("time_growth", 1.2))
        return base * (growth ** level)

    def _team_speed(self, state: dict, job: dict, ctx) -> float:
        """Progress units per day."""
        cfg_root = ctx.configs().load("research")
        mapping = {"model": "model_research", "data": "data_research", "compute": "compute_research"}
        rcfg = cfg_root.get(mapping.get(job.get("category", ""), ""), {}).get(job["research_id"], {})
        req = rcfg.get("required_skills", {})
        emps = [e for e in state.get("employees", []) if e["id"] in job.get("employee_ids", [])]
        if not emps:
            return 0.15  # solo founder trickle
        total = 0.0
        for emp in emps:
            skill_score = 0.0
            if req:
                for sk, need in req.items():
                    skill_score += max(0.0, float(emp.get("skills", {}).get(sk, 0)) / max(need * 20, 1))
                skill_score /= max(len(req), 1)
            else:
                skill_score = sum(emp.get("skills", {}).values()) / max(len(emp.get("skills", {})), 1) / 50.0
            morale = float(emp.get("morale", 70)) / 100.0
            fatigue = 1.0 - float(emp.get("fatigue", 0)) / 200.0
            tag_mult = 1.0
            for tag in emp.get("hidden_tags", []):
                eff = ctx.configs().get("employees", "hidden_tags", tag, "effect", default={}) or {}
                if "research_speed" in eff:
                    tag_mult += float(eff["research_speed"])
                if "quality" in eff:
                    tag_mult += float(eff["quality"]) * 0.3
                if "speed" in eff:
                    tag_mult += float(eff["speed"])
            total += skill_score * morale * fatigue * tag_mult
        # diminishing returns past 8 people
        n = len(emps)
        team_factor = n / (1 + 0.08 * max(0, n - 4))
        # Scale so a decent small team finishes a level in roughly base_time days
        return max(0.5, total * 0.9 * (team_factor / max(n, 1)) * 8.0)
