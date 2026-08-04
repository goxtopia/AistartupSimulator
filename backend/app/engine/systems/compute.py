"""Compute pool: purchase chips, cloud rentals, efficiency from research."""

from __future__ import annotations

from typing import Any


class ComputeSystem:
    name = "compute"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        # starter: a couple consumer GPUs
        state["compute"] = {
            "owned": {"nvidia_4090": 2},
            "cloud": {},  # chip_id -> qty rented
            "busy": 0.0,  # 0-1 utilization reserved by training
            "efficiency_bonus": 0.0,
        }

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        chips_cfg = ctx.configs().load("chips").get("chips", {})
        cloud = state.get("compute", {}).get("cloud", {})
        country = state["company"]["country"]
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        cost_mult = float(country_cfg.get("compute_cost_multiplier", 1.0))
        cost_mult *= 1.0 + float(state["company"].get("modifiers", {}).get("compute_cost_mult", 0))

        monthly = 0.0
        for chip_id, qty in cloud.items():
            cfg = chips_cfg.get(chip_id, {})
            monthly += float(cfg.get("monthly_cloud_cost", 0)) * int(qty)
        # charge proportionally per day
        daily = (monthly / 30.0) * cost_mult
        if daily > 0:
            state["company"]["capital"] -= daily * days

        # efficiency from research
        levels = state.get("research", {}).get("levels", {})
        eff = 0.0
        for rid, key in (
            ("kernel_opt", "compute_efficiency"),
            ("kernel_opt", "effective_flops_mult"),
            ("asic", "asic_efficiency"),
            ("quant_aware", "quant_efficiency"),
        ):
            lv = levels.get(rid, {})
            level = int(lv.get("level", 0)) if isinstance(lv, dict) else int(lv or 0)
            rcfg = None
            for cat in ("compute_research",):
                rcfg = ctx.configs().get("research", cat, rid, default=None)
                if rcfg:
                    break
            if rcfg and level > 0:
                eff += float(rcfg.get("effects", {}).get(key, 0)) * level
        mod = float(state["company"].get("modifiers", {}).get("compute_efficiency", 0))
        state["compute"]["efficiency_bonus"] = eff + mod
        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        chips_cfg = ctx.configs().load("chips").get("chips", {})
        country = state["company"]["country"]
        available = []
        for cid, c in chips_cfg.items():
            countries = c.get("countries", [])
            if country in countries:
                available.append({**c, "owned": int(state["compute"]["owned"].get(cid, 0)),
                                  "cloud_qty": int(state["compute"]["cloud"].get(cid, 0))})
        return {
            "owned": state["compute"].get("owned", {}),
            "cloud": state["compute"].get("cloud", {}),
            "available": available,
            "pool": self.pool_stats(state, ctx),
        }

    def pool_stats(self, state: dict[str, Any], ctx) -> dict[str, float]:
        chips_cfg = ctx.configs().load("chips").get("chips", {})
        total_flops = 0.0
        total_mem = 0.0
        units = 0
        for source in ("owned", "cloud"):
            for cid, qty in state.get("compute", {}).get(source, {}).items():
                cfg = chips_cfg.get(cid, {})
                q = int(qty)
                units += q
                total_flops += float(cfg.get("flops_tf", 0)) * float(cfg.get("efficiency", 1)) * q
                total_mem += float(cfg.get("memory_gb", 0)) * q
        eff = 1.0 + float(state.get("compute", {}).get("efficiency_bonus", 0))
        return {
            "units": units,
            "flops_tf": round(total_flops * eff, 1),
            "memory_gb": round(total_mem, 1),
            "efficiency": round(eff, 3),
            "busy": float(state.get("compute", {}).get("busy", 0)),
        }

    def purchase(self, state: dict[str, Any], ctx, chip_id: str, quantity: int, mode: str = "buy") -> tuple[bool, str]:
        chips_cfg = ctx.configs().load("chips").get("chips", {})
        cfg = chips_cfg.get(chip_id)
        if not cfg:
            return False, "未知芯片"
        country = state["company"]["country"]
        if country not in cfg.get("countries", []):
            return False, "该芯片在当前国家不可用"
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        cost_mult = float(country_cfg.get("compute_cost_multiplier", 1.0))
        cost_mult *= 1.0 + float(state["company"].get("modifiers", {}).get("compute_cost_mult", 0))

        # availability roll for large orders
        avail = float(cfg.get("availability", 1.0))
        if quantity > 8 and ctx.rng().random() > avail:
            quantity = max(1, int(quantity * avail))

        if mode == "cloud" or cfg.get("cloud_only"):
            # first month upfront
            cost = float(cfg.get("monthly_cloud_cost", 0)) * quantity * cost_mult
            if state["company"]["capital"] < cost:
                return False, f"资金不足（需要 ${cost:,.0f}）"
            state["company"]["capital"] -= cost
            cloud = state["compute"].setdefault("cloud", {})
            cloud[chip_id] = int(cloud.get(chip_id, 0)) + quantity
            return True, f"租用 {cfg['name']} x{quantity}（首月 ${cost:,.0f}）"

        if cfg.get("cloud_only"):
            return False, "该芯片仅支持云租用"
        cost = float(cfg.get("unit_cost", 0)) * quantity * cost_mult
        if state["company"]["capital"] < cost:
            return False, f"资金不足（需要 ${cost:,.0f}）"
        state["company"]["capital"] -= cost
        owned = state["compute"].setdefault("owned", {})
        owned[chip_id] = int(owned.get(chip_id, 0)) + quantity
        return True, f"采购 {cfg['name']} x{quantity}（${cost:,.0f}）"
