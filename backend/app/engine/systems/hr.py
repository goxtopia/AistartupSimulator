"""HR system: recruitment, training, morale, poaching, hidden tags."""

from __future__ import annotations

import uuid
from typing import Any

from backend.app.engine.calculators.scores import (
    chief_scientist_profile,
    clamp,
    compute_company_tendencies,
    team_skill_multiplier,
)


class HRSystem:
    name = "hr"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        state["employees"] = []
        state["hr"] = {
            "candidates": [],
            "talent_pool_boost": 0,
            "recruit_cost_mult": 1.0,
            "last_refresh_day": 0,
            "poach_cooldown": 0,
            "chief_scientist_id": None,
            "auto_hire": {
                "enabled": False,
                "status": "off",
                "hires_completed": 0,
                "last_hire_day": -999,
                "max_hires_per_cycle": 3,
            },
        }
        self.refresh_candidates(state, ctx, count=6)

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        day = state.get("day", 0)
        hr = state.setdefault("hr", {})

        # Monthly salary
        if day > 0 and day % 30 < days:
            total = sum(float(e.get("salary", 0)) for e in state.get("employees", []))
            state["company"]["capital"] = float(state["company"].get("capital", 0)) - total
            if total > 0:
                events.append({"type": "salary", "msg": f"发放月薪 -${total:,.0f}", "amount": -total})

        # Train passive XP for assigned researchers
        for emp in state.get("employees", []):
            self._tick_employee(emp, state, ctx, days)

        # Morale / leave checks
        tendencies = compute_company_tendencies(state, ctx.configs())
        state["company"]["tendencies"] = {**state["company"].get("tendencies", {}), **tendencies}

        leavers = []
        for emp in list(state.get("employees", [])):
            sat = self._satisfaction(emp, tendencies)
            emp["satisfaction"] = round(sat, 1)
            emp["morale"] = clamp(float(emp.get("morale", 70)) + (sat - 50) * 0.02 * days)
            leave_chance = 0.002 * days
            if sat < 35:
                leave_chance += 0.01 * days
            if sat < 20:
                leave_chance += 0.03 * days
            for tag in emp.get("hidden_tags", []):
                leave_chance += float(
                    ctx.configs().get("employees", "hidden_tags", tag, "effect", "leave_chance", default=0) or 0
                ) * 0.01 * days
            if emp.get("morale", 70) < 25:
                leave_chance += 0.02 * days
            if ctx.rng().random() < leave_chance:
                leavers.append(emp)

        for emp in leavers:
            _ok, msg, _departed = self.voluntary_leave(
                state,
                emp["id"],
                reason="因倾向不被满足而主动离职",
            )
            events.append({"type": "leave", "msg": msg, "employee_id": emp["id"]})

        # Refresh candidates periodically
        if day - int(hr.get("last_refresh_day", 0)) >= 7:
            self.refresh_candidates(state, ctx, count=4)
            hr["last_refresh_day"] = day

        auto_hire_event = self._run_auto_hire_batch(state, ctx)
        if auto_hire_event:
            events.append(auto_hire_event)

        if hr.get("poach_cooldown", 0) > 0:
            hr["poach_cooldown"] = max(0, int(hr["poach_cooldown"]) - days)

        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        self._ensure_hr_state(state)
        chief = chief_scientist_profile(state)
        multiplier = team_skill_multiplier(state)
        employees = [
            {
                **employee,
                "severance_cost": round(float(employee.get("salary", 0)) * 0.5, 2),
                "is_chief_scientist": bool(chief and chief["employee_id"] == employee["id"]),
                "effective_skill_multiplier": round(multiplier, 3),
                "effective_skills": {
                    key: round(float(value) * multiplier, 1)
                    for key, value in (employee.get("skills") or {}).items()
                },
            }
            for employee in state.get("employees", [])
        ]
        candidates = [
            {**candidate, "hire_cost": round(self._hire_cost(state, ctx, candidate), 2)}
            for candidate in state.get("hr", {}).get("candidates", [])
        ]
        poach_estimates = {}
        for competitor in state.get("competitors", []):
            roster = list(competitor.get("employees") or [])
            if not roster:
                continue
            ranked = sorted(
                roster,
                key=lambda employee: sum(float(value) for value in (employee.get("skills") or {}).values()),
                reverse=True,
            )[:5]
            offers = {}
            for multiplier in (1.5, 2.2):
                costs = [
                    float(person.get("salary", 15000)) * 2 * multiplier
                    + float(person.get("signing_bonus", person.get("salary", 15000))) * multiplier
                    for person in ranked
                ]
                offers[str(multiplier)] = {
                    "min_total": round(min(costs), 2),
                    "max_total": round(max(costs), 2),
                    "min_search": round(min(costs) * 0.3, 2),
                    "max_search": round(max(costs) * 0.3, 2),
                }
            poach_estimates[competitor["id"]] = offers
        return {
            "employees": employees,
            "candidates": candidates,
            "poach_cooldown": state.get("hr", {}).get("poach_cooldown", 0),
            "poach_estimates": poach_estimates,
            "chief_scientist": chief,
            "auto_hire": dict(state.get("hr", {}).get("auto_hire", {})),
        }

    # ---- actions ----

    def refresh_candidates(self, state: dict[str, Any], ctx, count: int = 5) -> list[dict]:
        cfg = ctx.configs().load("employees")
        country = state["company"]["country"]
        boost = int(state.get("hr", {}).get("talent_pool_boost", 0))
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        pool_mult = float(country_cfg.get("talent_pool_size", 1.0))
        n = max(3, int(count * pool_mult) + boost // 3)
        candidates = [self._gen_person(state, ctx, cfg, country, for_hire=True) for _ in range(n)]
        # Keep some old ones
        old = state.get("hr", {}).get("candidates", [])
        keep = [c for c in old if ctx.rng().random() < 0.3][:3]
        state.setdefault("hr", {})["candidates"] = (keep + candidates)[:12]
        state["hr"]["talent_pool_boost"] = max(0, boost - 1)
        return state["hr"]["candidates"]

    def hire(self, state: dict[str, Any], ctx, candidate_id: str) -> tuple[bool, str, dict | None]:
        hr = state.setdefault("hr", {})
        cand = next((c for c in hr.get("candidates", []) if c["id"] == candidate_id), None)
        if not cand:
            return False, "候选人不存在或已失效", None
        cost = self._hire_cost(state, ctx, cand)

        if state["company"]["capital"] < cost:
            return False, f"资金不足（需要 ${cost:,.0f}）", None

        state["company"]["capital"] -= cost
        emp = {**cand, "hired_day": state.get("day", 0), "revealed_tags": True}
        # Reveal hidden tags on hire
        emp["hidden_tags_visible"] = list(emp.get("hidden_tags", []))
        # media_savvy rep
        for tag in emp.get("hidden_tags", []):
            rep = ctx.configs().get("employees", "hidden_tags", tag, "effect", "public_rep_on_hire", default=None)
            if rep:
                t = state["company"].setdefault("tendencies", {})
                t["public_rep"] = clamp(float(t.get("public_rep", 20)) + float(rep))

        state.setdefault("employees", []).append(emp)
        hr["candidates"] = [c for c in hr["candidates"] if c["id"] != candidate_id]
        return True, f"已雇佣 {emp['name']}", emp

    def fire(self, state: dict[str, Any], employee_id: str) -> tuple[bool, str]:
        emps = state.get("employees", [])
        emp = next((e for e in emps if e["id"] == employee_id), None)
        if not emp:
            return False, "员工不存在"
        emps.remove(emp)
        if state.get("hr", {}).get("chief_scientist_id") == employee_id:
            state["hr"]["chief_scientist_id"] = None
        self._unassign(state, employee_id)
        # Severance
        sev = float(emp.get("salary", 0)) * 0.5
        state["company"]["capital"] -= sev
        return True, f"已解雇 {emp['name']}（补偿 ${sev:,.0f}）"

    def set_chief_scientist(
        self, state: dict[str, Any], employee_id: str | None
    ) -> tuple[bool, str, dict | None]:
        hr = state.setdefault("hr", {})
        if not employee_id:
            previous = chief_scientist_profile(state)
            hr["chief_scientist_id"] = None
            if not previous:
                return True, "当前没有首席科学家", None
            return True, f"已解除 {previous['name']} 的首席科学家职务", None
        employee = next(
            (item for item in state.get("employees", []) if item["id"] == employee_id), None
        )
        if not employee:
            return False, "只能从在职员工中任命首席科学家", None
        hr["chief_scientist_id"] = employee_id
        profile = chief_scientist_profile(state)
        return (
            True,
            f"已任命 {employee['name']} 为首席科学家，全员能力 ×{profile['team_skill_multiplier']:.3f}",
            profile,
        )

    def set_auto_hire(
        self,
        state: dict[str, Any],
        ctx,
        enabled: bool,
        max_hires_per_cycle: int = 3,
    ) -> tuple[bool, str, dict]:
        self._ensure_hr_state(state)
        automation = state["hr"]["auto_hire"]
        was_enabled = bool(automation.get("enabled"))
        automation["max_hires_per_cycle"] = max(1, min(20, int(max_hires_per_cycle)))
        automation["enabled"] = bool(enabled)
        automation["updated_day"] = state.get("day", 0)
        if not enabled:
            automation["status"] = "off"
            automation["status_message"] = "自动雇佣已关闭"
            return True, "已关闭自动雇佣", automation
        automation["status"] = "planning"
        automation["status_message"] = "正在分析 AUTO 研究的人才缺口"
        if was_enabled:
            return (
                True,
                f"自动雇佣设置已更新：每 7 天最多 {automation['max_hires_per_cycle']} 人",
                automation,
            )
        event = self._run_auto_hire_batch(state, ctx, force=True)
        detail = event["msg"] if event else automation.get("status_message", "等待招聘")
        return True, f"已开启自动雇佣：{detail}", automation

    def _run_auto_hire_batch(
        self, state: dict[str, Any], ctx, *, force: bool = False
    ) -> dict[str, Any] | None:
        self._ensure_hr_state(state)
        automation = state["hr"]["auto_hire"]
        if not automation.get("enabled"):
            return None
        day = int(state.get("day", 0))
        if not force and day - int(automation.get("last_hire_day", -999)) < 7:
            automation["status"] = "cooldown"
            automation["status_message"] = (
                f"招聘团队正在评估新一批人才（每 7 天最多录用 "
                f"{int(automation.get('max_hires_per_cycle', 3))} 人）"
            )
            return None

        events: list[dict[str, Any]] = []
        limit = max(1, min(20, int(automation.get("max_hires_per_cycle", 3))))
        for _ in range(limit):
            event = self._run_auto_hire_once(state, ctx)
            if not event:
                break
            events.append(event)
        if not events:
            return None
        cycle_hires = [
            {
                "employee_id": event["employee_id"],
                "employee_name": event.get("employee_name"),
                "research_id": event["research_id"],
                "research_name": event.get("research_name"),
            }
            for event in events
        ]
        automation["last_cycle_hires"] = cycle_hires
        automation["hires_this_cycle"] = len(events)
        automation["status"] = "hired"
        automation["status_message"] = (
            f"本轮已自动录用 {len(events)} 人："
            + "、".join(item.get("employee_name") or item["employee_id"] for item in cycle_hires)
        )
        msg = f"自动雇佣本轮完成：录用 {len(events)} 人（上限 {limit} 人）"
        return {"type": "auto_hire_batch", "msg": msg, "hires": cycle_hires}

    def _run_auto_hire_once(self, state: dict[str, Any], ctx) -> dict[str, Any] | None:
        automation = state["hr"]["auto_hire"]
        day = int(state.get("day", 0))

        research_cfg = ctx.configs().load("research")
        levels = state.get("research", {}).get("levels", {})
        topics: list[dict[str, Any]] = []
        category_used: dict[str, set[str]] = {"model": set(), "data": set(), "compute": set()}
        for research_id, current in levels.items():
            if not isinstance(current, dict):
                continue
            category = str(current.get("category") or "model")
            category_used.setdefault(category, set()).update(current.get("employee_ids") or [])
            if not current.get("auto_enabled"):
                continue
            cfg_key = {
                "model": "model_research",
                "data": "data_research",
                "compute": "compute_research",
            }.get(category, "model_research")
            config = research_cfg.get(cfg_key, {}).get(research_id, {})
            pending_employees = [
                employee
                for employee in state.get("employees", [])
                if employee.get("auto_hire_target_research_id") == research_id
                and not employee.get("assigned_to")
            ]
            category_used.setdefault(category, set()).update(
                employee["id"] for employee in pending_employees
            )
            assigned = len(current.get("employee_ids") or []) + len(pending_employees)
            desired = min(4, max(2, int(round(float(config.get("base_time_days", 14)) / 7.0))))
            topics.append(
                {
                    "id": research_id,
                    "name": config.get("name", research_id),
                    "category": category,
                    "config": config,
                    "assigned": assigned,
                    "desired": desired,
                    "deficit": max(0, desired - assigned),
                }
            )
        if not topics:
            automation.update(
                {
                    "status": "waiting_auto_research",
                    "status_message": "尚未开启任何 AUTO 研究课题",
                    "target_research_id": None,
                    "candidate_id": None,
                }
            )
            return None

        topics = [
            topic
            for topic in topics
            if topic["deficit"] > 0
            and len(category_used.get(topic["category"], set())) < 20
        ]
        if not topics:
            automation.update(
                {
                    "status": "staffed",
                    "status_message": "所有 AUTO 研究已达到建议团队规模",
                    "target_research_id": None,
                    "candidate_id": None,
                }
            )
            return None

        candidates = list(state.get("hr", {}).get("candidates", []))
        choices: list[tuple[int, float, float, dict, dict, float]] = []
        for topic in topics:
            for candidate in candidates:
                fit = self._auto_hire_research_fit(state, candidate, topic["config"])
                if fit < 25.0:
                    continue
                cost = self._hire_cost(state, ctx, candidate)
                unmet = 1 if topic["assigned"] == 0 else 0
                marginal = 1.0 / (1.0 + 0.42 * topic["assigned"])
                benefit = fit * marginal * (1.45 if unmet else 1.0)
                roi = benefit / max(cost + float(candidate.get("salary", 0)) * 2.0, 1.0) * 100_000
                choices.append((unmet, roi, fit, topic, candidate, cost))
        if not choices:
            automation.update(
                {
                    "status": "waiting_candidate",
                    "status_message": "人才市场暂无符合 AUTO 研究技能要求的候选人",
                    "candidate_id": None,
                }
            )
            return None

        unmet, roi, fit, topic, candidate, cost = max(
            choices, key=lambda item: (item[0], item[1], item[2])
        )
        monthly_payroll = sum(float(employee.get("salary", 0)) for employee in state.get("employees", []))
        cash_reserve = max(100_000.0, monthly_payroll * 3.0)
        automation.update(
            {
                "target_research_id": topic["id"],
                "target_research_name": topic["name"],
                "target_unmet": bool(unmet),
                "candidate_id": candidate["id"],
                "candidate_name": candidate.get("name"),
                "candidate_fit": round(fit, 1),
                "candidate_roi": round(roi, 2),
                "estimated_hire_cost": round(cost, 2),
                "cash_reserve": round(cash_reserve, 2),
            }
        )
        if float(state.get("company", {}).get("capital", 0)) - cost < cash_reserve:
            automation["status"] = "waiting_funds"
            automation["status_message"] = (
                f"等待资金：{candidate.get('name')} 适合 {topic['name']}，"
                f"但需保留 ${cash_reserve:,.0f} 安全现金"
            )
            return None

        ok, message, employee = self.hire(state, ctx, candidate["id"])
        if not ok or not employee:
            automation["status"] = "waiting"
            automation["status_message"] = message
            return None
        employee["auto_hire_target_research_id"] = topic["id"]
        automation.update(
            {
                "status": "hired",
                "status_message": (
                    f"已为 {topic['name']} 招聘 {employee['name']}；"
                    f"匹配 {fit:.0f}，收益成本分 {roi:.1f}"
                ),
                "last_hire_day": day,
                "hires_completed": int(automation.get("hires_completed", 0)) + 1,
                "last_employee_id": employee["id"],
                "last_employee_name": employee.get("name"),
            }
        )
        msg = f"自动雇佣：{employee['name']} 加入公司，优先补充 {topic['name']}"
        state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "hr"})
        return {
            "type": "auto_hire",
            "msg": msg,
            "employee_id": employee["id"],
            "employee_name": employee.get("name"),
            "research_id": topic["id"],
            "research_name": topic["name"],
        }

    def _auto_hire_research_fit(
        self, state: dict[str, Any], candidate: dict, research_config: dict
    ) -> float:
        requirements = research_config.get("required_skills") or {}
        skills = candidate.get("skills") or {}
        if not requirements:
            return (
                sum(float(value) for value in skills.values())
                / max(1, len(skills))
                * team_skill_multiplier(state)
            )
        total_weight = sum(max(0.1, float(weight)) for weight in requirements.values())
        return sum(
            float(skills.get(skill, 0))
            * team_skill_multiplier(state)
            * max(0.1, float(weight))
            for skill, weight in requirements.items()
        ) / max(total_weight, 0.1)

    def _ensure_hr_state(self, state: dict[str, Any]) -> None:
        hr = state.setdefault("hr", {})
        hr.setdefault("chief_scientist_id", None)
        hr.setdefault(
            "auto_hire",
            {
                "enabled": False,
                "status": "off",
                "hires_completed": 0,
                "last_hire_day": -999,
                "max_hires_per_cycle": 3,
            },
        )
        hr["auto_hire"].setdefault("max_hires_per_cycle", 3)

    def voluntary_leave(
        self,
        state: dict[str, Any],
        employee_id: str,
        *,
        reason: str = "主动离职",
    ) -> tuple[bool, str, dict | None]:
        """Remove an employee without severance or any other capital adjustment."""
        employees = state.get("employees", [])
        employee = next((item for item in employees if item["id"] == employee_id), None)
        if not employee:
            return False, "员工不存在", None
        employees.remove(employee)
        if state.get("hr", {}).get("chief_scientist_id") == employee_id:
            state["hr"]["chief_scientist_id"] = None
        self._unassign(state, employee_id)
        msg = f"{employee['name']} {reason}（不支付离职补偿）"
        state.setdefault("log", []).append(
            {"day": state.get("day", 0), "msg": msg, "cat": "hr"}
        )
        return True, msg, employee

    def train_skill(self, state: dict[str, Any], ctx, employee_id: str, skill: str, intensity: float = 1.0) -> tuple[bool, str]:
        emp = next((e for e in state.get("employees", []) if e["id"] == employee_id), None)
        if not emp:
            return False, "员工不存在"
        skills_cfg = ctx.configs().get("employees", "skills", default={}) or {}
        if skill not in skills_cfg:
            return False, "未知技能"
        cost = 2000 * intensity
        if state["company"]["capital"] < cost:
            return False, "资金不足"
        state["company"]["capital"] -= cost
        skills = emp.setdefault("skills", {})
        cur = float(skills.get(skill, 0))
        gain = (3.0 + (100 - cur) * 0.02) * intensity
        # tags
        for tag in emp.get("hidden_tags", []):
            eff = ctx.configs().get("employees", "hidden_tags", tag, "effect", default={}) or {}
            focus = emp.get("skill_focus", [])
            if tag == "specialist" or "main_skill_bonus" in eff:
                if skill in focus:
                    gain *= 1.0 + float(eff.get("main_skill_bonus", 0))
                else:
                    gain *= 1.0 + float(eff.get("other_skill_penalty", 0))
            if "cross_train" in eff:
                gain *= 1.0 + float(eff["cross_train"]) * 0.5
        skills[skill] = round(clamp(cur + gain, 0, 100), 1)
        emp["morale"] = clamp(float(emp.get("morale", 70)) - 2 * intensity + 1)
        return True, f"{emp['name']} 的 {skills_cfg[skill]['name']} → {skills[skill]}"

    def try_poach(self, state: dict[str, Any], ctx, company_id: str, offer_mult: float = 1.5) -> tuple[bool, str, dict | None]:
        """Poach a real employee from a rival roster (falls back to generated talent)."""
        hr = state.setdefault("hr", {})
        if hr.get("poach_cooldown", 0) > 0:
            return False, f"挖角冷却中（{hr['poach_cooldown']} 天）", None
        comps = state.get("competitors", [])
        comp = next((c for c in comps if c["id"] == company_id), None)
        if not comp:
            return False, "目标公司不存在", None

        rng = ctx.rng()
        roster = list(comp.get("employees") or [])
        from_roster = bool(roster)
        if from_roster:
            # Prefer higher-skill targets
            def power(e: dict) -> float:
                skills = e.get("skills") or {}
                return sum(float(v) for v in skills.values()) / max(len(skills), 1) + {
                    "junior": 0, "mid": 5, "senior": 15, "staff": 25, "principal": 35
                }.get(e.get("seniority"), 0)

            ranked = sorted(roster, key=power, reverse=True)
            person = dict(rng.choice(ranked[: min(5, len(ranked))]))
        else:
            cfg = ctx.configs().load("employees")
            person = self._gen_person(
                state, ctx, cfg, comp.get("country", state["company"]["country"]), for_hire=True
            )

        person["from_company"] = comp["name"]
        base_p = 0.12 + (offer_mult - 1.0) * 0.12
        base_p += float(state["company"].get("tendencies", {}).get("public_rep", 20)) / 500.0
        base_p -= float(comp.get("strength", 0.5)) * 0.12
        base_p -= {"titan": 0.08, "challenger": 0.03, "startup": -0.05}.get(comp.get("tier"), 0)
        if "job_hopper" in person.get("hidden_tags", []):
            base_p += 0.15
        if "loyalist" in person.get("hidden_tags", []):
            base_p -= 0.2

        cost = float(person.get("salary", 15000)) * 2 * offer_mult + float(
            person.get("signing_bonus", person.get("salary", 15000))
        ) * offer_mult
        if state["company"]["capital"] < cost:
            return False, f"资金不足（需要 ${cost:,.0f}）", None

        state["company"]["capital"] -= cost * 0.3  # search cost always
        hr["poach_cooldown"] = 14
        if rng.random() < clamp(base_p, 0.02, 0.75):
            state["company"]["capital"] -= cost * 0.7
            # remove from rival roster if real
            if from_roster:
                comp["employees"] = [e for e in roster if e.get("id") != person.get("id")]
            person["salary"] = round(float(person.get("salary", 15000)) * offer_mult, 0)
            person["hired_day"] = state.get("day", 0)
            person["revealed_tags"] = True
            person["hidden_tags_visible"] = list(person.get("hidden_tags", []))
            person["morale"] = 78
            person["employer"] = "player"
            person.pop("assigned_to", None)
            state.setdefault("employees", []).append(person)
            # rival may retaliate with shorter poach cooldown
            comp["poach_cooldown"] = min(int(comp.get("poach_cooldown", 0)), 3)
            return True, f"成功从 {comp['name']} 挖到 {person['name']}！", person
        return False, f"挖角失败（已支付搜寻费 ${cost*0.3:,.0f}）", None

    # ---- internals ----

    def _hire_cost(self, state: dict, ctx, candidate: dict) -> float:
        cost = float(candidate.get("signing_bonus", 0)) + float(candidate.get("salary", 0))
        country_cfg = ctx.configs().get(
            "countries", "countries", state["company"]["country"], default={}
        ) or {}
        cost *= float(country_cfg.get("talent_cost_multiplier", 1.0))
        cost *= float(state.get("hr", {}).get("recruit_cost_mult", 1.0))
        cost *= float(
            state["company"].get("founder_background_cfg", {}).get("recruit_cost_multiplier", 1.0)
        )
        return cost

    def _gen_person(self, state, ctx, cfg, country: str, for_hire: bool = False) -> dict:
        rng = ctx.rng()
        names = cfg.get("name_pools", {}).get(country) or cfg.get("name_pools", {}).get("usa")
        gender = rng.choice(["male", "female"])
        family = rng.choice(names["family"])
        given = rng.choice(names["given_m"] if gender == "male" else names["given_f"])
        # East-Asian order
        if country in ("china", "japan", "korea"):
            full = f"{family}{given}"
        else:
            full = f"{given} {family}"

        roles = list(cfg.get("roles", {}).values())
        role = rng.choice(roles)
        seniority = rng.choices(
            cfg.get("seniority_levels", []),
            weights=[30, 35, 20, 10, 5],
            k=1,
        )[0]

        lo, hi = seniority["skill_range"]
        skills = {sid: 5.0 for sid in cfg.get("skills", {})}
        for focus in role.get("skill_focus", []):
            skills[focus] = float(rng.randint(lo, hi))
        # some secondary
        for sid in rng.sample(list(skills.keys()), k=min(3, len(skills))):
            skills[sid] = max(skills[sid], float(rng.randint(max(5, lo - 15), hi - 5)))

        # Tendencies preferences (what they care about) 0-100 weight importance + ideal
        tend_cfg = cfg.get("tendencies", {})
        preferences = {}
        for tid in tend_cfg:
            preferences[tid] = {
                "weight": round(rng.uniform(0.3, 1.5), 2),
                "ideal": round(rng.uniform(20, 90), 1),
            }
        # One dominant tendency
        dom = rng.choice(list(preferences.keys()))
        preferences[dom]["weight"] = round(rng.uniform(1.2, 2.0), 2)

        # 1-2 hidden tags
        tag_ids = list(cfg.get("hidden_tags", {}).keys())
        n_tags = 1 if rng.random() < 0.6 else 2
        hidden = rng.sample(tag_ids, k=min(n_tags, len(tag_ids)))

        salary = role["salary_base"] * seniority["salary_mult"]
        for tag in hidden:
            eff = cfg["hidden_tags"][tag].get("effect", {})
            if "salary_demand" in eff:
                salary *= 1.0 + float(eff["salary_demand"])
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        salary *= float(country_cfg.get("talent_cost_multiplier", 1.0))

        return {
            "id": str(uuid.uuid4())[:8],
            "name": full,
            "gender": gender,
            "country": country,
            "role": role["id"],
            "role_name": role["name"],
            "seniority": seniority["id"],
            "seniority_name": seniority["name"],
            "skills": {k: round(v, 1) for k, v in skills.items()},
            "skill_focus": role.get("skill_focus", []),
            "preferences": preferences,
            "hidden_tags": hidden,
            "hidden_tags_visible": [],  # empty until hired
            "salary": round(salary, 0),
            "signing_bonus": round(salary * rng.uniform(0.5, 2.0), 0),
            "morale": round(rng.uniform(55, 85), 1),
            "satisfaction": 50.0,
            "fatigue": 0.0,
            "xp": 0.0,
            "assigned_to": None,
        }

    def _satisfaction(self, emp: dict, tendencies: dict[str, float]) -> float:
        prefs = emp.get("preferences", {})
        if not prefs:
            return 60.0
        total_w = 0.0
        score = 0.0
        for tid, pref in prefs.items():
            w = float(pref.get("weight", 1.0))
            ideal = float(pref.get("ideal", 50))
            actual = float(tendencies.get(tid, 50))
            # closer to ideal = better; distance 0 -> 100, distance 100 -> 0
            dist = abs(actual - ideal)
            part = max(0.0, 100.0 - dist * 1.4)
            score += part * w
            total_w += w
        return score / total_w if total_w else 50.0

    def _tick_employee(self, emp: dict, state: dict, ctx, days: int) -> None:
        # Fatigue recovery / buildup
        assigned = emp.get("assigned_to")
        fatigue_rate = 0.5 if assigned else -1.0
        for tag in emp.get("hidden_tags", []):
            fr = ctx.configs().get("employees", "hidden_tags", tag, "effect", "fatigue_rate", default=None)
            if fr:
                fatigue_rate += float(fr)
        emp["fatigue"] = clamp(float(emp.get("fatigue", 0)) + fatigue_rate * days, 0, 100)
        if emp["fatigue"] > 80:
            emp["morale"] = clamp(float(emp.get("morale", 70)) - 0.5 * days)

        # Passive skill drip if assigned
        if assigned:
            focus = emp.get("skill_focus") or list(emp.get("skills", {}).keys())[:1]
            for sk in focus[:2]:
                cur = float(emp["skills"].get(sk, 0))
                emp["skills"][sk] = round(clamp(cur + 0.05 * days), 1)

    def _unassign(self, state: dict, employee_id: str) -> None:
        for emp in state.get("employees", []):
            if emp["id"] == employee_id:
                emp["assigned_to"] = None
        # Continuous research stores staff on level entries
        for rid, cur in (state.get("research", {}).get("levels") or {}).items():
            if isinstance(cur, dict):
                ids = cur.get("employee_ids") or []
                if employee_id in ids:
                    cur["employee_ids"] = [i for i in ids if i != employee_id]
        for job in state.get("research", {}).get("active", []):
            ids = job.get("employee_ids", [])
            if employee_id in ids:
                job["employee_ids"] = [i for i in ids if i != employee_id]
        for job in state.get("training", {}).get("active", []):
            ids = job.get("employee_ids", [])
            if employee_id in ids:
                job["employee_ids"] = [i for i in ids if i != employee_id]
        for job in state.get("training", {}).get("dataset_jobs", []):
            ids = job.get("employee_ids", [])
            if employee_id in ids:
                job["employee_ids"] = [i for i in ids if i != employee_id]
                if not job["employee_ids"]:
                    job["paused"] = True
