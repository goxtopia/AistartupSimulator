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

    BUSINESS_MODELS = {
        "closed_frontier": {"id": "premium_api", "name": "高价前沿 API", "contract": 0.35, "ecosystem": 0.05, "government": 0.1, "margin": 0.7},
        "safety_first": {"id": "enterprise_safety", "name": "安全政企订阅", "contract": 1.35, "ecosystem": 0.08, "government": 0.8, "margin": 0.74},
        "open_weights": {"id": "open_ecosystem", "name": "开源生态与授权", "contract": 0.25, "ecosystem": 1.55, "government": 0.05, "margin": 0.48},
        "mixed_platform": {"id": "platform", "name": "平台 API + 企业套件", "contract": 0.75, "ecosystem": 0.65, "government": 0.25, "margin": 0.66},
        "efficient_open": {"id": "efficient_api", "name": "低价高吞吐 API", "contract": 0.3, "ecosystem": 0.8, "government": 0.1, "margin": 0.58},
        "domestic_scale": {"id": "domestic_enterprise", "name": "本地政企规模采购", "contract": 1.15, "ecosystem": 0.2, "government": 0.85, "margin": 0.68},
        "creative_open": {"id": "consumer_ecosystem", "name": "消费 API + 社区生态", "contract": 0.2, "ecosystem": 1.05, "government": 0.0, "margin": 0.5},
        "sovereign_compute": {"id": "sovereign_contracts", "name": "主权采购与算力服务", "contract": 0.7, "ecosystem": 0.25, "government": 1.6, "margin": 0.62},
        "talent_raider": {"id": "venture_growth", "name": "融资驱动的高价 API", "contract": 0.2, "ecosystem": 0.05, "government": 0.0, "margin": 0.64},
    }

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
            model = self._build_model(rival, strat, ctx, state=state, version=1, force_open=None, day=0)
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
            "bankruptcies": [],
            "entrant_count": 0,
            "next_entrant_day": ctx.rng().randint(95, 145),
            "last_player_distill_day": -999,
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

        ai_state = state.setdefault("competitor_ai", {})
        ai_state.setdefault("bankruptcies", [])
        ai_state.setdefault("entrant_count", 0)
        ai_state.setdefault("next_entrant_day", day + 90)
        ai_state.setdefault("last_player_distill_day", -999)
        rivals = [r for r in state.get("competitors", []) if not r.get("bankrupt")]

        # Research progress every N days
        research_every = int(tick_cfg.get("research_check_every", 3))
        hire_every = int(tick_cfg.get("hire_check_every", 5))
        poach_every = int(tick_cfg.get("poach_check_every", 4))
        release_every = int(tick_cfg.get("release_check_every", 2))
        pricing_every = int(tick_cfg.get("pricing_check_every", 7))
        distill_every = int(tick_cfg.get("distill_check_every", 11))

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

        if day > 0 and day % pricing_every == 0:
            for rival in rivals:
                self._tick_pricing(rival, strategies.get(rival.get("strategy"), {}), state, ctx)

        if day > 0 and day % distill_every == 0:
            msg = self._try_distill_player_model(rivals, strategies, state, ctx)
            if msg:
                events.append(msg)
                self._log_action(state, day, msg.get("msg", ""), msg.get("rival_id", ""))

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

        events.extend(self._handle_bankruptcies(state, ctx))
        entrant = self._maybe_new_entrant(state, ctx)
        if entrant:
            events.append(entrant)

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
            business = self._business_profile(r.get("strategy"), strat)
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
                    "business_model": business["id"],
                    "business_model_name": business["name"],
                    "color": strat.get("color", "#38bdf8"),
                    "tier": r.get("tier", "challenger"),
                    "strength": round(float(r.get("strength", 0.5)), 3),
                    "public_rep": round(float(r.get("public_rep", 50)), 1),
                    "gov_relation": round(float(r.get("gov_relation", 20)), 1),
                    "open_ratio": round(float(r.get("open_ratio", 0.3)), 2),
                    "capital": round(float(r.get("capital", 0)), 0),
                    "daily_revenue": round(float(r.get("daily_revenue", 0)), 2),
                    "daily_cost": round(float(r.get("daily_cost", 0)), 2),
                    "daily_profit": round(float(r.get("daily_profit", 0)), 2),
                    "api_daily_revenue": round(float(r.get("api_daily_revenue", 0)), 2),
                    "api_daily_users": round(float(r.get("api_daily_users", 0)), 1),
                    "revenue_breakdown": dict(r.get("revenue_breakdown") or {}),
                    "runway_days": r.get("runway_days"),
                    "financial_status": r.get("financial_status", "healthy"),
                    "employee_count": len(r.get("employees", [])),
                    "models_count": int(r.get("models_count", 0)),
                    "last_release_day": r.get("last_release_day", 0),
                    "personality": r.get("personality", ""),
                    "focus": list((r.get("research_levels") or {}).keys())[:5],
                    "top_research": self._top_research(r),
                    "flagship": self._flagship_public(models),
                    "top_models": self._top_models_public(models),
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
            "bankruptcies": list(state.get("competitor_ai", {}).get("bankruptcies", []))[-12:],
            "next_entrant_day": state.get("competitor_ai", {}).get("next_entrant_day"),
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
                    "parameter_scale_factor": round(calc.parameter_scaling_factor(float(m.get("params_b", 7))), 3),
                    "open_source": m.get("open_source"),
                    "api_enabled": m.get("api_enabled"),
                    "price_input": m.get("price_input"),
                    "price_output": m.get("price_output"),
                    "daily_users": m.get("daily_users", 0),
                    "daily_revenue": m.get("daily_revenue", 0),
                    "model_type": m.get("model_type"),
                    "distilled_from_player": bool(m.get("distilled_from_player")),
                    "teacher_model_name": m.get("teacher_model_name"),
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
        business = self._business_profile(seed.get("strategy"), strat)
        return {
            "id": seed["id"],
            "name": seed["name"],
            "country": seed.get("country", "usa"),
            "strategy": seed.get("strategy"),
            "business_model": business["id"],
            "business_model_name": business["name"],
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
            "daily_revenue": 0.0,
            "daily_cost": 0.0,
            "daily_profit": 0.0,
            "revenue_breakdown": {},
            "financial_status": "healthy",
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
        max_level = self._research_max_level(ctx, pick)
        # team power
        team = len(rival.get("employees", []))
        chance = 0.35 * pace * (0.7 + min(team, 20) * 0.03) * (0.8 + float(rival.get("strength", 0.5)))
        msgs = []
        if rng.random() < chance and cur < max_level:
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
            rival, strat, ctx, state=state, version=int(rival.get("models_count", 1)) + 1, day=day
        )
        training_cost = float(model.get("training_upfront_cost", 0))
        if float(rival.get("capital", 0)) < training_cost:
            rival["next_release_day"] = day + rng.randint(7, 16)
            rival["financial_status"] = "distressed"
            return None
        rival["capital"] -= training_cost
        model["released_day"] = day
        # replace previous main + keep history lightly
        models = state.setdefault("competitor_models", [])
        # demote old mains
        for m in models:
            if m.get("company_id") == rival["id"] and m.get("is_flagship"):
                m["is_flagship"] = False
        model["is_flagship"] = True
        models.append(model)
        # prune very old models per company (keep enough for the company Top 5)
        kept = []
        per: dict[str, int] = {}
        for m in reversed(models):
            cid = m.get("company_id", "")
            per[cid] = per.get(cid, 0) + 1
            if per[cid] <= 5:
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
        tick_cfg = ctx.configs().load("competitors").get("ai_tick", {})
        # Global spacing keeps successful raids rare enough to recover from.
        last_global = int(state.get("competitor_ai", {}).get("last_poach_day", -999))
        if day - last_global < int(tick_cfg.get("poach_global_spacing_days", 18)):
            return None

        chief_id = state.get("hr", {}).get("chief_scientist_id")
        emps = [
            employee
            for employee in state.get("employees", [])
            if employee.get("id") != chief_id
        ]
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
        interest = aggression * (0.08 + visibility) * float(tick_cfg.get("poach_interest_multiplier", 0.58))
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
        seniority_mult = {
            "junior": 0.75,
            "mid": 1.0,
            "senior": 1.25,
            "staff": 1.6,
            "principal": 2.0,
        }.get(target.get("seniority"), 1.0)
        breach_fee = round(
            float(target.get("salary", 15000))
            * float(tick_cfg.get("poach_breach_months", 4))
            * seniority_mult,
            0,
        )
        if rival["capital"] < cost + breach_fee:
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

        base_p *= float(tick_cfg.get("poach_success_multiplier", 0.55))
        success = rng.random() < calc.clamp(base_p, 0.008, float(tick_cfg.get("poach_success_cap", 0.18)))
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

        # The hiring rival pays the player's company a contractual breach fee.
        rival["capital"] = float(rival.get("capital", 0)) - breach_fee
        state["company"]["capital"] = float(state["company"].get("capital", 0)) + breach_fee

        # player morale shock
        for e in state.get("employees", []):
            e["morale"] = calc.clamp(float(e.get("morale", 70)) - rng.uniform(2, 6))

        msg = (
            f"⚠ {rival['name']} 挖走了 {target['name']}！"
            f"（{target.get('role_name', target.get('role', ''))} · 报价 {offer_mult:.1f}× 薪资；"
            f"收到违约金 ${breach_fee:,.0f}）"
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
            "breach_fee": breach_fee,
        }

    def _tick_economy(self, rival: dict, strat: dict, state: dict, ctx, days: int) -> None:
        rng = ctx.rng()
        business = self._business_profile(rival.get("strategy"), strat)
        models = [
            model
            for model in state.get("competitor_models", [])
            if model.get("company_id") == rival["id"] and model.get("api_enabled")
        ]
        best_hidden = max((float(model.get("hidden_score", 0)) for model in models), default=35.0)
        api_income = float(rival.get("api_daily_revenue", 0))
        rep = float(rival.get("public_rep", 50))
        gov = float(rival.get("gov_relation", 20))
        tier_mult = {"titan": 1.4, "challenger": 1.0, "startup": 0.7}.get(rival.get("tier"), 1.0)
        maturity = 0.7 + min(2.5, int(state.get("day", 0)) / 365.0)
        contract_income = (
            (best_hidden ** 1.18)
            * (20.0 + rep * 0.32)
            * float(business.get("contract", 0))
            * tier_mult
            * maturity
        )
        ecosystem_income = (
            (max(10.0, rep) ** 1.28)
            * 18.0
            * float(business.get("ecosystem", 0))
            * (0.65 + float(rival.get("open_ratio", 0.3)))
            * maturity
        )
        government_income = (
            (max(5.0, gov) ** 1.3)
            * 15.0
            * float(business.get("government", 0))
            * tier_mult
            * maturity
        )
        gross_daily = api_income + contract_income + ecosystem_income + government_income
        payroll_daily = sum(float(e.get("salary", 0)) for e in rival.get("employees", [])) / 30.0
        serving_daily = api_income * max(0.08, 1.0 - float(business.get("margin", 0.62)))
        compute_daily = (best_hidden ** 1.16) * 22.0 * tier_mult
        operating_daily = 2_000.0 * tier_mult + len(models) * 450.0
        total_cost_daily = payroll_daily + serving_daily + compute_daily + operating_daily
        net_daily = gross_daily - total_cost_daily
        rival["capital"] = float(rival["capital"]) + net_daily * days
        rival["daily_revenue"] = round(gross_daily, 2)
        rival["daily_cost"] = round(total_cost_daily, 2)
        rival["daily_profit"] = round(net_daily, 2)
        rival["revenue_breakdown"] = {
            "api": round(api_income, 2),
            "contracts": round(contract_income, 2),
            "ecosystem": round(ecosystem_income, 2),
            "government": round(government_income, 2),
        }
        burn = max(0.0, -net_daily)
        rival["runway_days"] = round(max(0.0, float(rival["capital"])) / burn, 0) if burn > 1 else None
        if float(rival["capital"]) < 0:
            rival["financial_status"] = "insolvent"
        elif burn > 0 and float(rival["capital"]) / burn < 90:
            rival["financial_status"] = "distressed"
        else:
            rival["financial_status"] = "healthy"
        # Rare shocks make otherwise viable strategies genuinely fallible.
        if rng.random() < 0.0015 * days:
            shock = min(float(rival["capital"]) * rng.uniform(0.08, 0.22), 6_000_000.0)
            rival["capital"] -= max(0.0, shock)
            rival.setdefault("recent_actions", []).append(
                {"day": state.get("day", 0), "msg": f"遭遇商业事故，损失 ${shock:,.0f}"}
            )
        # strength slow climb + noise
        rival["strength"] = calc.clamp(
            float(rival["strength"]) + rng.uniform(-0.002, 0.006) * days * float(strat.get("research_pace", 1)),
            0.25,
            0.99,
        )
        if rival.get("poach_cooldown", 0) > 0:
            rival["poach_cooldown"] = max(0, int(rival["poach_cooldown"]) - days)

    def _tick_pricing(self, rival: dict, strat: dict, state: dict, ctx) -> None:
        market_total = float(state.get("market", {}).get("total_api_market_daily_revenue", 0))
        share = float(rival.get("api_daily_revenue", 0)) / max(market_total, 1.0)
        distress = rival.get("financial_status") in {"distressed", "insolvent"}
        for model in state.get("competitor_models", []):
            if model.get("company_id") != rival["id"] or not model.get("api_enabled"):
                continue
            hidden = float(model.get("hidden_score", 40))
            target = (2.2 + hidden / 22.0) * float(strat.get("price_mult", 1.0))
            if model.get("open_source"):
                target *= 0.6
            if share < 0.025:
                target *= 0.86
            elif share > 0.16:
                target *= 1.06
            if distress:
                target *= 0.82
            old = float(model.get("price_output", target))
            price_out = calc.clamp(old * 0.72 + target * 0.28, 0.08, 100.0)
            model["price_output"] = round(price_out, 2)
            model["price_input"] = round(price_out * (0.28 if model.get("open_source") else 0.36), 2)

    def _try_distill_player_model(
        self,
        rivals: list[dict],
        strategies: dict[str, dict],
        state: dict,
        ctx,
    ) -> dict | None:
        day = int(state.get("day", 0))
        ai_state = state.setdefault("competitor_ai", {})
        if day < 35 or day - int(ai_state.get("last_player_distill_day", -999)) < 24:
            return None
        rng = ctx.rng()
        player_models = [
            model
            for model in state.get("models", [])
            if model.get("released") and (model.get("open_source") or model.get("api_enabled"))
        ]
        if not player_models or not rivals or rng.random() > 0.42:
            return None
        teacher = max(
            player_models,
            key=lambda model: float(model.get("hidden_score", 0))
            * (1.12 if model.get("open_source") else 1.0),
        )
        eligible = []
        for rival in rivals:
            if rival.get("financial_status") == "insolvent":
                continue
            same_type = [
                model
                for model in state.get("competitor_models", [])
                if model.get("company_id") == rival["id"]
                and model.get("model_type", "text") == teacher.get("model_type", "text")
            ]
            own_best = max((float(model.get("hidden_score", 0)) for model in same_type), default=0.0)
            if float(teacher.get("hidden_score", 0)) >= own_best * 0.82:
                eligible.append((rival, own_best))
        if not eligible:
            return None
        rival, own_best = rng.choice(eligible)
        strat = strategies.get(rival.get("strategy"), {})
        sampling_cost = (
            float(teacher.get("params_b", 7)) * 8_000
            if teacher.get("open_source")
            else float(teacher.get("hidden_score", 50)) * 14_000
        )
        version = int(rival.get("models_count", 1)) + 1
        model = self._build_model(rival, strat, ctx, state=state, version=version, day=day)
        teacher_hidden = float(teacher.get("hidden_score", 0))
        if teacher_hidden > own_best:
            transferred = own_best + max(0.8, (teacher_hidden - own_best) * rng.uniform(0.22, 0.36))
            model["hidden_score"] = round(min(teacher_hidden * 0.93, max(transferred, float(model["hidden_score"]))), 2)
        model["model_type"] = teacher.get("model_type", "text")
        model["params_b"] = max(1.0, min(float(teacher.get("params_b", 7)), float(model.get("params_b", 7))))
        presets = ctx.configs().load("model_types").get("param_presets", [])
        parameter_units = calc.parameter_compute_units(float(model["params_b"]), presets)
        type_cfg = ctx.configs().load("model_types").get("model_types", {}).get(model["model_type"], {})
        model["parameter_compute_units"] = round(parameter_units, 2)
        model["parameter_scale_factor"] = round(calc.parameter_scaling_factor(float(model["params_b"])), 3)
        model["training_upfront_cost"] = round(
            8000 + parameter_units * 250 * float(type_cfg.get("difficulty", 1.0)),
            2,
        )
        total_training_cost = sampling_cost + float(model["training_upfront_cost"])
        if float(rival.get("capital", 0)) < total_training_cost:
            return None
        rival["capital"] -= total_training_cost
        teacher_evals = teacher.get("eval_scores") or {}
        model_evals = model.get("eval_scores") or {}
        for key in set(teacher_evals) | set(model_evals):
            if key == "average":
                continue
            tv = teacher_evals.get(key)
            mv = model_evals.get(key)
            if isinstance(tv, (int, float)):
                base = float(mv) if isinstance(mv, (int, float)) else float(tv) * 0.7
                model_evals[key] = round(calc.clamp(float(tv) * 0.76 + base * 0.24 - rng.uniform(1.0, 4.5), 0, 100), 2)
        market_system = ctx.get_system("market")
        benchmarks = market_system.benchmarks_for_state(state, ctx) if market_system else {}
        model_evals["average"] = calc.weighted_eval_average(model_evals, benchmarks)
        model["eval_scores"] = model_evals
        model["name"] = f"{rival['name']} Echo-{version}"
        model["distilled_from_player"] = True
        model["teacher_model_id"] = teacher["id"]
        model["teacher_model_name"] = teacher.get("name")
        model["teacher_company"] = state.get("company", {}).get("name")
        model["released_day"] = day
        model["is_flagship"] = float(model.get("hidden_score", 0)) >= own_best
        if model["is_flagship"]:
            for existing in state.get("competitor_models", []):
                if existing.get("company_id") == rival["id"]:
                    existing["is_flagship"] = False
        state.setdefault("competitor_models", []).append(model)
        rival["models_count"] = version
        rival["last_release_day"] = day
        if model.get("open_source"):
            state.setdefault("open_models", []).append(self._to_open_entry(model, rival))
        self._prune_models(state)
        ai_state["last_player_distill_day"] = day
        access = "开源权重" if teacher.get("open_source") else "API 输出采样"
        msg = (
            f"⚠ {rival['name']} 通过{access}蒸馏了你的 {teacher.get('name')}，"
            f"发布 {model['name']}（H{model['hidden_score']}）"
        )
        rival.setdefault("recent_actions", []).append({"day": day, "msg": msg})
        state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "rival"})
        return {
            "type": "player_model_distilled",
            "msg": msg,
            "rival_id": rival["id"],
            "model_id": model["id"],
            "teacher_model_id": teacher["id"],
        }

    def _handle_bankruptcies(self, state: dict, ctx) -> list[dict]:
        events = []
        day = int(state.get("day", 0))
        ai_state = state.setdefault("competitor_ai", {})
        for rival in list(state.get("competitors", [])):
            if float(rival.get("capital", 0)) >= -250_000:
                continue
            state["competitors"].remove(rival)
            rival["bankrupt"] = True
            rival["bankrupt_day"] = day
            record = {
                "id": rival["id"],
                "name": rival["name"],
                "day": day,
                "business_model_name": rival.get("business_model_name"),
                "final_capital": round(float(rival.get("capital", 0)), 0),
            }
            ai_state.setdefault("bankruptcies", []).append(record)
            survivors = []
            for model in state.get("competitor_models", []):
                if model.get("company_id") != rival["id"]:
                    survivors.append(model)
                elif model.get("open_source"):
                    model["api_enabled"] = False
                    model["company_bankrupt"] = True
                    survivors.append(model)
            state["competitor_models"] = survivors
            msg = f"{rival['name']} 资金链断裂并破产退出竞争，开源权重仍留在社区"
            state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "rival"})
            self._log_action(state, day, msg, rival["id"])
            events.append({"type": "rival_bankrupt", "msg": msg, "rival_id": rival["id"]})
        return events

    def _maybe_new_entrant(self, state: dict, ctx) -> dict | None:
        day = int(state.get("day", 0))
        ai_state = state.setdefault("competitor_ai", {})
        if day < int(ai_state.get("next_entrant_day", day + 90)):
            return None
        rng = ctx.rng()
        ai_state["next_entrant_day"] = day + rng.randint(80, 145)
        if len(state.get("competitors", [])) >= 12:
            return None
        cfg = ctx.configs().load("competitors")
        strategies = cfg.get("strategies", {})
        strategy_id = rng.choice(list(strategies) or ["mixed_platform"])
        names = [
            "VectorForge", "星链智能", "Northstar Labs", "量潮科技", "HelixMind",
            "青穹模型", "Nova Cognition", "Atlas Kernel", "极昼智能", "Cedar AI",
        ]
        count = int(ai_state.get("entrant_count", 0)) + 1
        name = names[(count - 1) % len(names)] + (f" {count}" if count > len(names) else "")
        strength = min(0.9, 0.48 + day / 1800.0 + rng.uniform(-0.04, 0.08))
        seed = {
            "id": f"entrant_{count}_{str(uuid.uuid4())[:5]}",
            "name": name,
            "country": rng.choice(["usa", "china", "europe", "middle_east"]),
            "strategy": strategy_id,
            "tier": "challenger" if strength > 0.68 else "startup",
            "starting_strength": strength,
            "starting_capital": rng.randint(5_000_000, 28_000_000) * (1.0 + day / 1200.0),
            "starting_rep": rng.randint(38, 68),
            "starting_gov": rng.randint(10, 58),
            "starting_employees": rng.randint(4, 10),
            "starting_research_bonus": max(1, int(day / 240)),
            "personality": "新入场公司，会根据市场价格与新评测快速调整产品路线。",
        }
        strat = strategies.get(strategy_id, {})
        rival = self._init_rival(seed, strat, ctx)
        state.setdefault("competitors", []).append(rival)
        model = self._build_model(rival, strat, ctx, state=state, version=1, day=day)
        state.setdefault("competitor_models", []).append(model)
        if model.get("open_source"):
            state.setdefault("open_models", []).append(self._to_open_entry(model, rival))
        ai_state["entrant_count"] = count
        msg = f"新公司加入竞争：{name}（{rival['business_model_name']} · {rival['tier']}）"
        self._log_action(state, day, msg, rival["id"])
        state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "rival"})
        return {"type": "rival_entry", "msg": msg, "rival_id": rival["id"]}

    def _business_profile(self, strategy_id: str | None, strat: dict) -> dict:
        return dict(
            self.BUSINESS_MODELS.get(
                str(strategy_id),
                {"id": "mixed", "name": "混合商业化", "contract": 0.5, "ecosystem": 0.3, "government": 0.2, "margin": 0.62},
            )
        )

    def _research_max_level(self, ctx, research_id: str) -> int:
        cfg = ctx.configs().load("research")
        for category in ("model_research", "data_research", "compute_research"):
            if research_id in cfg.get(category, {}):
                return int(cfg[category][research_id].get("max_level", 20))
        return 36

    def _prune_models(self, state: dict) -> None:
        kept = []
        per: dict[str, int] = {}
        for model in reversed(state.get("competitor_models", [])):
            cid = model.get("company_id", "")
            per[cid] = per.get(cid, 0) + 1
            if per[cid] <= 5:
                kept.append(model)
        state["competitor_models"] = list(reversed(kept))

    # ------------------------------------------------------------------ model build

    def _build_model(
        self,
        rival: dict,
        strat: dict,
        ctx,
        state: dict | None = None,
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

        capacity_lv = int(model_levels.get("capacity", max(1, int(rival.get("strength", 0.5) * 5))))
        min_params_b = float(tcfg.get("min_params_b", 0.5))
        params_pref = [
            float(value)
            for value in (strat.get("param_pref") or [7, 13, 70])
            if min_params_b <= float(value)
        ]
        if not params_pref:
            params_pref = [max(min_params_b, 7.0)]
        # weight later params higher as strength grows
        params_b = float(rng.choice(params_pref))
        if float(rival.get("strength", 0.5)) > 0.8 and len(params_pref) > 1:
            params_b = float(rng.choice(params_pref[len(params_pref) // 2 :]))

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
        hidden = max(5.0, hidden)

        market_system = ctx.get_system("market")
        benchmarks = (
            market_system.benchmarks_for_state(state or {}, ctx)
            if market_system
            else ctx.configs().load("market").get("eval_benchmarks", {})
        )
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
        presets = ctx.configs().load("model_types").get("param_presets", [])
        parameter_units = calc.parameter_compute_units(params_b, presets)
        training_upfront = 8000 + parameter_units * 250 * float(tcfg.get("difficulty", 1.0))
        return {
            "id": mid if version > 1 else f"comp_{rival['id']}_main",
            "name": f"{rival['name']} {self._model_codename(model_type, params_b, version)}",
            "company_id": rival["id"],
            "company": rival["name"],
            "params_b": params_b,
            "parameter_scale_factor": round(calc.parameter_scaling_factor(params_b), 3),
            "parameter_compute_units": round(parameter_units, 2),
            "training_upfront_cost": round(training_upfront, 2),
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
            "api_enabled": m.get("api_enabled"),
            "price_input": m.get("price_input"),
            "price_output": m.get("price_output"),
            "daily_users": m.get("daily_users", 0),
            "daily_revenue": m.get("daily_revenue", 0),
            "params_b": m.get("params_b"),
            "parameter_scale_factor": round(calc.parameter_scaling_factor(float(m.get("params_b", 7))), 3),
            "model_type": m.get("model_type"),
            "distilled_from_player": bool(m.get("distilled_from_player")),
            "teacher_model_name": m.get("teacher_model_name"),
        }

    def _top_models_public(self, models: list[dict]) -> list[dict]:
        top = sorted(
            models,
            key=lambda model: (
                float((model.get("eval_scores") or {}).get("average", 0)),
                float(model.get("hidden_score", 0)),
            ),
            reverse=True,
        )[:5]
        return [
            {
                "id": model.get("id"),
                "name": model.get("name"),
                "hidden_score": model.get("hidden_score"),
                "eval_avg": (model.get("eval_scores") or {}).get("average"),
                "params_b": model.get("params_b"),
                "parameter_scale_factor": round(
                    calc.parameter_scaling_factor(float(model.get("params_b", 7))), 3
                ),
                "model_type": model.get("model_type"),
                "open_source": bool(model.get("open_source")),
                "api_enabled": bool(model.get("api_enabled")),
                "price_input": model.get("price_input"),
                "price_output": model.get("price_output"),
                "daily_users": model.get("daily_users", 0),
                "daily_revenue": model.get("daily_revenue", 0),
                "distilled_from_player": bool(model.get("distilled_from_player")),
                "teacher_model_name": model.get("teacher_model_name"),
            }
            for model in top
        ]

    def _log_action(self, state: dict, day: int, msg: str, rival_id: str) -> None:
        log = state.setdefault("competitor_ai", {}).setdefault("action_log", [])
        log.append({"day": day, "msg": msg, "rival_id": rival_id})
        limit = 40
        if len(log) > limit:
            del log[: len(log) - limit]
