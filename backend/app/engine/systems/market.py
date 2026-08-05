"""API market, public model ladder, and long-term procurement contracts."""

from __future__ import annotations

import uuid
from typing import Any

from backend.app.engine.calculators import scores as calc


class MarketSystem:
    name = "market"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        state.setdefault("competitors", [])
        state["market"] = {
            "daily_revenue": 0.0,
            "api_daily_revenue": 0.0,
            "contract_daily_revenue": 0.0,
            "monthly_revenue": 0.0,
            "segment_users": {},
            "competitor_segment_users": {},
            "api_market_multiplier": 1.0,
            "total_api_market_daily_revenue": 0.0,
            "player_api_market_share": 0.0,
            "revenue_log": [],
            "active_contracts": [],
            "completed_contracts": [],
            "dynamic_evals": [],
            "next_eval_day": ctx.rng().randint(70, 105),
            "eval_generation": 0,
            "dynamic_contract_offers": {},
            "next_contract_offer_day": ctx.rng().randint(45, 75),
            "contract_generation": 0,
            "demand_mods": {
                "consumer": 1.0,
                "code": 1.0,
                "enthusiast": 1.0,
                "enterprise_gov": 1.0,
            },
        }

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        market = self._ensure_state(state)
        events.extend(self._tick_dynamic_evals(state, ctx))
        events.extend(self._tick_dynamic_contracts(state, ctx))
        market_cfg = ctx.configs().load("market")
        segments = market_cfg.get("api_segments", {})
        country = state["company"]["country"]
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        bias = country_cfg.get("api_segment_bias", {})
        market_size = float(country_cfg.get("market_size_multiplier", 1.0))
        tendencies = state["company"].get("tendencies", {})
        mods = market.get("demand_mods", {})

        company_mods = state["company"].get("modifiers", {})
        for key, segment_id in (
            ("consumer_demand", "consumer"),
            ("code_demand", "code"),
            ("enthusiast_demand", "enthusiast"),
            ("enterprise_demand", "enterprise_gov"),
        ):
            if key in company_mods:
                mods[segment_id] = float(mods.get(segment_id, 1.0)) + float(company_mods.pop(key, 0) or 0)

        own_models = [m for m in state.get("models", []) if m.get("released") and m.get("api_enabled")]
        comp_models = [m for m in state.get("competitor_models", []) if m.get("released") and m.get("api_enabled")]
        benchmarks = self.benchmarks_for_state(state, ctx)
        for model in own_models + comp_models:
            score = calc.weighted_eval_average(model.get("eval_scores", {}), benchmarks)
            model.setdefault("eval_scores", {})["average"] = score
            model["market_eval_score"] = score
        all_evals = [float(m.get("market_eval_score", 0)) for m in own_models + comp_models]
        best_eval = max(all_evals) if all_evals else 50.0
        events.extend(self._run_auto_pricing(state, ctx))
        rivals_by_id = {c["id"]: c for c in state.get("competitors", [])}

        day = int(state.get("day", 0))
        economy_cfg = market_cfg.get("api_economy", {})
        growth_days = max(30.0, float(economy_cfg.get("growth_days", 180)))
        time_growth = (1.0 + day / growth_days) ** float(economy_cfg.get("growth_power", 2.0))
        frontier_adoption = 0.75 + max(0.0, best_eval - 35.0) / 55.0 * float(
            economy_cfg.get("frontier_adoption_scale", 1.6)
        )
        market_multiplier = float(
            calc.clamp(
                time_growth * frontier_adoption,
                float(economy_cfg.get("min_market_multiplier", 0.65)),
                float(economy_cfg.get("max_market_multiplier", 80.0)),
            )
        )
        revenue_scale = max(0.1, float(economy_cfg.get("base_revenue_multiplier", 2.5)))
        market["api_market_multiplier"] = round(market_multiplier, 2)

        model_totals: dict[str, dict[str, Any]] = {
            m["id"]: {"users": 0.0, "revenue": 0.0, "segments": {}} for m in own_models
        }
        competitor_totals: dict[str, dict[str, Any]] = {
            m["id"]: {"users": 0.0, "revenue": 0.0, "segments": {}} for m in comp_models
        }
        api_daily_revenue = 0.0
        competitor_api_daily_revenue = 0.0
        segment_users: dict[str, float] = {}
        competitor_segment_users: dict[str, float] = {}
        own_portfolio_divisor = max(1.0, len(own_models) ** 0.82)
        competitor_portfolio_sizes: dict[str, int] = {}
        for model in comp_models:
            cid = str(model.get("company_id", ""))
            competitor_portfolio_sizes[cid] = competitor_portfolio_sizes.get(cid, 0) + 1

        for sid, seg in segments.items():
            country_bias = float(bias.get(sid, 1.0)) * market_size
            demand_mod = max(0.1, float(mods.get(sid, 1.0)))
            own_attractions: list[tuple[dict[str, Any], float]] = []
            for model in own_models:
                attraction = calc.segment_demand(
                    segment={**seg, "id": sid},
                    model=model,
                    company_tendencies=tendencies,
                    country_bias=country_bias,
                    best_eval_in_market=best_eval,
                    demand_mod=demand_mod,
                ) / own_portfolio_divisor
                own_attractions.append((model, attraction))

            competitor_attractions: list[tuple[dict[str, Any], float]] = []
            for model in comp_models:
                rival = rivals_by_id.get(model.get("company_id"), {})
                attraction = calc.segment_demand(
                    segment={**seg, "id": sid},
                    model=model,
                    company_tendencies={
                        "gov_relation": float(rival.get("gov_relation", 30)),
                        "public_rep": float(rival.get("public_rep", 50)),
                    },
                    country_bias=country_bias,
                    best_eval_in_market=best_eval,
                    demand_mod=1.0,
                ) / max(1.0, competitor_portfolio_sizes.get(str(model.get("company_id", "")), 1) ** 0.82)
                competitor_attractions.append((model, attraction))

            own_total = sum(attraction for _, attraction in own_attractions)
            competitor_total = sum(attraction for _, attraction in competitor_attractions)
            total_attraction = own_total + competitor_total
            active_pool = (
                float(seg.get("base_population", 1000))
                * float(seg.get("active_rate", 0.01))
                * country_bias
                * market_multiplier
            )
            segment_owned_users = 0.0
            for model, attraction in own_attractions:
                users = active_pool * attraction / max(total_attraction, 1e-6)
                monthly_revenue = calc.monthly_api_revenue(
                    users,
                    float(model.get("price_output", 6)),
                    usage_tokens_m=float(seg.get("daily_tokens_m", 0.05)),
                    price_input=float(model.get("price_input", 2)),
                    output_token_share=float(seg.get("output_token_share", 0.7)),
                )
                daily_revenue = monthly_revenue / 30.0 * revenue_scale
                api_daily_revenue += daily_revenue
                segment_owned_users += users
                totals = model_totals[model["id"]]
                totals["users"] += users
                totals["revenue"] += daily_revenue
                totals["segments"][sid] = {
                    "users": round(users, 1),
                    "daily_revenue": round(daily_revenue, 2),
                }
            segment_competitor_users = 0.0
            for model, attraction in competitor_attractions:
                users = active_pool * attraction / max(total_attraction, 1e-6)
                monthly_revenue = calc.monthly_api_revenue(
                    users,
                    float(model.get("price_output", 6)),
                    usage_tokens_m=float(seg.get("daily_tokens_m", 0.05)),
                    price_input=float(model.get("price_input", 2)),
                    output_token_share=float(seg.get("output_token_share", 0.7)),
                )
                daily_revenue = monthly_revenue / 30.0 * revenue_scale
                competitor_api_daily_revenue += daily_revenue
                segment_competitor_users += users
                totals = competitor_totals[model["id"]]
                totals["users"] += users
                totals["revenue"] += daily_revenue
                totals["segments"][sid] = {
                    "users": round(users, 1),
                    "daily_revenue": round(daily_revenue, 2),
                }
            segment_users[sid] = round(segment_owned_users, 1)
            competitor_segment_users[sid] = round(segment_competitor_users, 1)

        for model in own_models:
            totals = model_totals[model["id"]]
            model["daily_users"] = round(totals["users"], 1)
            model["daily_revenue"] = round(totals["revenue"], 2)
            model["segment_performance"] = totals["segments"]

        rival_revenue: dict[str, float] = {}
        rival_users: dict[str, float] = {}
        for model in comp_models:
            totals = competitor_totals[model["id"]]
            model["daily_users"] = round(totals["users"], 1)
            model["daily_revenue"] = round(totals["revenue"], 2)
            model["segment_performance"] = totals["segments"]
            cid = model.get("company_id")
            rival_revenue[cid] = rival_revenue.get(cid, 0.0) + totals["revenue"]
            rival_users[cid] = rival_users.get(cid, 0.0) + totals["users"]
        for rival in state.get("competitors", []):
            rival["api_daily_revenue"] = round(rival_revenue.get(rival["id"], 0.0), 2)
            rival["api_daily_users"] = round(rival_users.get(rival["id"], 0.0), 1)

        contract_daily_revenue, contract_events = self._tick_contracts(state, days)
        events.extend(contract_events)
        total_daily_revenue = api_daily_revenue + contract_daily_revenue
        total_revenue = total_daily_revenue * days

        market["api_daily_revenue"] = round(api_daily_revenue, 2)
        market["contract_daily_revenue"] = round(contract_daily_revenue, 2)
        market["daily_revenue"] = round(total_daily_revenue, 2)
        market["segment_users"] = segment_users
        state["company"]["capital"] = float(state["company"].get("capital", 0)) + total_revenue

        total_api_market = api_daily_revenue + competitor_api_daily_revenue
        market["competitor_api_daily_revenue"] = round(competitor_api_daily_revenue, 2)
        market["total_api_market_daily_revenue"] = round(total_api_market, 2)
        market["player_api_market_share"] = round(
            api_daily_revenue / total_api_market if total_api_market > 0 else 0.0, 4
        )
        market["competitor_segment_users"] = competitor_segment_users
        if day > 0 and day % 30 < days:
            api_month = api_daily_revenue * 30
            contract_month = contract_daily_revenue * 30
            month_total = api_month + contract_month
            market["monthly_revenue"] = round(month_total, 2)
            market.setdefault("revenue_log", []).append(
                {
                    "day": day,
                    "revenue": round(month_total, 2),
                    "api_revenue": round(api_month, 2),
                    "contract_revenue": round(contract_month, 2),
                }
            )
            events.append(
                {
                    "type": "revenue",
                    "msg": f"本月收入约 ${month_total:,.0f}（API ${api_month:,.0f} · 合同 ${contract_month:,.0f}）",
                    "amount": month_total,
                }
            )
        return events

    def set_auto_pricing(
        self,
        state: dict[str, Any],
        ctx,
        model_id: str,
        enabled: bool,
    ) -> tuple[bool, str, dict | None]:
        model = next((item for item in state.get("models", []) if item.get("id") == model_id), None)
        if not model:
            return False, "模型不存在", None
        if not model.get("released") or not model.get("api_enabled"):
            return False, "只有已发布且启用 API 的模型可以自动定价", None
        if not enabled:
            model["auto_price_enabled"] = False
            model["auto_price_status"] = "off"
            model["auto_price_reason"] = "自动定价已关闭，保留最后一次价格"
            return True, f"已关闭 {model['name']} 的自动定价", model

        model["auto_price_enabled"] = True
        model["auto_price_status"] = "optimizing"
        event = self._update_auto_price(state, ctx, model, initial=True)
        message = event["msg"] if event else f"已开启 {model['name']} 的自动定价"
        return True, message, model

    def _run_auto_pricing(self, state: dict[str, Any], ctx) -> list[dict]:
        day = int(state.get("day", 0))
        events: list[dict] = []
        for model in state.get("models", []):
            if not model.get("auto_price_enabled"):
                continue
            if not model.get("released") or not model.get("api_enabled"):
                model["auto_price_enabled"] = False
                model["auto_price_status"] = "unavailable"
                model["auto_price_reason"] = "模型未启用 API，自动定价已停止"
                continue
            if day - int(model.get("auto_price_last_day", -999)) < 7:
                continue
            event = self._update_auto_price(state, ctx, model, initial=False)
            if event:
                events.append(event)
        return events

    def _update_auto_price(
        self, state: dict[str, Any], ctx, model: dict[str, Any], *, initial: bool
    ) -> dict[str, Any] | None:
        market_cfg = ctx.configs().load("market")
        pricing = market_cfg.get("pricing", {})
        lower, upper = self._auto_price_bounds(state, model, pricing)
        lower = max(0.01, lower)
        upper = max(lower, upper)
        candidates = {lower, upper, float(model.get("price_output", 6.0))}
        if upper > lower:
            for index in range(41):
                candidates.add(lower * ((upper / lower) ** (index / 40.0)))
        peers = [
            item
            for item in state.get("models", []) + state.get("competitor_models", [])
            if item.get("id") != model.get("id")
            and item.get("released")
            and item.get("api_enabled")
            and item.get("model_type", "text") == model.get("model_type", "text")
        ]
        candidates.update(
            float(item.get("price_output", 6.0))
            for item in peers
            if lower <= float(item.get("price_output", 6.0)) <= upper
        )

        min_price = float(pricing.get("min_price", 0.05))
        max_price = float(pricing.get("max_price", 100.0))
        best: tuple[float, float, float] | None = None
        for output_price in sorted(candidates):
            output_price = float(calc.clamp(output_price, lower, upper))
            # A conventional input/output structure avoids opaque cross-subsidies
            # while blended-price elasticity keeps both prices market-relevant.
            input_price = float(calc.clamp(output_price * 0.32, min_price, max_price))
            revenue = self._estimate_model_api_revenue(
                state, ctx, model, input_price, output_price
            )
            if best is None or revenue > best[0]:
                best = (revenue, input_price, output_price)
        if not best:
            return None

        target_revenue, target_input, target_output = best
        current_input = max(min_price, float(model.get("price_input", 2.0)))
        current_output = max(min_price, float(model.get("price_output", 6.0)))
        before_revenue = self._estimate_model_api_revenue(
            state, ctx, model, current_input, current_output
        )
        if initial:
            next_input, next_output = target_input, target_output
        else:
            step = 0.12
            next_input = current_input * float(
                calc.clamp(target_input / max(current_input, min_price), 1.0 - step, 1.0 + step)
            )
            next_output = current_output * float(
                calc.clamp(target_output / max(current_output, min_price), 1.0 - step, 1.0 + step)
            )
        next_input = float(calc.clamp(next_input, min_price, max_price))
        next_output = float(calc.clamp(next_output, lower, upper))
        projected = self._estimate_model_api_revenue(
            state, ctx, model, next_input, next_output
        )
        model.update(
            {
                "price_input": round(next_input, 3),
                "price_output": round(next_output, 3),
                "auto_price_enabled": True,
                "auto_price_status": "active",
                "auto_price_last_day": int(state.get("day", 0)),
                "auto_price_target_input": round(target_input, 3),
                "auto_price_target_output": round(target_output, 3),
                "auto_price_estimated_daily_revenue": round(projected, 2),
                "auto_price_target_daily_revenue": round(target_revenue, 2),
                "auto_price_previous_daily_revenue": round(before_revenue, 2),
                "auto_price_reason": (
                    f"基于 {len(peers)} 个同类型竞品与当前用户弹性，"
                    f"目标价 ${target_input:.2f}/${target_output:.2f}"
                ),
            }
        )
        msg = (
            f"自动定价更新 {model['name']}：输入 ${next_input:.2f}/M，"
            f"输出 ${next_output:.2f}/M，预计日收入 ${projected:,.0f}"
        )
        state.setdefault("log", []).append(
            {"day": state.get("day", 0), "msg": msg, "cat": "market"}
        )
        return {"type": "auto_price_update", "msg": msg, "model_id": model["id"]}

    def _auto_price_bounds(
        self, state: dict[str, Any], model: dict[str, Any], pricing: dict[str, Any]
    ) -> tuple[float, float]:
        lower = float(pricing.get("min_price", 0.05))
        upper = float(pricing.get("max_price", 100.0))
        if model.get("open_source"):
            peers = [
                item
                for item in state.get("models", []) + state.get("competitor_models", [])
                if item.get("id") != model.get("id")
                and item.get("released")
                and item.get("api_enabled")
            ]
            if peers:
                hidden = float(model.get("hidden_score", 50))
                closest = min(
                    peers,
                    key=lambda item: abs(float(item.get("hidden_score", 50)) - hidden),
                )
                reference = float(closest.get("price_output", 6.0))
                price_range = float(pricing.get("open_source_price_lock_range", 1.0))
                lower = max(lower, reference * (1.0 - price_range))
                upper = min(upper, reference * (1.0 + price_range))
        return lower, upper

    def _estimate_model_api_revenue(
        self,
        state: dict[str, Any],
        ctx,
        target: dict[str, Any],
        price_input: float,
        price_output: float,
    ) -> float:
        market_cfg = ctx.configs().load("market")
        segments = market_cfg.get("api_segments", {})
        country = state.get("company", {}).get("country", "usa")
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        bias = country_cfg.get("api_segment_bias", {})
        market_size = float(country_cfg.get("market_size_multiplier", 1.0))
        tendencies = state.get("company", {}).get("tendencies", {})
        market = self._ensure_state(state)
        mods = market.get("demand_mods", {})
        own_models = [
            item for item in state.get("models", []) if item.get("released") and item.get("api_enabled")
        ]
        competitor_models = [
            item
            for item in state.get("competitor_models", [])
            if item.get("released") and item.get("api_enabled")
        ]
        all_models = own_models + competitor_models
        benchmarks = self.benchmarks_for_state(state, ctx)
        best_eval = max(
            (calc.weighted_eval_average(item.get("eval_scores", {}), benchmarks) for item in all_models),
            default=50.0,
        )
        own_divisor = max(1.0, len(own_models) ** 0.82)
        rival_sizes: dict[str, int] = {}
        rivals = {item["id"]: item for item in state.get("competitors", [])}
        for item in competitor_models:
            company_id = str(item.get("company_id", ""))
            rival_sizes[company_id] = rival_sizes.get(company_id, 0) + 1
        candidate = {**target, "price_input": price_input, "price_output": price_output}
        multiplier = float(market.get("api_market_multiplier", 1.0))
        revenue_scale = max(
            0.1, float(market_cfg.get("api_economy", {}).get("base_revenue_multiplier", 2.5))
        )
        revenue = 0.0
        for segment_id, segment in segments.items():
            country_bias = float(bias.get(segment_id, 1.0)) * market_size
            demand_mod = max(0.1, float(mods.get(segment_id, 1.0)))
            target_attraction = calc.segment_demand(
                segment={**segment, "id": segment_id},
                model=candidate,
                company_tendencies=tendencies,
                country_bias=country_bias,
                best_eval_in_market=best_eval,
                demand_mod=demand_mod,
            ) / own_divisor
            total_attraction = target_attraction
            for item in own_models:
                if item.get("id") == target.get("id"):
                    continue
                total_attraction += calc.segment_demand(
                    segment={**segment, "id": segment_id},
                    model=item,
                    company_tendencies=tendencies,
                    country_bias=country_bias,
                    best_eval_in_market=best_eval,
                    demand_mod=demand_mod,
                ) / own_divisor
            for item in competitor_models:
                rival = rivals.get(item.get("company_id"), {})
                total_attraction += calc.segment_demand(
                    segment={**segment, "id": segment_id},
                    model=item,
                    company_tendencies={
                        "gov_relation": float(rival.get("gov_relation", 30)),
                        "public_rep": float(rival.get("public_rep", 50)),
                    },
                    country_bias=country_bias,
                    best_eval_in_market=best_eval,
                    demand_mod=1.0,
                ) / max(
                    1.0,
                    rival_sizes.get(str(item.get("company_id", "")), 1) ** 0.82,
                )
            active_pool = (
                float(segment.get("base_population", 1000))
                * float(segment.get("active_rate", 0.01))
                * country_bias
                * multiplier
            )
            users = active_pool * target_attraction / max(total_attraction, 1e-6)
            monthly = calc.monthly_api_revenue(
                users,
                price_output,
                usage_tokens_m=float(segment.get("daily_tokens_m", 0.05)),
                price_input=price_input,
                output_token_share=float(segment.get("output_token_share", 0.7)),
            )
            revenue += monthly / 30.0 * revenue_scale
        return max(0.0, revenue)

    def sign_contract(
        self,
        state: dict[str, Any],
        ctx,
        offer_id: str,
        model_id: str,
        duration_years: int,
    ) -> tuple[bool, str, dict | None]:
        offer = self._contract_offers(state, ctx).get(offer_id)
        if not offer:
            return False, "采购方不存在", None
        if offer.get("expires_day") and int(state.get("day", 0)) > int(offer["expires_day"]):
            return False, "该采购机会已经截止", None
        market = self._ensure_state(state)
        if any(c.get("offer_id") == offer_id for c in market.get("active_contracts", [])):
            return False, "该采购方已有生效中的合同", None

        model = next((m for m in state.get("models", []) if m.get("id") == model_id), None)
        if not model:
            return False, "只能使用已经训练完成的自有模型投标", None
        issues = self._contract_issues(model, offer.get("requirements", {}), state)
        if issues:
            return False, "模型未满足采购要求：" + "；".join(issues), None

        option = next(
            (o for o in offer.get("duration_options", []) if int(o.get("years", 0)) == int(duration_years)),
            None,
        )
        if not option:
            return False, "不支持该合同期限", None

        day = int(state.get("day", 0))
        duration_days = int(duration_years) * 365
        contract = {
            "id": str(uuid.uuid4()),
            "offer_id": offer_id,
            "buyer": offer.get("buyer", offer_id),
            "buyer_type": offer.get("buyer_type", "enterprise"),
            "model_id": model_id,
            "model_name": model.get("name", model_id),
            "duration_years": int(duration_years),
            "start_day": day,
            "end_day": day + duration_days,
            "monthly_revenue": float(option.get("monthly_revenue", 0)),
            "total_earned": 0.0,
        }
        market.setdefault("active_contracts", []).append(contract)
        msg = (
            f"与{contract['buyer']}签署{duration_years}年采购合同："
            f"{contract['model_name']}，每月 ${contract['monthly_revenue']:,.0f}"
        )
        return True, msg, contract

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        market_cfg = ctx.configs().load("market")
        market = self._ensure_state(state)
        comps = state.get("competitors", [])
        slim = [
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
            for c in comps
        ]

        offers = []
        active_offer_ids = {c.get("offer_id") for c in market.get("active_contracts", [])}
        for offer_id, offer in self._contract_offers(state, ctx).items():
            assessments = []
            for model in state.get("models", []):
                issues = self._contract_issues(model, offer.get("requirements", {}), state)
                assessments.append(
                    {
                        "model_id": model.get("id"),
                        "model_name": model.get("name"),
                        "eligible": not issues,
                        "issues": issues,
                    }
                )
            offers.append(
                {
                    **offer,
                    "id": offer_id,
                    "active": offer_id in active_offer_ids,
                    "expired": bool(
                        offer.get("expires_day")
                        and int(state.get("day", 0)) > int(offer["expires_day"])
                    ),
                    "model_assessments": assessments,
                }
            )

        leaderboard = self._model_leaderboard(state)
        open_ladder = [dict(row) for row in leaderboard if row.get("open_source")][:20]
        closed_ladder = [dict(row) for row in leaderboard if not row.get("open_source")][:20]
        for rows in (open_ladder, closed_ladder):
            for rank, row in enumerate(rows, 1):
                row["category_rank"] = rank

        return {
            "daily_revenue": market.get("daily_revenue", 0),
            "api_daily_revenue": market.get("api_daily_revenue", 0),
            "contract_daily_revenue": market.get("contract_daily_revenue", 0),
            "monthly_revenue": market.get("monthly_revenue", 0),
            "segment_users": market.get("segment_users", {}),
            "competitor_segment_users": market.get("competitor_segment_users", {}),
            "api_market_multiplier": market.get("api_market_multiplier", 1.0),
            "total_api_market_daily_revenue": market.get("total_api_market_daily_revenue", 0),
            "competitor_api_daily_revenue": market.get("competitor_api_daily_revenue", 0),
            "player_api_market_share": market.get("player_api_market_share", 0),
            "segments": market_cfg.get("api_segments", {}),
            "competitors": slim,
            "revenue_log": market.get("revenue_log", [])[-12:],
            "model_leaderboard": leaderboard[:20],
            "model_leaderboards": {"open": open_ladder, "closed": closed_ladder},
            "contract_offers": offers,
            "active_contracts": list(market.get("active_contracts", [])),
            "completed_contracts": list(market.get("completed_contracts", []))[-12:],
            "dynamic_evals": list(market.get("dynamic_evals", [])),
            "next_eval_day": market.get("next_eval_day"),
            "next_contract_offer_day": market.get("next_contract_offer_day"),
        }

    def _tick_contracts(self, state: dict[str, Any], days: int) -> tuple[float, list[dict]]:
        market = self._ensure_state(state)
        day = int(state.get("day", 0))
        events: list[dict] = []
        daily_total = 0.0
        for contract in list(market.get("active_contracts", [])):
            if day <= int(contract.get("end_day", -1)):
                daily = float(contract.get("monthly_revenue", 0)) / 30.0
                daily_total += daily
                contract["total_earned"] = round(float(contract.get("total_earned", 0)) + daily * days, 2)
            if day >= int(contract.get("end_day", -1)):
                market["active_contracts"].remove(contract)
                contract["status"] = "completed"
                market.setdefault("completed_contracts", []).append(contract)
                events.append(
                    {
                        "type": "contract_complete",
                        "msg": f"{contract.get('buyer')}采购合同到期，累计收入 ${float(contract.get('total_earned', 0)):,.0f}",
                    }
                )
        return daily_total, events

    def _contract_issues(self, model: dict, requirements: dict, state: dict) -> list[str]:
        issues: list[str] = []
        allowed_types = requirements.get("model_types") or []
        if allowed_types and model.get("model_type") not in allowed_types:
            issues.append("模型类型不符")
        evals = model.get("eval_scores", {})
        avg = float(evals.get("average", 0))
        if avg < float(requirements.get("min_eval", 0)):
            issues.append(f"EVAL {avg:.1f}/{float(requirements['min_eval']):.0f}")
        safety = float(evals.get("safetybench", 0))
        if safety < float(requirements.get("min_safety", 0)):
            issues.append(f"安全分 {safety:.1f}/{float(requirements['min_safety']):.0f}")
        hidden = float(model.get("hidden_score", 0))
        if hidden < float(requirements.get("min_hidden", 0)):
            issues.append(f"隐藏分 {hidden:.1f}/{float(requirements['min_hidden']):.0f}")
        gov = float(state.get("company", {}).get("tendencies", {}).get("gov_relation", 0))
        if gov < float(requirements.get("min_gov_relation", 0)):
            issues.append(f"政府关系 {gov:.0f}/{float(requirements['min_gov_relation']):.0f}")
        for benchmark_id, minimum in (requirements.get("min_benchmarks") or {}).items():
            score = float(evals.get(benchmark_id, 0))
            if score < float(minimum):
                issues.append(f"{benchmark_id.upper()} {score:.1f}/{float(minimum):.0f}")
        return issues

    def _model_leaderboard(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        company_name = state.get("company", {}).get("name", "玩家")
        rivals = {c.get("id"): c.get("name", c.get("id")) for c in state.get("competitors", [])}
        rows = []
        for model in state.get("models", []):
            if model.get("released"):
                rows.append((model, company_name, True))
        for model in state.get("competitor_models", []):
            if model.get("released"):
                owner = rivals.get(
                    model.get("company_id"),
                    model.get("company") or model.get("company_id", "竞品"),
                )
                rows.append((model, owner, False))

        result = []
        for model, owner, is_player in rows:
            eval_avg = float(model.get("eval_scores", {}).get("average", 0))
            hidden = float(model.get("hidden_score", 0))
            ladder_score = eval_avg * 0.7 + min(100.0, hidden / 2.0) * 0.3
            result.append(
                {
                    "id": model.get("id"),
                    "name": model.get("name"),
                    "owner": owner,
                    "is_player": is_player,
                    "model_type": model.get("model_type", "text"),
                    "params_b": model.get("params_b", 0),
                    "parameter_scale_factor": round(
                        calc.parameter_scaling_factor(float(model.get("params_b", 7))), 3
                    ),
                    "eval_avg": round(eval_avg, 1),
                    "hidden_score": round(hidden, 1),
                    "ladder_score": round(ladder_score, 1),
                    "open_source": bool(model.get("open_source")),
                    "api_enabled": bool(model.get("api_enabled")),
                    "price_input": model.get("price_input"),
                    "price_output": model.get("price_output"),
                    "released_day": model.get("released_day", 0),
                }
            )
        result.sort(key=lambda row: (row["ladder_score"], row["eval_avg"], row["hidden_score"]), reverse=True)
        for rank, row in enumerate(result, 1):
            row["rank"] = rank
        return result

    def benchmarks_for_state(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        """Static benchmark catalog plus every benchmark revealed this run."""
        benchmarks = dict(ctx.configs().load("market").get("eval_benchmarks", {}))
        for benchmark in state.get("market", {}).get("dynamic_evals", []):
            benchmarks[benchmark["id"]] = dict(benchmark)
        return benchmarks

    def _tick_dynamic_evals(self, state: dict[str, Any], ctx) -> list[dict]:
        market = self._ensure_state(state)
        day = int(state.get("day", 0))
        if day < int(market.get("next_eval_day", 90)):
            return []
        rng = ctx.rng()
        generation = int(market.get("eval_generation", 0)) + 1
        templates = [
            {
                "slug": "frontier_reasoning",
                "name": "FrontierReason-X",
                "description": "更长推理链、反事实规划与高难数学的综合压力测试。",
                "bias_from": ["cot", "rl", "performance"],
                "reference_evals": ["gsm8k", "mmlu"],
            },
            {
                "slug": "swe_arena_pro",
                "name": "SWE-Arena Pro",
                "description": "跨仓库修复、工具调用与真实软件工程任务。",
                "bias_from": ["code", "agentic", "performance"],
                "reference_evals": ["humaneval", "agentbench"],
            },
            {
                "slug": "longagent",
                "name": "LongAgent-X",
                "description": "长上下文检索、持续规划与多步执行评测。",
                "bias_from": ["long_context", "agentic", "cot"],
                "reference_evals": ["longbench", "agentbench"],
            },
            {
                "slug": "safe_deploy",
                "name": "SafeDeploy-X",
                "description": "对抗攻击、越狱抵抗与高风险部署安全评测。",
                "bias_from": ["harmlessness", "interpretability", "rl"],
                "reference_evals": ["safetybench", "mt_bench"],
            },
            {
                "slug": "world_knowledge_live",
                "name": "WorldKnowledge Live",
                "description": "动态知识、跨领域迁移和低资源事实核验评测。",
                "bias_from": ["frontier_science", "performance", "capacity"],
                "reference_evals": ["mmlu", "mt_bench"],
            },
        ]
        template = templates[(generation - 1) % len(templates)]
        difficulty = min(2.15, 1.12 + generation * 0.13 + day / 2400.0)
        benchmark = {
            "id": f"{template['slug']}_g{generation}",
            "name": f"{template['name']} {generation}",
            "description": template["description"],
            "weight": round(min(2.4, 1.15 + generation * 0.12), 2),
            "difficulty": round(difficulty, 2),
            "noise": round(max(0.035, 0.075 - generation * 0.003), 3),
            "bias_from": list(template["bias_from"]),
            "reference_evals": list(template["reference_evals"]),
            "created_day": day,
            "dynamic": True,
            "generation": generation,
        }
        market.setdefault("dynamic_evals", []).append(benchmark)
        market["eval_generation"] = generation
        market["next_eval_day"] = day + rng.randint(85, 135)

        all_benchmarks = self.benchmarks_for_state(state, ctx)
        for model in state.get("models", []) + state.get("competitor_models", []):
            one = calc.compute_eval_scores(
                float(model.get("hidden_score", 0)),
                research_levels={},
                data_levels={},
                benchmarks={benchmark["id"]: benchmark},
                model_type=model.get("model_type", "text"),
                rng=rng,
            )
            base_score = float(one.get(benchmark["id"], 0))
            old_evals = model.setdefault("eval_scores", {})
            references = [
                float(old_evals[key])
                for key in benchmark["reference_evals"]
                if isinstance(old_evals.get(key), (int, float))
            ]
            old_avg = float(old_evals.get("average", base_score))
            specialty = ((sum(references) / len(references)) - old_avg) * 0.35 if references else 0.0
            old_evals[benchmark["id"]] = round(calc.clamp(base_score + specialty, 0, 100), 2)
            old_evals["average"] = calc.weighted_eval_average(old_evals, all_benchmarks)

        msg = (
            f"新高难评测发布：{benchmark['name']}（难度 ×{difficulty:.2f}，"
            "已重新影响模型榜单与 API 竞争）"
        )
        state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "market"})
        return [{"type": "new_benchmark", "msg": msg, "benchmark_id": benchmark["id"]}]

    def _tick_dynamic_contracts(self, state: dict[str, Any], ctx) -> list[dict]:
        market = self._ensure_state(state)
        day = int(state.get("day", 0))
        dynamic = market.setdefault("dynamic_contract_offers", {})
        active_offer_ids = {item.get("offer_id") for item in market.get("active_contracts", [])}
        for offer_id, offer in list(dynamic.items()):
            if (
                offer_id not in active_offer_ids
                and offer.get("expires_day")
                and day > int(offer["expires_day"])
            ):
                del dynamic[offer_id]
        available_count = sum(1 for offer_id in dynamic if offer_id not in active_offer_ids)
        if day < int(market.get("next_contract_offer_day", 60)) or available_count >= 4:
            return []

        rng = ctx.rng()
        generation = int(market.get("contract_generation", 0)) + 1
        buyers = [
            ("曜石全球银行", "enterprise", "跨境金融智能体与审计分析平台"),
            ("泛星工业联合体", "enterprise", "工业控制、研发知识库与供应链决策模型"),
            ("国际科学计算中心", "enterprise", "高难科学推理与多模态研究基础设施"),
            ("国家关键系统署", "government", "关键政务系统、安全审查与应急决策模型"),
            ("深空任务联盟", "government", "长期自主规划、科学工具调用与可靠性验证"),
            ("万象内容平台", "enterprise", "超大规模内容理解、创作与实时审核服务"),
        ]
        buyer, buyer_type, description = buyers[(generation - 1) % len(buyers)]
        frontier_hidden = max(
            (float(model.get("hidden_score", 0)) for model in state.get("models", []) + state.get("competitor_models", [])),
            default=60.0,
        )
        min_hidden = round(
            min(185.0, max(90.0, frontier_hidden * rng.uniform(0.86, 0.96) + day / 48)),
            1,
        )
        min_eval = round(min(96.0, 68.0 + day / 32.0 + generation * 1.6), 1)
        min_safety = (
            round(min(92.0, max(62.0, 55.0 + day / 38.0)), 1)
            if buyer_type == "government"
            else 0.0
        )
        latest_eval = (market.get("dynamic_evals") or [])[-1] if market.get("dynamic_evals") else None
        min_benchmarks = {}
        if latest_eval:
            min_benchmarks[latest_eval["id"]] = round(min(82.0, max(35.0, min_eval - 13.0)), 1)
        monthly = round((150_000 + day * 780 + min_hidden * 1_650) / 5_000) * 5_000
        offer_id = f"dynamic_contract_{generation}_{str(uuid.uuid4())[:5]}"
        offer = {
            "id": offer_id,
            "buyer": f"{buyer} · 第{generation}期",
            "buyer_type": buyer_type,
            "description": description + "。这是限时高难采购，要求会随行业前沿提升。",
            "duration_options": [
                {"years": 2, "monthly_revenue": monthly},
                {"years": 5, "monthly_revenue": round(monthly * 0.84 / 5_000) * 5_000},
            ],
            "requirements": {
                "model_types": ["text", "multimodal", "anytoany"],
                "min_eval": min_eval,
                "min_hidden": min_hidden,
                **({"min_safety": min_safety, "min_gov_relation": 42} if min_safety else {}),
                **({"min_benchmarks": min_benchmarks} if min_benchmarks else {}),
            },
            "created_day": day,
            "expires_day": day + rng.randint(120, 180),
            "dynamic": True,
            "difficulty_tier": generation,
        }
        dynamic[offer_id] = offer
        market["contract_generation"] = generation
        market["next_contract_offer_day"] = day + rng.randint(65, 110)
        benchmark_req = f"，含 {latest_eval['name']} 专项门槛" if latest_eval else ""
        msg = f"新高难采购发布：{offer['buyer']}，月收入最高 ${monthly:,.0f}{benchmark_req}"
        state.setdefault("log", []).append({"day": day, "msg": msg, "cat": "contract"})
        return [{"type": "new_contract_offer", "msg": msg, "offer_id": offer_id}]

    def _contract_offers(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        offers = dict(ctx.configs().load("market").get("procurement_contracts", {}))
        offers.update(state.get("market", {}).get("dynamic_contract_offers", {}))
        return offers

    def _ensure_state(self, state: dict[str, Any]) -> dict[str, Any]:
        market = state.setdefault("market", {})
        market.setdefault("daily_revenue", 0.0)
        market.setdefault("api_daily_revenue", market.get("daily_revenue", 0.0))
        market.setdefault("contract_daily_revenue", 0.0)
        market.setdefault("monthly_revenue", 0.0)
        market.setdefault("segment_users", {})
        market.setdefault("competitor_segment_users", {})
        market.setdefault("api_market_multiplier", 1.0)
        market.setdefault("total_api_market_daily_revenue", 0.0)
        market.setdefault("competitor_api_daily_revenue", 0.0)
        market.setdefault("player_api_market_share", 0.0)
        market.setdefault("revenue_log", [])
        market.setdefault("active_contracts", [])
        market.setdefault("completed_contracts", [])
        market.setdefault("dynamic_evals", [])
        market.setdefault("next_eval_day", int(state.get("day", 0)) + 90)
        market.setdefault("eval_generation", len(market.get("dynamic_evals", [])))
        market.setdefault("dynamic_contract_offers", {})
        market.setdefault("next_contract_offer_day", int(state.get("day", 0)) + 60)
        market.setdefault("contract_generation", len(market.get("dynamic_contract_offers", {})))
        market.setdefault(
            "demand_mods",
            {"consumer": 1.0, "code": 1.0, "enthusiast": 1.0, "enterprise_gov": 1.0},
        )
        return market
