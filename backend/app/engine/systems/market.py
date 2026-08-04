"""Market / API demand. Competitor AI lives in CompetitorsSystem."""

from __future__ import annotations

from typing import Any

from backend.app.engine.calculators import scores as calc


class MarketSystem:
    name = "market"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        # Competitors are owned by CompetitorsSystem; only init market stats here.
        # Keep empty list if competitors system not yet run (engine orders market after).
        state.setdefault("competitors", [])
        state["market"] = {
            "daily_revenue": 0.0,
            "monthly_revenue": 0.0,
            "segment_users": {},
            "revenue_log": [],
            "demand_mods": {
                "consumer": 1.0,
                "code": 1.0,
                "enthusiast": 1.0,
                "enterprise_gov": 1.0,
            },
        }

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        market_cfg = ctx.configs().load("market")
        segments = market_cfg.get("api_segments", {})
        country = state["company"]["country"]
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        bias = country_cfg.get("api_segment_bias", {})
        market_size = float(country_cfg.get("market_size_multiplier", 1.0))
        tendencies = state["company"].get("tendencies", {})
        mods = state.get("market", {}).get("demand_mods", {})

        company_mods = state["company"].get("modifiers", {})
        for k, seg in (
            ("consumer_demand", "consumer"),
            ("code_demand", "code"),
            ("enthusiast_demand", "enthusiast"),
            ("enterprise_demand", "enterprise_gov"),
        ):
            if k in company_mods:
                mods[seg] = float(mods.get(seg, 1.0)) + float(company_mods.pop(k, 0) or 0)

        own_models = [m for m in state.get("models", []) if m.get("released") and m.get("api_enabled")]
        comp_models = [m for m in state.get("competitor_models", []) if m.get("api_enabled")]
        all_evals = [float(m.get("eval_scores", {}).get("average", 0)) for m in own_models + comp_models]
        best_eval = max(all_evals) if all_evals else 50.0

        total_rev = 0.0
        segment_users: dict[str, float] = {}
        rivals_by_id = {c["id"]: c for c in state.get("competitors", [])}

        for sid, seg in segments.items():
            country_bias = float(bias.get(sid, 1.0)) * market_size
            demand_mod = float(mods.get(sid, 1.0))
            attractions = []
            for m in own_models:
                a = calc.segment_demand(
                    segment={**seg, "id": sid},
                    model=m,
                    company_tendencies=tendencies,
                    country_bias=country_bias,
                    best_eval_in_market=best_eval,
                    demand_mod=demand_mod,
                )
                attractions.append((m, a))

            comp_attr = 0.0
            for m in comp_models:
                rival = rivals_by_id.get(m.get("company_id"), {})
                comp_attr += calc.segment_demand(
                    segment={**seg, "id": sid},
                    model=m,
                    company_tendencies={
                        "gov_relation": float(rival.get("gov_relation", 30)),
                        "public_rep": float(rival.get("public_rep", 50)),
                    },
                    country_bias=country_bias * 0.85,
                    best_eval_in_market=best_eval,
                    demand_mod=1.0,
                )

            own_total = sum(a for _, a in attractions) + 1e-6
            share = own_total / (own_total + comp_attr + 1e-6)
            seg_users = 0.0
            for m, a in attractions:
                part = (a / own_total) * share
                users = a * part * 0.001
                rev = calc.monthly_api_revenue(a * share * (a / own_total), float(m.get("price_output", 6))) / 30.0
                total_rev += rev * days
                seg_users += users
                m["daily_users"] = round(users, 1)
                m["daily_revenue"] = round(rev, 2)
            segment_users[sid] = round(seg_users, 1)

        state["market"]["daily_revenue"] = round(total_rev / max(days, 1), 2)
        state["market"]["segment_users"] = segment_users
        state["company"]["capital"] = float(state["company"].get("capital", 0)) + total_rev

        day = state.get("day", 0)
        if day > 0 and day % 30 < days:
            month_rev = state["market"]["daily_revenue"] * 30
            state["market"]["monthly_revenue"] = round(month_rev, 2)
            state["market"].setdefault("revenue_log", []).append(
                {"day": day, "revenue": round(month_rev, 2)}
            )
            events.append({"type": "revenue", "msg": f"本月 API 收入约 ${month_rev:,.0f}", "amount": month_rev})

        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        market_cfg = ctx.configs().load("market")
        # Prefer rich rival projection from competitors system if present in same serialize pass —
        # engine serializes each system independently, so expose lightweight list here.
        comps = state.get("competitors", [])
        slim = []
        for c in comps:
            slim.append(
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "strategy": c.get("strategy") or c.get("strategy_legacy", "mixed"),
                    "country": c.get("country"),
                    "strength": c.get("strength"),
                    "open_ratio": c.get("open_ratio"),
                    "public_rep": c.get("public_rep"),
                    "tier": c.get("tier"),
                    "models_count": c.get("models_count"),
                    "employee_count": len(c.get("employees", [])),
                    "personality": c.get("personality", ""),
                }
            )
        return {
            "daily_revenue": state.get("market", {}).get("daily_revenue", 0),
            "monthly_revenue": state.get("market", {}).get("monthly_revenue", 0),
            "segment_users": state.get("market", {}).get("segment_users", {}),
            "segments": market_cfg.get("api_segments", {}),
            "competitors": slim,
            "revenue_log": state.get("market", {}).get("revenue_log", [])[-12:],
        }
