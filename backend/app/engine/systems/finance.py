"""Debt financing, credit capacity, and monthly repayment processing."""

from __future__ import annotations

import math
import uuid
from typing import Any

from backend.app.engine.calculators.scores import clamp


class FinanceSystem:
    name = "finance"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        state["finance"] = {
            "active_loans": [],
            "completed_loans": [],
            "active_revenue_financing": [],
            "completed_revenue_financing": [],
            "funding_tool_uses": {},
            "funding_history": [],
            "equity_sold": 0.0,
            "equity_raised": 0.0,
            "grant_funding": 0.0,
            "total_borrowed": 0.0,
            "total_interest_paid": 0.0,
            "missed_payments": 0,
            "payment_log": [],
        }

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        finance = self._ensure_state(state)
        day = int(state.get("day", 0))
        events: list[dict] = []
        if day <= 0:
            return events

        for loan in list(finance["active_loans"]):
            next_payment_day = int(
                loan.get("next_payment_day", int(loan.get("started_day", 0)) + 30)
            )
            if day < next_payment_day:
                continue
            balance = float(loan.get("balance", 0))
            if balance <= 0.01:
                self._complete(finance, loan, day)
                continue

            monthly_rate = float(loan.get("apr", 0)) / 12.0
            interest = balance * monthly_rate
            scheduled = min(float(loan.get("monthly_payment", 0)), balance + interest)
            capital_before = float(state["company"].get("capital", 0))
            late = capital_before < scheduled
            state["company"]["capital"] = capital_before - scheduled

            principal_paid = max(0.0, scheduled - interest)
            loan["balance"] = round(max(0.0, balance - principal_paid), 2)
            loan["payments_made"] = int(loan.get("payments_made", 0)) + 1
            loan["next_payment_day"] = next_payment_day + 30
            loan["interest_paid"] = round(float(loan.get("interest_paid", 0)) + interest, 2)
            finance["total_interest_paid"] = round(
                float(finance.get("total_interest_paid", 0)) + interest, 2
            )

            if late:
                loan["late_payments"] = int(loan.get("late_payments", 0)) + 1
                finance["missed_payments"] = int(finance.get("missed_payments", 0)) + 1
                tendencies = state["company"].setdefault("tendencies", {})
                tendencies["public_rep"] = clamp(float(tendencies.get("public_rep", 20)) - 1.5)

            entry = {
                "day": day,
                "loan_id": loan["id"],
                "name": loan["name"],
                "payment": round(scheduled, 2),
                "interest": round(interest, 2),
                "principal": round(principal_paid, 2),
                "balance": loan["balance"],
                "late": late,
            }
            finance["payment_log"].append(entry)
            events.append(
                {
                    "type": "loan_payment",
                    "msg": f"偿还{loan['name']} ${scheduled:,.0f}（本金 ${principal_paid:,.0f} · 利息 ${interest:,.0f}）",
                    "amount": -scheduled,
                }
            )
            if loan["balance"] <= 0.01 or loan["payments_made"] >= int(loan.get("term_months", 0)):
                loan["balance"] = 0.0
                self._complete(finance, loan, day)
                events.append({"type": "loan_complete", "msg": f"贷款已还清：{loan['name']}"})

        daily_revenue = float(state.get("market", {}).get("daily_revenue", 0))
        for agreement in list(finance["active_revenue_financing"]):
            remaining = max(0.0, float(agreement.get("remaining", 0)))
            payment = min(remaining, daily_revenue * float(agreement.get("revenue_share", 0)) * days)
            if payment <= 0:
                continue
            state["company"]["capital"] = float(state["company"].get("capital", 0)) - payment
            agreement["remaining"] = round(max(0.0, remaining - payment), 2)
            agreement["total_repaid"] = round(float(agreement.get("total_repaid", 0)) + payment, 2)
            if agreement["remaining"] <= 0.01:
                agreement["completed_day"] = day
                agreement["status"] = "completed"
                finance["active_revenue_financing"].remove(agreement)
                finance["completed_revenue_financing"].append(agreement)
                events.append(
                    {"type": "revenue_financing_complete", "msg": f"收入分成融资已结清：{agreement['name']}"}
                )

        finance["payment_log"] = finance["payment_log"][-60:]
        return events

    def use_funding_tool(
        self, state: dict[str, Any], ctx, tool_id: str
    ) -> tuple[bool, str, dict | None]:
        config = ctx.configs().load("finance").get("funding_tools", {}).get(tool_id)
        if not config:
            return False, "融资工具不存在", None
        finance = self._ensure_state(state)
        projection = self._funding_tool_projection(state, config)
        if projection["issues"]:
            return False, "暂不符合条件：" + "；".join(projection["issues"]), None

        amount = float(config.get("amount", 0))
        day = int(state.get("day", 0))
        tool_type = config.get("type")
        record: dict[str, Any] = {
            "id": "fund_" + str(uuid.uuid4())[:8],
            "tool_id": tool_id,
            "type": tool_type,
            "name": config.get("name", tool_id),
            "provider": config.get("provider", "融资机构"),
            "amount": amount,
            "started_day": day,
        }

        if tool_type == "equity":
            equity = float(config.get("equity_percent", 0))
            finance["equity_sold"] = round(float(finance.get("equity_sold", 0)) + equity, 4)
            finance["equity_raised"] = round(float(finance.get("equity_raised", 0)) + amount, 2)
            record["equity_percent"] = equity
            message = f"完成{record['name']}，获得 ${amount:,.0f}，出让 {equity * 100:.1f}% 股权"
        elif tool_type == "revenue_share":
            multiple = float(config.get("repayment_multiple", 1.0))
            target = amount * multiple
            record.update(
                {
                    "revenue_share": float(config.get("revenue_share", 0)),
                    "repayment_multiple": multiple,
                    "repayment_target": round(target, 2),
                    "remaining": round(target, 2),
                    "total_repaid": 0.0,
                    "status": "active",
                }
            )
            finance["active_revenue_financing"].append(record)
            message = (
                f"获得{record['name']} ${amount:,.0f}，将按收入的 "
                f"{record['revenue_share'] * 100:.0f}% 偿还至 ${target:,.0f}"
            )
        elif tool_type == "grant":
            finance["grant_funding"] = round(float(finance.get("grant_funding", 0)) + amount, 2)
            message = f"获得{record['name']} ${amount:,.0f}，无需偿还或稀释股权"
        else:
            return False, "暂不支持该融资工具", None

        state["company"]["capital"] = float(state["company"].get("capital", 0)) + amount
        uses = finance["funding_tool_uses"].setdefault(tool_id, [])
        uses.append(day)
        finance["funding_history"].append(record)
        finance["funding_history"] = finance["funding_history"][-40:]
        return True, message, record

    def borrow(
        self, state: dict[str, Any], ctx, product_id: str, amount: float
    ) -> tuple[bool, str, dict | None]:
        cfg = ctx.configs().load("finance")
        product = cfg.get("loan_products", {}).get(product_id)
        if not product:
            return False, "贷款产品不存在", None
        finance = self._ensure_state(state)
        projection = self._product_projection(state, product, cfg)
        if projection["issues"]:
            return False, "暂不符合授信条件：" + "；".join(projection["issues"]), None
        if any(loan.get("product_id") == product_id for loan in finance["active_loans"]):
            return False, "同一贷款产品只能同时持有一笔", None

        amount = round(float(amount), 2)
        minimum = float(product.get("min_amount", 0))
        maximum = float(projection["available_amount"])
        step = max(1.0, float(product.get("amount_step", 1)))
        if amount < minimum or amount > maximum + 0.01:
            return False, f"可贷款额度为 ${minimum:,.0f}–${maximum:,.0f}", None
        if abs(amount / step - round(amount / step)) > 1e-6:
            return False, f"贷款金额必须按 ${step:,.0f} 递增", None

        term_months = int(product.get("term_years", 1)) * 12
        apr = float(product.get("apr", 0))
        monthly_payment = self._monthly_payment(amount, apr, term_months)
        fee = amount * float(product.get("origination_fee_rate", 0))
        proceeds = amount - fee
        day = int(state.get("day", 0))
        loan = {
            "id": "loan_" + str(uuid.uuid4())[:8],
            "product_id": product_id,
            "name": product.get("name", product_id),
            "lender": product.get("lender", "贷款机构"),
            "principal": amount,
            "balance": amount,
            "apr": apr,
            "term_months": term_months,
            "monthly_payment": round(monthly_payment, 2),
            "origination_fee": round(fee, 2),
            "early_repay_fee_rate": float(product.get("early_repay_fee_rate", 0)),
            "started_day": day,
            "maturity_day": day + term_months * 30,
            "next_payment_day": day + 30,
            "payments_made": 0,
            "interest_paid": 0.0,
            "late_payments": 0,
        }
        finance["active_loans"].append(loan)
        finance["total_borrowed"] = round(float(finance.get("total_borrowed", 0)) + amount, 2)
        state["company"]["capital"] = float(state["company"].get("capital", 0)) + proceeds
        msg = (
            f"获得{loan['name']} ${amount:,.0f}，到账 ${proceeds:,.0f}；"
            f"月供 ${monthly_payment:,.0f}，期限 {term_months} 个月"
        )
        return True, msg, loan

    def repay_early(
        self, state: dict[str, Any], loan_id: str
    ) -> tuple[bool, str, dict | None]:
        finance = self._ensure_state(state)
        loan = next((item for item in finance["active_loans"] if item["id"] == loan_id), None)
        if not loan:
            return False, "贷款不存在或已经结清", None
        balance = float(loan.get("balance", 0))
        fee = balance * float(loan.get("early_repay_fee_rate", 0))
        payoff = balance + fee
        if float(state["company"].get("capital", 0)) < payoff:
            return False, f"资金不足，提前结清需要 ${payoff:,.0f}", None
        state["company"]["capital"] = float(state["company"].get("capital", 0)) - payoff
        loan["early_repay_fee"] = round(fee, 2)
        loan["balance"] = 0.0
        loan["paid_off_early"] = True
        self._complete(finance, loan, int(state.get("day", 0)))
        return True, f"已提前结清{loan['name']}，支付 ${payoff:,.0f}", loan

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        finance = self._ensure_state(state)
        cfg = ctx.configs().load("finance")
        products = []
        for product_id, product in cfg.get("loan_products", {}).items():
            projection = self._product_projection(state, product, cfg)
            products.append({**product, "id": product_id, **projection})
        funding_tools = []
        for tool_id, tool in cfg.get("funding_tools", {}).items():
            projection = self._funding_tool_projection(state, tool)
            funding_tools.append({**tool, "id": tool_id, **projection})
        active = [dict(loan) for loan in finance["active_loans"]]
        total_balance = sum(float(loan.get("balance", 0)) for loan in active)
        statement = self._financial_statement(state, ctx, active)
        monthly_debt_service = statement["monthly_debt_service"]
        return {
            "credit_score": self._credit_score(state, cfg),
            "products": products,
            "funding_tools": funding_tools,
            "active_loans": active,
            "active_revenue_financing": [dict(item) for item in finance["active_revenue_financing"]],
            "completed_revenue_financing": list(finance["completed_revenue_financing"])[-12:],
            "funding_history": list(finance["funding_history"])[-20:],
            "equity_sold": finance.get("equity_sold", 0),
            "founder_ownership": round(max(0.0, 1.0 - float(finance.get("equity_sold", 0))), 4),
            "equity_raised": finance.get("equity_raised", 0),
            "grant_funding": finance.get("grant_funding", 0),
            "completed_loans": list(finance["completed_loans"])[-12:],
            "payment_log": list(finance["payment_log"])[-24:],
            "total_balance": round(total_balance, 2),
            "monthly_debt_service": round(monthly_debt_service, 2),
            "total_borrowed": finance.get("total_borrowed", 0),
            "total_interest_paid": finance.get("total_interest_paid", 0),
            "missed_payments": finance.get("missed_payments", 0),
            "financial_statement": statement,
        }

    def _financial_statement(
        self, state: dict[str, Any], ctx, active_loans: list[dict] | None = None
    ) -> dict[str, Any]:
        """Current 30-day run-rate P&L and cash flow projection.

        Interest is an expense in net income; scheduled principal repayment is
        shown separately below net income because it only affects cash flow.
        """
        market = state.get("market", {})
        api_income = float(market.get("api_daily_revenue", 0)) * 30.0
        contract_income = float(market.get("contract_daily_revenue", 0)) * 30.0
        total_income = api_income + contract_income

        payroll = sum(float(employee.get("salary", 0)) for employee in state.get("employees", []))
        cloud_compute = self._cloud_compute_monthly_cost(state, ctx)
        research = self._research_monthly_cost(state, ctx)
        model_training, dataset_building = self._training_monthly_costs(state)

        loans = active_loans if active_loans is not None else self._ensure_state(state)["active_loans"]
        debt_interest = 0.0
        debt_principal = 0.0
        debt_service = 0.0
        for loan in loans:
            balance = max(0.0, float(loan.get("balance", 0)))
            interest = balance * max(0.0, float(loan.get("apr", 0))) / 12.0
            scheduled = min(float(loan.get("monthly_payment", 0)), balance + interest)
            debt_interest += interest
            debt_principal += max(0.0, scheduled - interest)
            debt_service += scheduled

        revenue_financing_payment = 0.0
        revenue_financing_cost = 0.0
        for agreement in self._ensure_state(state)["active_revenue_financing"]:
            projected = min(
                max(0.0, float(agreement.get("remaining", 0))),
                total_income * float(agreement.get("revenue_share", 0)),
            )
            multiple = max(1.0, float(agreement.get("repayment_multiple", 1)))
            revenue_financing_payment += projected
            revenue_financing_cost += projected * (multiple - 1.0) / multiple
        revenue_financing_principal = max(0.0, revenue_financing_payment - revenue_financing_cost)

        operating_expenses = (
            payroll
            + cloud_compute
            + research
            + model_training
            + dataset_building
            + debt_interest
            + revenue_financing_cost
        )
        net_income = total_income - operating_expenses
        financing_principal = debt_principal + revenue_financing_principal
        net_cash_flow = net_income - financing_principal
        capital = float(state.get("company", {}).get("capital", 0))
        runway_months = None
        if net_cash_flow < 0:
            runway_months = max(0.0, capital) / max(1.0, -net_cash_flow)

        return {
            "basis_days": 30,
            "income": {
                "api": round(api_income, 2),
                "contracts": round(contract_income, 2),
                "total": round(total_income, 2),
            },
            "expenses": {
                "payroll": round(payroll, 2),
                "cloud_compute": round(cloud_compute, 2),
                "research": round(research, 2),
                "model_training": round(model_training, 2),
                "dataset_building": round(dataset_building, 2),
                "debt_interest": round(debt_interest, 2),
                "revenue_financing_cost": round(revenue_financing_cost, 2),
                "total": round(operating_expenses, 2),
            },
            "monthly_net_income": round(net_income, 2),
            "monthly_debt_principal": round(debt_principal, 2),
            "monthly_revenue_financing_principal": round(revenue_financing_principal, 2),
            "monthly_financing_principal": round(financing_principal, 2),
            "monthly_revenue_financing_payment": round(revenue_financing_payment, 2),
            "monthly_debt_service": round(debt_service, 2),
            "monthly_net_cash_flow": round(net_cash_flow, 2),
            "capital": round(capital, 2),
            "runway_months": round(runway_months, 1) if runway_months is not None else None,
        }

    def _funding_tool_projection(self, state: dict[str, Any], tool: dict) -> dict[str, Any]:
        finance = self._ensure_state(state)
        requirements = tool.get("requirements", {})
        day = int(state.get("day", 0))
        tendencies = state.get("company", {}).get("tendencies", {})
        public_rep = float(tendencies.get("public_rep", 0))
        gov_relation = float(tendencies.get("gov_relation", 0))
        market = state.get("market", {})
        monthly_revenue = (
            float(market.get("api_daily_revenue", 0))
            + float(market.get("contract_daily_revenue", 0))
        ) * 30.0
        research_levels = sum(
            int(current.get("level", 0)) if isinstance(current, dict) else int(current or 0)
            for current in state.get("research", {}).get("levels", {}).values()
        )
        issues = []
        if day < int(requirements.get("min_day", 0)):
            issues.append(f"经营天数 {day}/{int(requirements['min_day'])}")
        if public_rep < float(requirements.get("min_public_rep", 0)):
            issues.append(f"公众声誉 {public_rep:.0f}/{float(requirements['min_public_rep']):.0f}")
        if gov_relation < float(requirements.get("min_gov_relation", 0)):
            issues.append(f"政府关系 {gov_relation:.0f}/{float(requirements['min_gov_relation']):.0f}")
        if monthly_revenue < float(requirements.get("min_monthly_revenue", 0)):
            issues.append(
                f"月收入 ${monthly_revenue:,.0f}/${float(requirements['min_monthly_revenue']):,.0f}"
            )
        if research_levels < int(requirements.get("min_research_levels", 0)):
            issues.append(f"累计研究等级 {research_levels}/{int(requirements['min_research_levels'])}")

        uses = list(finance.get("funding_tool_uses", {}).get(tool.get("id"), []))
        if len(uses) >= int(tool.get("max_uses", 1)):
            issues.append("使用次数已达上限")
        if tool.get("type") == "equity":
            after = float(finance.get("equity_sold", 0)) + float(tool.get("equity_percent", 0))
            if after > 0.49:
                issues.append("完成后创始团队持股将低于控制线")
        if tool.get("type") == "revenue_share" and finance["active_revenue_financing"]:
            issues.append("已有收入分成融资尚未结清")
        return {"eligible": not issues, "issues": issues, "uses": len(uses)}

    def _cloud_compute_monthly_cost(self, state: dict[str, Any], ctx) -> float:
        chips = ctx.configs().load("chips").get("chips", {})
        country = state.get("company", {}).get("country")
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        cost_mult = float(country_cfg.get("compute_cost_multiplier", 1.0))
        cost_mult *= 1.0 + float(
            state.get("company", {}).get("modifiers", {}).get("compute_cost_mult", 0)
        )
        return sum(
            float(chips.get(chip_id, {}).get("monthly_cloud_cost", 0)) * int(quantity)
            for chip_id, quantity in state.get("compute", {}).get("cloud", {}).items()
        ) * cost_mult

    def _research_monthly_cost(self, state: dict[str, Any], ctx) -> float:
        root = ctx.configs().load("research")
        categories = {
            "model": "model_research",
            "data": "data_research",
            "compute": "compute_research",
        }
        daily = 0.0
        for research_id, current in state.get("research", {}).get("levels", {}).items():
            if not isinstance(current, dict) or current.get("paused"):
                continue
            employee_ids = list(current.get("employee_ids") or [])
            if not employee_ids:
                continue
            category = current.get("category", "model")
            config = root.get(categories.get(category, ""), {}).get(research_id, {})
            if not config:
                continue
            level = int(current.get("level", 0))
            base = float(config.get("base_cost", 50000))
            growth = float(config.get("cost_growth", 1.4))
            per_day = base * (growth ** level) * 0.012
            daily += round(per_day * (0.6 + 0.15 * max(1, len(employee_ids))), 1)
        return daily * 30.0

    def _training_monthly_costs(self, state: dict[str, Any]) -> tuple[float, float]:
        training = state.get("training", {})
        training_daily = 0.0
        for job in training.get("active", []):
            if job.get("paused"):
                continue
            staff_count = max(1, len(job.get("employee_ids") or []))
            base = float(job.get("daily_cost_base", job.get("daily_cost", 0)))
            training_daily += base * (0.7 + 0.08 * staff_count)

        dataset_daily = 0.0
        for job in training.get("dataset_jobs", []):
            if job.get("paused"):
                continue
            staff_count = max(1, len(job.get("employee_ids") or []))
            base = float(job.get("daily_cost_base", 700))
            dataset_daily += base * (0.8 + 0.1 * staff_count)
        return training_daily * 30.0, dataset_daily * 30.0

    def _product_projection(self, state: dict, product: dict, cfg: dict) -> dict[str, Any]:
        req = product.get("requirements", {})
        day = int(state.get("day", 0))
        tendencies = state.get("company", {}).get("tendencies", {})
        rep = float(tendencies.get("public_rep", 0))
        gov = float(tendencies.get("gov_relation", 0))
        monthly_revenue = float(state.get("market", {}).get("monthly_revenue", 0))
        if monthly_revenue <= 0:
            monthly_revenue = float(state.get("market", {}).get("daily_revenue", 0)) * 30
        issues = []
        if day < int(req.get("min_day", 0)):
            issues.append(f"经营天数 {day}/{int(req['min_day'])}")
        if rep < float(req.get("min_public_rep", 0)):
            issues.append(f"公众声誉 {rep:.0f}/{float(req['min_public_rep']):.0f}")
        if gov < float(req.get("min_gov_relation", 0)):
            issues.append(f"政府关系 {gov:.0f}/{float(req['min_gov_relation']):.0f}")
        if monthly_revenue < float(req.get("min_monthly_revenue", 0)):
            issues.append(f"月收入 ${monthly_revenue:,.0f}/${float(req['min_monthly_revenue']):,.0f}")

        capacity = self._monthly_capacity(state, cfg)
        finance = self._ensure_state(state)
        current_service = sum(float(loan.get("monthly_payment", 0)) for loan in finance["active_loans"])
        if any(loan.get("product_id") == product.get("id") for loan in finance["active_loans"]):
            issues.append("已持有该产品贷款")
        available_service = max(0.0, capacity - current_service)
        term_months = int(product.get("term_years", 1)) * 12
        per_dollar = self._monthly_payment(1.0, float(product.get("apr", 0)), term_months)
        credit_max = available_service / max(per_dollar, 1e-9)
        step = max(1.0, float(product.get("amount_step", 1)))
        available_amount = min(float(product.get("max_amount", 0)), math.floor(credit_max / step) * step)
        if available_amount < float(product.get("min_amount", 0)):
            issues.append("现有债务或现金流不足以覆盖最低月供")
        return {
            "eligible": not issues,
            "issues": issues,
            "available_amount": round(max(0.0, available_amount), 2),
            "monthly_capacity": round(capacity, 2),
        }

    def _credit_score(self, state: dict, cfg: dict) -> float:
        credit = cfg.get("credit", {})
        tendencies = state.get("company", {}).get("tendencies", {})
        rep = float(tendencies.get("public_rep", 0))
        gov = float(tendencies.get("gov_relation", 0))
        monthly_revenue = float(state.get("market", {}).get("monthly_revenue", 0))
        if monthly_revenue <= 0:
            monthly_revenue = float(state.get("market", {}).get("daily_revenue", 0)) * 30
        capital = max(0.0, float(state.get("company", {}).get("capital", 0)))
        missed = int(self._ensure_state(state).get("missed_payments", 0))
        score = (
            float(credit.get("base_score", 35))
            + rep * float(credit.get("rep_weight", 0.25))
            + gov * float(credit.get("gov_weight", 0.15))
            + min(float(credit.get("revenue_cap", 20)), monthly_revenue / 100000 * 5)
            + min(float(credit.get("capital_cap", 10)), capital / 1000000 * 2)
            - missed * float(credit.get("missed_payment_penalty", 8))
        )
        return round(clamp(score, 0, 100), 1)

    def _monthly_capacity(self, state: dict, cfg: dict) -> float:
        credit = cfg.get("credit", {})
        tendencies = state.get("company", {}).get("tendencies", {})
        rep = float(tendencies.get("public_rep", 0))
        monthly_revenue = float(state.get("market", {}).get("monthly_revenue", 0))
        if monthly_revenue <= 0:
            monthly_revenue = float(state.get("market", {}).get("daily_revenue", 0)) * 30
        return max(
            float(credit.get("base_monthly_capacity", 25000)),
            monthly_revenue * float(credit.get("revenue_capacity_ratio", 0.45))
            + rep * float(credit.get("rep_capacity_per_point", 700)),
        )

    def _monthly_payment(self, principal: float, apr: float, months: int) -> float:
        if months <= 0:
            return principal
        monthly_rate = apr / 12.0
        if monthly_rate <= 0:
            return principal / months
        factor = (1 + monthly_rate) ** months
        return principal * monthly_rate * factor / (factor - 1)

    def _complete(self, finance: dict, loan: dict, day: int) -> None:
        if loan in finance["active_loans"]:
            finance["active_loans"].remove(loan)
        loan["completed_day"] = day
        loan["status"] = "completed"
        finance["completed_loans"].append(loan)

    def _ensure_state(self, state: dict[str, Any]) -> dict[str, Any]:
        finance = state.setdefault("finance", {})
        finance.setdefault("active_loans", [])
        finance.setdefault("completed_loans", [])
        finance.setdefault("active_revenue_financing", [])
        finance.setdefault("completed_revenue_financing", [])
        finance.setdefault("funding_tool_uses", {})
        finance.setdefault("funding_history", [])
        finance.setdefault("equity_sold", 0.0)
        finance.setdefault("equity_raised", 0.0)
        finance.setdefault("grant_funding", 0.0)
        finance.setdefault("total_borrowed", 0.0)
        finance.setdefault("total_interest_paid", 0.0)
        finance.setdefault("missed_payments", 0)
        finance.setdefault("payment_log", [])
        return finance
