"""AI rival companies — strategy-driven research, releases, and poaching."""

from __future__ import annotations

import uuid
from typing import Any

from backend.app.engine.calculators import scores as calc


class CompetitorsSystem:
    """Simulates rival labs as first-class agents.

    Each rival has:
      - strategy profile (from competitors.json)
      - capital / rep / research levels / employee roster
      - model catalog feeding market competition
      - active desire to poach the player's staff
    """

    name = "competitors"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        cfg = ctx.configs().load("competitors")
        strategies = cfg.get("strategies", {})
        rivals_out = []
        competitor_models: list[dict] = []
        open_extra: list[dict] = []

        for seed in cfg.get("rivals", []):
            strat_id = seed.get("strategy", "mixed_platform")
            strat = strategies.get(strat_id, {})
            rival = self._init_rival(seed, strat, ctx)
            rivals_out.append(rival)
            # seed a flagship model so market isn't empty
            model = self._build_model(rival, strat, ctx, version=1, force_open=None, day=0)
            competitor_models.append(model)
            if model.get("open_source"):
                open_extra.append(self._to_open_entry(model, rival))

        state["competitors"] = rivals_out
        # Keep legacy key used by training/market
        state["competitor_models"] = competitor_models
        state.setdefault("open_models", [])
        # merge without dup
        existing_ids = {m["id"] for m in state["open_models"]}
        for m in open_extra:
            if m["id"] not in existing_ids:
                state["open_models"].append(m)

        state["competitor_ai"] = {
            "action_log": [],
            "last_poach_day": -999,
            "threat_index": 0.0,
        }

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        cfg = ctx.configs().load("competitors")
        strategies = cfg.get("strategies", {})
        tick_cfg = cfg.get("ai_tick", {})
        day = int(state.get("day", 0))

        for _ in range(days):
            # We already advanced day in engine; process once per call-day via loop of 1 from engine.
            pass

        # Engine calls with days=1 usually; support multi-day batches too
        for step in range(days):
            # When batching, approximate day as current - days + step + 1 ... simpler: use state day only once.
            # Engine always passes days=1 in advance loop.
            break

        rivals = state.get("competitors", [])
        if not rivals:
            return events

        # Research progress every N days
        research_every = int(tick_cfg.get("research_check_every", 3))
        hire_every = int(tick_cfg.get("hire_check_every", 5))
        poach_every = int(tick_cfg.get("poach_check_every", 4))
        release_every = int(tick_cfg.get("release_check_every", 2))

        if day > 0 and day % research_every == 0:
            for rival in rivals:
                strat = strategies.get(rival.get("strategy"), {})
                msgs = self._tick_research(rival, strat, state, ctx)
                for m in msgs:
                    events.append(m)

        if day > 0 and day % hire_every == 0:
            for rival in rivals:
                strat = strategies.get(rival.get("strategy"), {})
                msg = self._tick_hire(rival, strat, state, ctx)
                if msg:
                    events.append(msg)

        if day > 0 and day % release_every == 0:
            for rival in rivals:
                strat = strategies.get(rival.get("strategy"), {})
                msg = self._tick_release(rival, strat, state, ctx)
                if msg:
                    events.append(msg)
                    self._log_action(state, day, msg.get("msg", ""), rival["id"])

        # Poaching — limited global attempts so player isn't drained every tick
        if day > 0 and day % poach_every == 0:
            max_attempts = int(tick_cfg.get("max_poach_attempts_per_tick", 1))
            # Only the most aggressive rivals still on cooldown=0 roll
            candidates = [
                r for r in rivals
                if int(r.get("poach_cooldown", 0)) <= 0
            ]
            ranked = sorted(
                candidates,
                key=lambda r: float(strategies.get(r.get("strategy"), {}).get("poach_aggression", 0.5))
                * float(r.get("strength", 0.5)),
                reverse=True,
            )
            # Each check: sample up to 3 rivals, at most max_attempts successes logged
            pool = ranked[:6]
            rng = ctx.rng()
            if pool:
                rng.shuffle(pool)
            attempts = 0
            for rival in pool:
                if attempts >= max_attempts:
                    break
                strat = strategies.get(rival.get("strategy"), {})
                msg = self._try_poach_player(rival, strat, state, ctx)
                if msg:
                    events.append(msg)
                    self._log_action(state, day, msg.get("msg", ""), rival["id"])
                    if msg.get("type") == "poach_success":
                        attempts += 1
                        # Global soft cooldown via competitor_ai
                        state.setdefault("competitor_ai", {})["last_poach_day"] = day
                # Stop entire wave shortly after a successful raid
                last = state.get("competitor_ai", {}).get("last_poach_day", -999)
                if day - int(last) == 0 and msg and msg.get("type") == "poach_success":
                    break

        # Capital / strength drift + revenue simulation (simplified)
        for rival in rivals:
            strat = strategies.get(rival.get("strategy"), {})
            self._tick_economy(rival, strat, state, ctx, days)

        # Threat index for UI
        player_best = max(
            (float(m.get("hidden_score", 0)) for m in state.get("models", []) if m.get("released")),
            default=0.0,
        )
        rival_best = max(
            (float(m.get("hidden_score", 0)) for m in state.get("competitor_models", []) if m.get("released")),
            default=0.0,
        )
        state.setdefault("competitor_ai", {})["threat_index"] = round(
            calc.clamp((rival_best - player_best + 40) / 80 * 100, 0, 100), 1
        )

        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        cfg = ctx.configs().load("competitors")
        strategies = cfg.get("strategies", {})
        public_rivals = []
        for r in state.get("competitors", []):
            strat = strategies.get(r.get("strategy"), {})
            models = [
                m
                for m in state.get("competitor_models", [])
                if m.get("company_id") == r["id"]
            ]
            public_rivals.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "country": r["country"],
                    "strategy": r.get("strategy"),
                    "strategy_name": strat.get("name", r.get("strategy")),
                    "strategy_desc": strat.get("description", ""),
                    "color": strat.get("color", "#38bdf8"),
                    "tier": r.get("tier", "challenger"),
                    "strength": round(float(r.get("strength", 0.5)), 3),
                    "public_rep": round(float(r.get("public_rep", 50)), 1),
                    "gov_relation": round(float(r.get("gov_relation", 20)), 1),
                    "open_ratio": round(float(r.get("open_ratio", 0.3)), 2),
                    "capital": round(float(r.get("capital", 0)), 0),
                    "employee_count": len(r.get("employees", [])),
                    "models_count": int(r.get("models_count", 0)),
                    "last_release_day": r.get("last_release_day", 0),
                    "personality": r.get("personality", ""),
                    "focus": list((r.get("research_levels") or {}).keys())[:5],
                    "top_research": self._top_research(r),
                    "flagship": self._flagship_public(models),
                    "recent_actions": list(r.get("recent_actions", []))[-5:],
                    "poach_cooldown": int(r.get("poach_cooldown", 0)),
                    # legacy aliases used by older UI
                    "open_source_pressure": strat.get("open_bias", 0.3),
                }
            )

        return {
            "rivals": public_rivals,
            # backward compatible list for HR poach buttons / market tab
            "competitors": public_rivals,
            "action_log": list(state.get("competitor_ai", {}).get("action_log", []))[-20:],
            "threat_index": state.get("competitor_ai", {}).get("threat_index", 0),
            "strategies": {
                k: {"id": k, "name": v.get("name"), "description": v.get("description"), "color": v.get("color")}
                for k, v in strategies.items()
            },
            "models": [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "company_id": m.get("company_id"),
                    "company": m.get("company"),
                    "hidden_score": m.get("hidden_score"),
                    "eval_avg": (m.get("eval_scores") or {}).get("average"),
                    "params_b": m.get("params_b"),
                    "open_source": m.get("open_source"),
                    "api_enabled": m.get("api_enabled"),
                    "price_output": m.get("price_output"),
                    "model_type": m.get("model_type"),
                }
                for m in state.get("competitor_models", [])
                if m.get("released")
            ],
        }

    # ------------------------------------------------------------------ init

    def _init_rival(self, seed: dict, strat: dict, ctx) -> dict:
        rng = ctx.rng()
        strength = float(seed.get("starting_strength", 0.6))
        research_levels: dict[str, int] = {}
        # seed research along focus
        bonus = int(seed.get("starting_research_bonus", 1))
        weights = strat.get("focus_weights") or {"performance": 1.0}
        for rid, w in weights.items():
            base = int(strength * 6 * w) + bonus
            research_levels[rid] = max(0, min(12, base + rng.randint(-1, 1)))

        # generate roster
        hr = None
        try:
            hr = ctx.get_system("hr")
        except Exception:
            hr = None
        employees = []
        n_emp = int(seed.get("starting_employees", 6))
        emp_cfg = ctx.configs().load("employees")
        for _ in range(n_emp):
            if hr:
                # Use HR generator without mutating player candidates
                p = hr._gen_person(
                    {"company": {"country": seed.get("country", "usa")}},
                    ctx,
                    emp_cfg,
                    seed.get("country", "usa"),
                    for_hire=True,
                )
            else:
                p = {
                    "id": str(uuid.uuid4())[:8],
                    "name": f"Eng-{rng.randint(100,999)}",
                    "salary": 15000,
                    "skills": {"ml_theory": 50},
                    "seniority": "mid",
                    "hidden_tags": [],
                    "morale": 70,
                }
            p["employer"] = seed["id"]
            # slightly buff titan rosters
            if seed.get("tier") == "titan":
                for sk in list(p.get("skills", {})):
                    p["skills"][sk] = min(100, float(p["skills"][sk]) + rng.uniform(5, 15))
            employees.append(p)

        open_ratio = float(strat.get("open_bias", 0.3))
        return {
            "id": seed["id"],
            "name": seed["name"],
            "country": seed.get("country", "usa"),
            "strategy": seed.get("strategy"),
            "tier": seed.get("tier", "challenger"),
            "strength": strength,
            "capital": float(seed.get("starting_capital", 10_000_000)),
            "public_rep": float(seed.get("starting_rep", 50)),
            "gov_relation": float(seed.get("starting_gov", 20)),
            "open_ratio": open_ratio,
            "research_levels": research_levels,
            "employees": employees,
            "models_count": 1,
            "last_release_day": 0,
            "next_release_day": rng.randint(18, 40),
            "poach_cooldown": rng.randint(12, 24),
            "personality": seed.get("personality", ""),
            "recent_actions": [],
            "focus": list(weights.keys())[:4],
            # legacy field used by old market code
            "strategy_legacy": "open" if open_ratio > 0.7 else ("closed" if open_ratio < 0.2 else "mixed"),
        }

    # ------------------------------------------------------------------ ticks

    def _tick_research(self, rival: dict, strat: dict, state: dict, ctx) -> list[dict]:
        rng = ctx.rng()
        pace = float(strat.get("research_pace", 1.0))
        weights = strat.get("focus_weights") or {"performance": 1.0}
        levels = rival.setdefault("research_levels", {})
        # pick weighted research to bump
        ids = list(weights.keys())
        w = [float(weights[i]) for i in ids]
        pick = rng.choices(ids, weights=w, k=1)[0]
        cur = int(levels.get(pick, 0))
        # team power
        team = len(rival.get("employees", []))
        chance = 0.35 * pace * (0.7 + min(team, 20) * 0.03) * (0.8 + float(rival.get("strength", 0.5)))
        msgs = []
        if rng.random() < chance and cur < 18:
            cost = 40000 * (1.35 ** cur)
            if rival["capital"] >= cost:
                rival["capital"] -= cost
                levels[pick] = cur + 1
                # tiny strength bump
                rival["strength"] = calc.clamp(
                    float(rival["strength"]) + 0.004 * pace, 0.2, 0.99
                )
                if rng.random() < 0.2:
                    msg = f"{rival['name']} 完成研究「{pick}」→ Lv.{cur+1}"
                    rival.setdefault("recent_actions", []).append(
                        {"day": state.get("day", 0), "msg": msg}
                    )
                    msgs.append({"type": "rival_research", "msg": msg, "rival_id": rival["id"]})
        return msgs

    def _tick_hire(self, rival: dict, strat: dict, state: dict, ctx) -> dict | None:
        rng = ctx.rng()
        pace = float(strat.get("hire_pace", 1.0))
        if rng.random() > 0.4 * pace:
            return None
        emp_cfg = ctx.configs().load("employees")
        hr = ctx.get_system("hr")
        if not hr:
            return None
        person = hr._gen_person(
            {"company": {"country": rival.get("country", "usa")}},
            ctx,
            emp_cfg,
            rival.get("country", "usa"),
            for_hire=True,
        )
        cost = float(person.get("salary", 15000)) * 3
        if rival["capital"] < cost:
            return None
        rival["capital"] -= cost
        person["employer"] = rival["id"]
        rival.setdefault("employees", []).append(person)
        # soft cap roster
        if len(rival["employees"]) > 40:
            rival["employees"] = rival["employees"][-40:]
        if rng.random() < 0.25:
            msg = f"{rival['name']} 新招募了 {person['name']}（{person.get('seniority_name','')}）"
            rival.setdefault("recent_actions", []).append({"day": state.get("day", 0), "msg": msg})
            return {"type": "rival_hire", "msg": msg, "rival_id": rival["id"]}
        return None

    def _tick_release(self, rival: dict, strat: dict, state: dict, ctx) -> dict | None:
        rng = ctx.rng()
        day = int(state.get("day", 0))
        if day < int(rival.get("next_release_day", 15)):
            return None
        # interval based on strategy
        lo, hi = (strat.get("release_interval_days") or [18, 35])[:2]
        rival["next_release_day"] = day + rng.randint(int(lo), int(hi))

        model = self._build_model(
            rival, strat, ctx, version=int(rival.get("models_count", 1)) + 1, day=day
        )
        model["released_day"] = day
        # replace previous main + keep history lightly
        models = state.setdefault("competitor_models", [])
        # demote old mains
        for m in models:
            if m.get("company_id") == rival["id"] and m.get("is_flagship"):
                m["is_flagship"] = False
        model["is_flagship"] = True
        models.append(model)
        # prune very old models per company (keep last 4)
        kept = []
        per: dict[str, int] = {}
        for m in reversed(models):
            cid = m.get("company_id", "")
            per[cid] = per.get(cid, 0) + 1
            if per[cid] <= 4:
                kept.append(m)
        state["competitor_models"] = list(reversed(kept))

        rival["models_count"] = int(rival.get("models_count", 1)) + 1
        rival["last_release_day"] = day

        # open weights market
        if model.get("open_source"):
            state.setdefault("open_models", []).append(self._to_open_entry(model, rival))
            # recompute open_ratio
            own = [m for m in state["competitor_models"] if m.get("company_id") == rival["id"]]
            if own:
                rival["open_ratio"] = sum(1 for m in own if m.get("open_source")) / len(own)

        # reputation
        if model.get("open_source"):
            rival["public_rep"] = calc.clamp(float(rival["public_rep"]) + 3 + model["hidden_score"] * 0.02)
        else:
            rival["public_rep"] = calc.clamp(float(rival["public_rep"]) + 1.5 + model["hidden_score"] * 0.01)

        label = "开源" if model.get("open_source") else "闭源"
        msg = (
            f"{rival['name']} 发布 {model['name']}（{label} · 隐藏分 {model['hidden_score']} · "
            f"EVAL {model['eval_scores'].get('average', 0)}）"
        )
        rival.setdefault("recent_actions", []).append({"day": day, "msg": msg})
        state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "rival"})
        return {"type": "rival_release", "msg": msg, "rival_id": rival["id"], "model_id": model["id"]}

    def _try_poach_player(self, rival: dict, strat: dict, state: dict, ctx) -> dict | None:
        rng = ctx.rng()
        day = int(state.get("day", 0))
        # Grace period — rivals scout before raiding
        if day < 25:
            return None
        if int(rival.get("poach_cooldown", 0)) > 0:
            return None
        # Global spacing: at most one successful industry raid every 10 days
        last_global = int(state.get("competitor_ai", {}).get("last_poach_day", -999))
        if day - last_global < 10:
            return None

        emps = list(state.get("employees", []))
        if not emps:
            return None

        aggression = float(strat.get("poach_aggression", 0.5))
        player_rep = float(state.get("company", {}).get("tendencies", {}).get("public_rep", 20))
        player_best = max(
            (float(m.get("hidden_score", 0)) for m in state.get("models", []) if m.get("released")),
            default=0.0,
        )
        # Notice the player once they have staff / models / some rep
        visibility = min(0.4, len(emps) * 0.03) + min(0.25, player_best / 180) + min(0.15, player_rep / 250)
        interest = aggression * (0.08 + visibility) * 0.65
        if rng.random() > interest:
            rival["poach_cooldown"] = rng.randint(5, 12)
            return None

        # score targets
        prefer_skills = set(strat.get("poach_prefer_skills") or [])
        prefer_open = bool(strat.get("poach_prefer_openness"))
        player_open = float(state.get("company", {}).get("tendencies", {}).get("openness", 30))

        def target_score(e: dict) -> float:
            skills = e.get("skills") or {}
            power = sum(float(v) for v in skills.values()) / max(len(skills), 1)
            seniority_bonus = {
                "junior": 0,
                "mid": 5,
                "senior": 15,
                "staff": 28,
                "principal": 40,
            }.get(e.get("seniority"), 5)
            sat = float(e.get("satisfaction", 50))
            # unhappy people easier
            soft = (60 - sat) * 0.4
            skill_match = 0.0
            if prefer_skills:
                skill_match = sum(float(skills.get(s, 0)) for s in prefer_skills) / max(len(prefer_skills), 1) * 0.3
            open_match = 0.0
            if prefer_open:
                # employee wants openness?
                pref = (e.get("preferences") or {}).get("openness", {})
                ideal = float(pref.get("ideal", 50))
                if player_open + 10 < ideal:
                    open_match = 20
            tags = e.get("hidden_tags") or []
            tag_bonus = 0.0
            if "job_hopper" in tags:
                tag_bonus += 15
            if "loyalist" in tags:
                tag_bonus -= 25
            if "prima_donna" in tags:
                tag_bonus += 5  # money talks
            return power + seniority_bonus + soft + skill_match + open_match + tag_bonus

        ranked = sorted(emps, key=target_score, reverse=True)
        # pick among top 3
        target = rng.choice(ranked[: min(3, len(ranked))])

        lo, hi = (strat.get("poach_offer_mult") or [1.4, 2.2])[:2]
        offer_mult = rng.uniform(float(lo), float(hi))
        offer_salary = float(target.get("salary", 15000)) * offer_mult
        signing = offer_salary * rng.uniform(1.0, 2.5)
        cost = offer_salary * 2 + signing
        if rival["capital"] < cost:
            return None

        # success probability — keep threatening but not company-ending
        sat = float(target.get("satisfaction", 50))
        morale = float(target.get("morale", 70))
        base_p = 0.04 + aggression * 0.07
        base_p += max(0, 45 - sat) * 0.003
        base_p += max(0, 50 - morale) * 0.002
        base_p += (offer_mult - 1.0) * 0.06
        base_p += float(rival.get("public_rep", 50)) / 1200.0
        base_p -= player_rep / 700.0
        base_p += float(rival.get("strength", 0.5)) * 0.04
        # harder to steal last few people
        if len(emps) <= 2:
            base_p *= 0.45
        tags = target.get("hidden_tags") or []
        if "job_hopper" in tags:
            base_p += 0.12
        if "loyalist" in tags:
            base_p -= 0.25
        if "prima_donna" in tags:
            base_p += 0.04 * (offer_mult - 1)

        success = rng.random() < calc.clamp(base_p, 0.015, 0.32)
        rival["capital"] -= cost * (0.15 if not success else 1.0)
        rival["poach_cooldown"] = rng.randint(18, 36)

        if not success:
            # small morale hit / awareness
            target["morale"] = calc.clamp(float(target.get("morale", 70)) - rng.uniform(1, 4))
            if rng.random() < 0.55:
                msg = f"{rival['name']} 试图挖角 {target['name']}，但被拒绝了（报价 {offer_mult:.1f}×）"
                state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "poach"})
                rival.setdefault("recent_actions", []).append({"day": day, "msg": msg})
                return {"type": "poach_fail", "msg": msg, "rival_id": rival["id"]}
            return None

        # SUCCESS — transfer employee
        state["employees"].remove(target)
        # unassign from player jobs
        hr = ctx.get_system("hr")
        if hr:
            hr._unassign(state, target["id"])

        target["salary"] = round(offer_salary, 0)
        target["employer"] = rival["id"]
        target["morale"] = calc.clamp(75 + rng.uniform(0, 15))
        target["satisfaction"] = calc.clamp(60 + rng.uniform(0, 20))
        target["from_company"] = state["company"]["name"]
        rival.setdefault("employees", []).append(target)

        # player morale shock
        for e in state.get("employees", []):
            e["morale"] = calc.clamp(float(e.get("morale", 70)) - rng.uniform(2, 6))

        msg = (
            f"⚠ {rival['name']} 挖走了 {target['name']}！"
            f"（{target.get('role_name', target.get('role', ''))} · 报价 {offer_mult:.1f}× 薪资）"
        )
        state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "poach"})
        rival.setdefault("recent_actions", []).append({"day": day, "msg": msg})
        # slight rep hit for player if principal/staff lost
        if target.get("seniority") in ("staff", "principal"):
            t = state["company"].setdefault("tendencies", {})
            t["public_rep"] = calc.clamp(float(t.get("public_rep", 20)) - 2)

        return {
            "type": "poach_success",
            "msg": msg,
            "rival_id": rival["id"],
            "employee_id": target["id"],
            "employee_name": target["name"],
        }

    def _tick_economy(self, rival: dict, strat: dict, state: dict, ctx, days: int) -> None:
        rng = ctx.rng()
        growth = float(strat.get("capital_growth", 1.0))
        # API income from flagship
        models = [m for m in state.get("competitor_models", []) if m.get("company_id") == rival["id"] and m.get("api_enabled")]
        daily = 0.0
        for m in models:
            h = float(m.get("hidden_score", 40))
            price = float(m.get("price_output", 5))
            daily += (h ** 1.2) * price * 15 * (0.6 + float(rival.get("public_rep", 50)) / 100)
        # scale by tier
        tier_mult = {"titan": 1.4, "challenger": 1.0, "startup": 0.7}.get(rival.get("tier"), 1.0)
        income = daily * tier_mult * growth * days
        # payroll
        payroll = sum(float(e.get("salary", 0)) for e in rival.get("employees", [])) / 30.0 * days
        rival["capital"] = float(rival["capital"]) + income - payroll
        # strength slow climb + noise
        rival["strength"] = calc.clamp(
            float(rival["strength"]) + rng.uniform(-0.002, 0.006) * days * float(strat.get("research_pace", 1)),
            0.25,
            0.99,
        )
        if rival.get("poach_cooldown", 0) > 0:
            rival["poach_cooldown"] = max(0, int(rival["poach_cooldown"]) - days)

    # ------------------------------------------------------------------ model build

    def _build_model(
        self,
        rival: dict,
        strat: dict,
        ctx,
        version: int = 1,
        force_open: bool | None = None,
        day: int = 0,
    ) -> dict:
        rng = ctx.rng()
        levels = rival.get("research_levels") or {}
        # hidden score from strength + research
        research_cfg = ctx.configs().load("research").get("model_research", {})
        # map only model research ids
        model_levels = {k: int(v) for k, v in levels.items() if k in research_cfg}
        # also allow data research names in levels for bias
        data_levels = {
            k: int(v)
            for k, v in levels.items()
            if k in ctx.configs().load("research").get("data_research", {})
        }

        # model type
        type_w = strat.get("model_type_weights") or {"text": 1.0}
        types = list(type_w.keys())
        tw = [float(type_w[t]) for t in types]
        model_type = rng.choices(types, weights=tw, k=1)[0]
        tcfg = ctx.configs().load("model_types").get("model_types", {}).get(model_type, {})

        params_pref = strat.get("param_pref") or [7, 13, 70]
        # weight later params higher as strength grows
        params_b = float(rng.choice(params_pref))
        if float(rival.get("strength", 0.5)) > 0.8 and len(params_pref) > 1:
            params_b = float(rng.choice(params_pref[len(params_pref) // 2 :]))

        capacity_lv = int(model_levels.get("capacity", max(1, int(rival.get("strength", 0.5) * 5))))
        hidden = calc.compute_hidden_score(
            capacity_level=capacity_lv,
            research_levels=model_levels,
            research_cfg=research_cfg,
            model_type_mult=float(tcfg.get("base_hidden_mult", 1.0)),
            params_b=params_b,
            data_quality=0.75 + float(rival.get("strength", 0.5)) * 0.4,
            training_days_factor=1.0,
            from_scratch=True,
            base_model_hidden=0.0,
        )
        # blend with strength; keep early game beatable (player starts weaker)
        strength_floor = 18 + float(rival.get("strength", 0.5)) * 55
        # slow ramp with calendar so day-0 flagships aren't unbeatable SOTA
        day_ramp = min(1.0, 0.55 + day / 180.0)
        hidden = round((hidden * 0.5 + strength_floor * 0.5) * day_ramp + rng.uniform(-4, 3), 2)
        hidden = calc.clamp(hidden, 5, 200)

        benchmarks = ctx.configs().load("market").get("eval_benchmarks", {})
        evals = calc.compute_eval_scores(
            hidden,
            research_levels=model_levels,
            data_levels=data_levels,
            benchmarks=benchmarks,
            model_type=model_type,
            rng=rng,
        )

        open_bias = float(strat.get("open_bias", 0.3))
        is_open = bool(rng.random() < open_bias) if force_open is None else force_open
        price_mult = float(strat.get("price_mult", 1.0))
        # better models slightly more expensive unless open-dump strategy
        base_price = 2.5 + hidden / 25.0
        price_out = round(max(0.2, base_price * price_mult * rng.uniform(0.85, 1.15)), 2)
        price_in = round(price_out * rng.uniform(0.25, 0.45), 2)
        if is_open:
            price_out = round(price_out * 0.6, 2)
            price_in = round(price_in * 0.6, 2)

        api = bool(strat.get("api_always", True)) or not is_open
        if is_open and not strat.get("api_always", True):
            api = rng.random() < 0.4

        mid = f"comp_{rival['id']}_v{version}_{str(uuid.uuid4())[:4]}"
        return {
            "id": mid if version > 1 else f"comp_{rival['id']}_main",
            "name": f"{rival['name']} {self._model_codename(model_type, params_b, version)}",
            "company_id": rival["id"],
            "company": rival["name"],
            "params_b": params_b,
            "hidden_score": hidden,
            "model_type": model_type,
            "source": "open" if is_open else "closed_competitor",
            "api_enabled": api,
            "open_source": is_open,
            "price_input": price_in,
            "price_output": price_out,
            "released": True,
            "eval_scores": evals,
            "is_flagship": True,
            "released_day": day,
            "segment_affinity": tcfg.get("segment_affinity", {}),
        }

    def _model_codename(self, model_type: str, params_b: float, version: int) -> str:
        prefix = {
            "text": "Foundation",
            "multimodal": "Prism",
            "image": "Canvas",
            "video": "Motion",
            "anytoany": "Omni",
        }.get(model_type, "Model")
        pb = int(params_b) if params_b >= 1 else params_b
        return f"{prefix}-{pb}B v{version}"

    def _to_open_entry(self, model: dict, rival: dict) -> dict:
        return {
            "id": model["id"] + "_wt",
            "name": model["name"] + " (weights)",
            "company": rival["name"],
            "company_id": rival["id"],
            "hidden_score": model["hidden_score"],
            "params_b": model["params_b"],
            "model_type": model.get("model_type", "text"),
            "source": "open",
        }

    def _top_research(self, rival: dict) -> list[dict]:
        levels = rival.get("research_levels") or {}
        items = sorted(levels.items(), key=lambda x: -int(x[1]))[:5]
        return [{"id": k, "level": int(v)} for k, v in items]

    def _flagship_public(self, models: list[dict]) -> dict | None:
        if not models:
            return None
        m = max(models, key=lambda x: float(x.get("hidden_score", 0)))
        return {
            "id": m["id"],
            "name": m["name"],
            "hidden_score": m.get("hidden_score"),
            "eval_avg": (m.get("eval_scores") or {}).get("average"),
            "open_source": m.get("open_source"),
            "price_output": m.get("price_output"),
            "params_b": m.get("params_b"),
            "model_type": m.get("model_type"),
        }

    def _log_action(self, state: dict, day: int, msg: str, rival_id: str) -> None:
        log = state.setdefault("competitor_ai", {}).setdefault("action_log", [])
        log.append({"day": day, "msg": msg, "rival_id": rival_id})
        limit = 40
        if len(log) > limit:
            del log[: len(log) - limit]
