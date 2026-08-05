"""Research system — Game Dev Tycoon style continuous investment.

Player picks research directions and assigns staff. Progress accumulates
each day while staffed; when a level completes, XP resets and the next
level begins automatically if people remain assigned.
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.app.engine.calculators import scores as calc


class ResearchSystem:
    name = "research"

    CATEGORIES = ("model", "data", "compute")
    CATEGORY_STAFF_CAPS = {"model": 20, "data": 20, "compute": 20}
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
                    "auto_enabled": False,
                }
        state["research"] = {
            "levels": levels,
            # legacy alias: "active" = currently staffed / progressing topics
            "active": [],
            "automation": {
                "reserved_employee_id": None,
                "last_rebalance_day": None,
                "allocations": {},
            },
        }

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        self._enforce_category_staff_caps(state)
        auto_result = self._rebalance_auto_research(state, ctx)
        if auto_result.get("changed") and auto_result.get("message"):
            events.append({"type": "auto_research", "msg": auto_result["message"]})
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
                cur["auto_enabled"] = False
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
                        cur["auto_enabled"] = False
                        msg2 = f"{name} 已达满级"
                        events.append({"type": "research_max", "msg": msg2, "research_id": rid})
                        break
                    needed = self._progress_needed(rcfg, level)

        self._sync_active(state)
        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        # Normalize legacy saves that may have assigned up to 20 people to every
        # topic before category-wide staffing pools were introduced.
        self._enforce_category_staff_caps(state)
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
        category_staff = self._category_staff_counts(state)

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
                        "setup_cost_estimate": round(
                            float(rcfg.get("base_cost", 50000)) * 0.08 * (1.2 ** level), 2
                        ) if progress <= 0.01 and not eids else 0.0,
                        "team_cap": self.CATEGORY_STAFF_CAPS.get(cat_key, 20),
                        "category_staff_used": category_staff.get(cat_key, 0),
                        "category_staff_cap": self.CATEGORY_STAFF_CAPS.get(cat_key, 20),
                        "assignable_cap": max(
                            len(eids),
                            self.CATEGORY_STAFF_CAPS.get(cat_key, 20)
                            - (category_staff.get(cat_key, 0) - len(eids)),
                        ),
                        "staff": staff,
                        "employee_ids": eids,
                        "focused": bool(eids) and not cur.get("paused"),
                        "paused": bool(cur.get("paused")),
                        "auto_enabled": bool(cur.get("auto_enabled")),
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
        automation = state.get("research", {}).get("automation", {})
        reserved_id = automation.get("reserved_employee_id")
        reserved_employee = next(
            (employee for employee in state.get("employees", []) if employee["id"] == reserved_id),
            None,
        )
        return {
            "catalog": out_catalog,
            "active": active,
            "max_concurrent": self.MAX_CONCURRENT,
            "category_staff": {
                category: {
                    "used": category_staff.get(category, 0),
                    "cap": cap,
                    "remaining": max(0, cap - category_staff.get(category, 0)),
                }
                for category, cap in self.CATEGORY_STAFF_CAPS.items()
            },
            "automation": {
                "enabled_count": sum(
                    1
                    for cur in levels.values()
                    if isinstance(cur, dict) and cur.get("auto_enabled")
                ),
                "reserved_employee": {
                    "id": reserved_employee["id"],
                    "name": reserved_employee.get("name"),
                    "role_name": reserved_employee.get("role_name"),
                    "training_fit": round(self._training_fit(state, reserved_employee), 1),
                }
                if reserved_employee
                else None,
                "last_rebalance_day": automation.get("last_rebalance_day"),
                "allocations": dict(automation.get("allocations") or {}),
                "blocked_topics": list(automation.get("blocked_topics") or []),
            },
        }

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

    def set_auto(
        self,
        state: dict[str, Any],
        ctx,
        research_id: str,
        category: str,
        enabled: bool,
    ) -> tuple[bool, str, dict | None]:
        cfg_root = ctx.configs().load("research")
        mapping = {"model": "model_research", "data": "data_research", "compute": "compute_research"}
        cur = state.get("research", {}).get("levels", {}).get(research_id)
        rcfg = cfg_root.get(mapping.get(category, ""), {}).get(research_id)
        if not isinstance(cur, dict) or not rcfg:
            return False, "未知研究项目", None
        if enabled and int(cur.get("level", 0)) >= int(rcfg.get("max_level", 10)):
            return False, "已达最高等级，无法开启自动研究", None
        cur["category"] = category
        cur["auto_enabled"] = bool(enabled)
        result = self._rebalance_auto_research(state, ctx)
        name = rcfg.get("name", research_id)
        if enabled:
            assigned = len(cur.get("employee_ids") or [])
            reserved = result.get("reserved_name")
            msg = f"已开启自动研究：{name}"
            msg += f"（当前自动分配 {assigned} 人"
            if reserved:
                msg += f"，为训练预留 {reserved}"
            msg += "）"
        else:
            msg = f"已关闭自动研究：{name}（当前人员保留为手动团队）"
        return True, msg, result

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
        self._enforce_category_staff_caps(state)
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
        # A direct player assignment takes this topic back into manual control.
        cur["auto_enabled"] = False
        level = int(cur.get("level", 0))
        if level >= int(rcfg.get("max_level", 10)):
            return False, "已达最高等级", None

        team_cap = int(self.CATEGORY_STAFF_CAPS.get(cat, 20))
        employee_ids = list(dict.fromkeys(employee_ids or []))[:team_cap]

        # Every research category owns one shared staffing pool. Replacing the
        # current topic's team does not double-count its existing assignees.
        category_cap = int(self.CATEGORY_STAFF_CAPS.get(cat, 20))
        other_category_staff = {
            eid
            for rid, lv in levels.items()
            if rid != research_id
            and isinstance(lv, dict)
            and (lv.get("category") or "model") == cat
            for eid in (lv.get("employee_ids") or [])
        }
        proposed_category_total = len(other_category_staff | set(employee_ids))
        if proposed_category_total > category_cap:
            available = max(0, category_cap - len(other_category_staff))
            category_names = {"model": "模型", "data": "数据", "compute": "推理算力"}
            return False, (
                f"{category_names.get(cat, cat)}研究人员总上限为 {category_cap} 人；"
                f"其他课题已占用 {len(other_category_staff)} 人，本课题最多可分配 {available} 人"
            ), None

        # concurrent focus limit (only when adding staff to a new topic)
        focused_others = [
            rid
            for rid, lv in levels.items()
            if rid != research_id and isinstance(lv, dict) and lv.get("employee_ids")
        ]
        if employee_ids and research_id not in [f for f in focused_others] and len(focused_others) >= self.MAX_CONCURRENT:
            if not cur.get("employee_ids"):
                return False, f"同时专注的研究方向最多 {self.MAX_CONCURRENT} 个，请先撤下其他方向的人手", None

        # Validate the replacement team before changing any existing assignment.
        old = list(cur.get("employee_ids") or [])
        valid = []
        for eid in employee_ids:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if not emp:
                return False, f"员工 {eid} 不存在", None
            assigned = emp.get("assigned_to")
            if assigned and assigned != f"research:{research_id}":
                return False, f"{emp['name']} 已有任务（{assigned}）", None
            valid.append(eid)

        self._free_staff(state, old)
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
            "category_staff_used": proposed_category_total,
            "category_staff_cap": category_cap,
        }

    def pause(self, state: dict[str, Any], research_id: str) -> tuple[bool, str]:
        cur = state["research"]["levels"].get(research_id)
        if not isinstance(cur, dict):
            return False, "未知研究"
        eids = list(cur.get("employee_ids") or [])
        self._free_staff(state, eids)
        cur["employee_ids"] = []
        cur["paused"] = True
        cur["auto_enabled"] = False
        self._sync_active(state)
        return True, "已撤回人手，进度保留"

    # ---- internals ----

    def _rebalance_auto_research(self, state: dict, ctx) -> dict[str, Any]:
        levels = state.get("research", {}).get("levels", {})
        cfg_root = ctx.configs().load("research")
        mapping = {"model": "model_research", "data": "data_research", "compute": "compute_research"}
        auto_topics: dict[str, tuple[dict, dict, str]] = {}
        for research_id, cur in levels.items():
            if not isinstance(cur, dict) or not cur.get("auto_enabled"):
                continue
            category = cur.get("category") or "model"
            rcfg = cfg_root.get(mapping.get(category, ""), {}).get(research_id)
            if not rcfg or int(cur.get("level", 0)) >= int(rcfg.get("max_level", 10)):
                cur["auto_enabled"] = False
                continue
            auto_topics[research_id] = (cur, rcfg, category)

        automation = state.setdefault("research", {}).setdefault("automation", {})
        if not auto_topics:
            previous_reserved = automation.get("reserved_employee_id")
            automation.update(
                {
                    "reserved_employee_id": None,
                    "last_rebalance_day": state.get("day", 0),
                    "allocations": {},
                    "blocked_topics": [],
                }
            )
            return {"changed": bool(previous_reserved), "allocations": {}, "reserved_name": None}

        previous_allocations = {
            research_id: list(cur.get("employee_ids") or [])
            for research_id, (cur, _rcfg, _category) in auto_topics.items()
        }
        previous_signature = (
            automation.get("reserved_employee_id"),
            tuple((research_id, tuple(ids)) for research_id, ids in sorted(previous_allocations.items())),
        )

        # Only free staff and existing automatic-research staff enter the pool.
        auto_assignments = {f"research:{research_id}" for research_id in auto_topics}
        candidates = [
            employee
            for employee in state.get("employees", [])
            if not employee.get("assigned_to") or employee.get("assigned_to") in auto_assignments
        ]
        for research_id, (cur, _rcfg, _category) in auto_topics.items():
            for employee_id in cur.get("employee_ids") or []:
                employee = next(
                    (item for item in state.get("employees", []) if item["id"] == employee_id),
                    None,
                )
                if employee and employee.get("assigned_to") == f"research:{research_id}":
                    employee["assigned_to"] = None
            cur["employee_ids"] = []
            cur["paused"] = True

        # Reserve the strongest available training specialist. This invariant is
        # enforced whenever at least one automatic research topic is enabled.
        reserved = max(candidates, key=lambda employee: self._training_fit(state, employee), default=None)
        reserve_id = reserved.get("id") if reserved else None
        assignable = [employee for employee in candidates if employee.get("id") != reserve_id]

        manual_active = {
            research_id
            for research_id, cur in levels.items()
            if research_id not in auto_topics
            and isinstance(cur, dict)
            and cur.get("employee_ids")
        }
        active_topics = set(manual_active)
        category_used: dict[str, set[str]] = {category: set() for category in self.CATEGORIES}
        for research_id, cur in levels.items():
            if research_id in auto_topics or not isinstance(cur, dict):
                continue
            category = cur.get("category") or "model"
            category_used.setdefault(category, set()).update(cur.get("employee_ids") or [])

        allocations: dict[str, list[str]] = {research_id: [] for research_id in auto_topics}
        # Allocate specialists first, then account for diminishing returns so
        # similarly matched staff naturally spread across useful topics.
        assignable.sort(
            key=lambda employee: max(
                (
                    self._research_fit(state, employee, rcfg)
                    for _cur, rcfg, _category in auto_topics.values()
                ),
                default=0.0,
            ),
            reverse=True,
        )
        for employee in assignable:
            choices = []
            for research_id, (_cur, rcfg, category) in auto_topics.items():
                if len(category_used.setdefault(category, set())) >= int(
                    self.CATEGORY_STAFF_CAPS.get(category, 20)
                ):
                    continue
                if research_id not in active_topics and len(active_topics) >= self.MAX_CONCURRENT:
                    continue
                fit = self._research_fit(state, employee, rcfg)
                if fit < 25.0:
                    continue
                marginal_fit = fit / (1.0 + 0.16 * len(allocations[research_id]))
                choices.append((marginal_fit, fit, research_id, category))
            if not choices:
                continue
            _marginal, _fit, research_id, category = max(choices)
            allocations[research_id].append(employee["id"])
            category_used[category].add(employee["id"])
            active_topics.add(research_id)

        blocked_topics: list[str] = []
        for research_id, (cur, rcfg, _category) in auto_topics.items():
            employee_ids = allocations[research_id]
            needs_setup = bool(
                employee_ids
                and float(cur.get("progress", 0)) <= 0.01
                and not previous_allocations.get(research_id)
                and cur.get("auto_setup_paid_level") != int(cur.get("level", 0))
            )
            if needs_setup:
                level = int(cur.get("level", 0))
                setup = float(rcfg.get("base_cost", 50000)) * 0.08 * (1.2 ** level)
                if float(state["company"].get("capital", 0)) < setup:
                    employee_ids = []
                    allocations[research_id] = []
                    blocked_topics.append(research_id)
                else:
                    state["company"]["capital"] = float(state["company"].get("capital", 0)) - setup
                    cur["total_invested"] = float(cur.get("total_invested", 0)) + setup
                    cur["auto_setup_paid_level"] = level
                    state.setdefault("log", []).append(
                        {
                            "day": state.get("day", 0),
                            "msg": f"自动研究立项：{rcfg.get('name', research_id)}（${setup:,.0f}）",
                            "cat": "research",
                        }
                    )
            cur["employee_ids"] = employee_ids
            cur["paused"] = not bool(employee_ids)
            if employee_ids and cur.get("started_day") is None:
                cur["started_day"] = state.get("day", 0)
            for employee_id in employee_ids:
                employee = next(
                    (item for item in state.get("employees", []) if item["id"] == employee_id),
                    None,
                )
                if employee:
                    employee["assigned_to"] = f"research:{research_id}"

        automation.update(
            {
                "reserved_employee_id": reserve_id,
                "last_rebalance_day": state.get("day", 0),
                "allocations": {key: len(value) for key, value in allocations.items()},
                "blocked_topics": blocked_topics,
            }
        )
        current_signature = (
            reserve_id,
            tuple((research_id, tuple(ids)) for research_id, ids in sorted(allocations.items())),
        )
        changed = current_signature != previous_signature
        assigned_count = sum(len(ids) for ids in allocations.values())
        reserved_name = reserved.get("name") if reserved else None
        message = f"自动研究已重新调度 {assigned_count} 人"
        if reserved_name:
            message += f"，为训练预留 {reserved_name}"
        if blocked_topics:
            message += f"；{len(blocked_topics)} 个课题因立项资金不足等待中"
        return {
            "changed": changed,
            "message": message,
            "allocations": automation["allocations"],
            "reserved_employee_id": reserve_id,
            "reserved_name": reserved_name,
            "blocked_topics": blocked_topics,
        }

    def _research_fit(self, state: dict, employee: dict, research_cfg: dict) -> float:
        requirements = research_cfg.get("required_skills") or {}
        skills = employee.get("skills") or {}
        if not requirements:
            return (
                sum(float(value) for value in skills.values())
                / max(1, len(skills))
                * calc.team_skill_multiplier(state)
            )
        weight_total = sum(max(0.1, float(weight)) for weight in requirements.values())
        return sum(
            calc.employee_skill(state, employee, skill) * max(0.1, float(weight))
            for skill, weight in requirements.items()
        ) / max(weight_total, 0.1)

    def _training_fit(self, state: dict, employee: dict) -> float:
        profiles = (
            calc.employee_skill(state, employee, "ml_theory") * 0.65
            + calc.employee_skill(state, employee, "systems") * 0.35,
            calc.employee_skill(state, employee, "ml_theory") * 0.6
            + calc.employee_skill(state, employee, "data_eng") * 0.4,
            calc.employee_skill(state, employee, "rl") * 0.6
            + calc.employee_skill(state, employee, "alignment") * 0.4,
        )
        return max(profiles)

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

    def _category_staff_counts(self, state: dict) -> dict[str, int]:
        assigned: dict[str, set[str]] = {
            category: set() for category in self.CATEGORIES
        }
        for cur in state.get("research", {}).get("levels", {}).values():
            if not isinstance(cur, dict):
                continue
            category = cur.get("category") or "model"
            assigned.setdefault(category, set()).update(cur.get("employee_ids") or [])
        return {category: len(employee_ids) for category, employee_ids in assigned.items()}

    def _enforce_category_staff_caps(self, state: dict) -> None:
        """Trim overflow from legacy state while keeping earlier topic teams stable."""
        used: dict[str, set[str]] = {category: set() for category in self.CATEGORIES}
        for research_id, cur in state.get("research", {}).get("levels", {}).items():
            if not isinstance(cur, dict):
                continue
            category = cur.get("category") or "model"
            cap = int(self.CATEGORY_STAFF_CAPS.get(category, 20))
            kept: list[str] = []
            for employee_id in cur.get("employee_ids") or []:
                if employee_id in used.setdefault(category, set()):
                    continue
                if len(used[category]) >= cap:
                    employee = next(
                        (item for item in state.get("employees", []) if item["id"] == employee_id),
                        None,
                    )
                    if employee and employee.get("assigned_to") == f"research:{research_id}":
                        employee["assigned_to"] = None
                    continue
                used[category].add(employee_id)
                kept.append(employee_id)
                employee = next(
                    (item for item in state.get("employees", []) if item["id"] == employee_id),
                    None,
                )
                if employee:
                    employee["assigned_to"] = f"research:{research_id}"
            if len(kept) != len(cur.get("employee_ids") or []):
                cur["employee_ids"] = kept
                cur["paused"] = not bool(kept)

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
                    skill_score += max(
                        0.0,
                        calc.employee_skill(state, emp, sk) / max(need * 20, 1),
                    )
                skill_score /= max(len(req), 1)
            else:
                skills = emp.get("skills") or {}
                skill_score = (
                    sum(float(value) for value in skills.values())
                    * calc.team_skill_multiplier(state)
                    / max(len(skills), 1)
                    / 50.0
                )
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
