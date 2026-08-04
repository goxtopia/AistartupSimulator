"""Market / API demand and competitor drift."""

from __future__ import annotations

from typing import Any

from backend.app.engine.calculators import scores as calc


class MarketSystem:
    name = "market"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        market_cfg = ctx.configs().load("market")
        comps = []
        for seed in market_cfg.get("competitors_seed", []):
            comps.append({**seed, "models_count": 1, "last_release_day": 0})
        state["competitors"] = comps
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

        # Apply modifier hooks from events
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

        for sid, seg in segments.items():
            country_bias = float(bias.get(sid, 1.0)) * market_size
            demand_mod = float(mods.get(sid, 1.0))
            # distribute attraction across models (own only earns)
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

            # competitor gravity reduces share
            comp_attr = 0.0
            for m in comp_models:
                comp_attr += calc.segment_demand(
                    segment={**seg, "id": sid},
                    model=m,
                    company_tendencies={
                        "gov_relation": 30,
                        "public_rep": float(
                            next(
                                (c.get("public_rep", 50) for c in state.get("competitors", []) if c["id"] == m.get("company_id")),
                                50,
                            )
                        ),
                    },
                    country_bias=country_bias * 0.8,
                    best_eval_in_market=best_eval,
                    demand_mod=1.0,
                )

            own_total = sum(a for _, a in attractions) + 1e-6
            # share of market
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

        # monthly rollup log
        day = state.get("day", 0)
        if day > 0 and day % 30 < days:
            month_rev = state["market"]["daily_revenue"] * 30
            state["market"]["monthly_revenue"] = round(month_rev, 2)
            state["market"].setdefault("revenue_log", []).append(
                {"day": day, "revenue": round(month_rev, 2)}
            )
            events.append({"type": "revenue", "msg": f"本月 API 收入约 ${month_rev:,.0f}", "amount": month_rev})

        # competitor slow improvement
        if day > 0 and day % 14 < days:
            self._competitor_tick(state, ctx)

        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        market_cfg = ctx.configs().load("market")
        return {
            "daily_revenue": state.get("market", {}).get("daily_revenue", 0),
            "monthly_revenue": state.get("market", {}).get("monthly_revenue", 0),
            "segment_users": state.get("market", {}).get("segment_users", {}),
            "segments": market_cfg.get("api_segments", {}),
            "competitors": state.get("competitors", []),
            "revenue_log": state.get("market", {}).get("revenue_log", [])[-12:],
        }

    def _competitor_tick(self, state: dict, ctx) -> None:
        rng = ctx.rng()
        for c in state.get("competitors", []):
            c["strength"] = calc.clamp(float(c.get("strength", 0.5)) + rng.uniform(0.0, 0.015), 0.3, 0.98)
            # maybe release better model
            if rng.random() < 0.25:
                h = 40 + float(c["strength"]) * 65 + rng.uniform(-3, 8)
                mid = f"comp_{c['id']}_{state.get('day', 0)}"
                # replace main model
                models = state.setdefault("competitor_models", [])
                models = [m for m in models if m.get("company_id") != c["id"] or not str(m["id"]).endswith("_main")]
                models.append(
                    {
                        "id": f"comp_{c['id']}_main",
                        "name": f"{c['name']} v{1 + int(c.get('models_count', 1))}",
                        "company_id": c["id"],
                        "company": c["name"],
                        "params_b": rng.choice([13, 70, 100, 180, 400]),
                        "hidden_score": round(h, 1),
                        "model_type": "text",
                        "source": "closed_competitor" if c.get("strategy") != "open" else "open",
                        "api_enabled": c.get("strategy") != "open" or rng.random() < 0.5,
                        "open_source": c.get("strategy") == "open" or c.get("open_ratio", 0) > 0.5,
                        "price_input": round(rng.uniform(0.5, 4.0), 2),
                        "price_output": round(rng.uniform(1.5, 12.0), 2),
                        "released": True,
                        "eval_scores": {"average": round(h * 0.5 + rng.uniform(-4, 4), 1)},
                    }
                )
                state["competitor_models"] = models
                c["models_count"] = int(c.get("models_count", 1)) + 1
                c["last_release_day"] = state.get("day", 0)
                if models[-1].get("open_source"):
                    state.setdefault("open_models", []).append(
                        {
                            "id": models[-1]["id"] + "_wt",
                            "name": models[-1]["name"] + " (weights)",
                            "company": c["name"],
                            "hidden_score": models[-1]["hidden_score"],
                            "params_b": models[-1]["params_b"],
                            "model_type": "text",
                            "source": "open",
                        }
                    )
