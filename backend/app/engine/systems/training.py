"""Model training, datasets, release, distillation."""

from __future__ import annotations

import uuid
from typing import Any

from backend.app.engine.calculators import scores as calc


class TrainingSystem:
    name = "training"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        state["datasets"] = []
        state["models"] = []
        state["training"] = {"active": []}
        # seed a basic open dataset
        state["datasets"].append(
            {
                "id": "ds_open_base",
                "name": "开源混合语料 Base",
                "open_source_base": True,
                "quality": 0.7,
                "weights": {
                    "frontier_science": 0.25,
                    "code": 0.25,
                    "creative_writing": 0.2,
                    "industrial": 0.15,
                    "admin": 0.15,
                },
                "created_day": 0,
            }
        )
        self._seed_open_models(state, ctx)

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        active = state.get("training", {}).get("active", [])
        done = []
        pool = ctx.get_system("compute")
        for job in active:
            # consume compute reservation
            speed = self._train_speed(state, job, ctx)
            job["progress"] = float(job.get("progress", 0)) + speed * days
            daily = float(job.get("daily_cost", 0))
            state["company"]["capital"] -= daily * days
            if job["progress"] >= float(job.get("needed", 100)):
                done.append(job)

        for job in done:
            active.remove(job)
            model = self._finalize_model(state, job, ctx)
            state.setdefault("models", []).append(model)
            for eid in job.get("employee_ids", []):
                emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
                if emp:
                    emp["assigned_to"] = None
            state["compute"]["busy"] = max(0.0, float(state["compute"].get("busy", 0)) - float(job.get("compute_share", 0.3)))
            msg = f"训练完成：{model['name']}（隐藏分 {model['hidden_score']}）"
            events.append({"type": "train_done", "msg": msg, "model_id": model["id"]})
            state.setdefault("log", []).append({"day": state.get("day", 0), "msg": msg, "cat": "training"})

        # decay is_new flag
        for m in state.get("models", []):
            if m.get("is_new") and state.get("day", 0) - int(m.get("released_day") or m.get("created_day", 0)) > 21:
                m["is_new"] = False

        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        types = ctx.configs().load("model_types")
        return {
            "datasets": state.get("datasets", []),
            "models": [self._public_model(m) for m in state.get("models", [])],
            "active": state.get("training", {}).get("active", []),
            "model_types": types.get("model_types", {}),
            "param_presets": types.get("param_presets", []),
            "open_models": state.get("open_models", []),
            "competitor_models": state.get("competitor_models", []),
        }

    def create_dataset(self, state: dict[str, Any], ctx, name: str, use_open: bool, weights: dict[str, float]) -> tuple[bool, str, dict | None]:
        levels = state.get("research", {}).get("levels", {})
        data_cfg = ctx.configs().load("research").get("data_research", {})
        # quality from research levels matching weights
        q = 0.7 if use_open else 0.4
        wsum = sum(max(0.0, float(v)) for v in weights.values()) or 1.0
        norm = {k: max(0.0, float(v)) / wsum for k, v in weights.items()} if weights else {}
        if not norm:
            norm = {
                "frontier_science": 0.2,
                "code": 0.2,
                "creative_writing": 0.2,
                "industrial": 0.2,
                "admin": 0.2,
            }
        for did, w in norm.items():
            lv = levels.get(did, {})
            level = int(lv.get("level", 0)) if isinstance(lv, dict) else int(lv or 0)
            eff = float(data_cfg.get(did, {}).get("effects", {}).get("data_quality", 0.05))
            q += level * eff * w * 2.0
        q = calc.clamp(q, 0.2, 2.5)

        cost = 15000 + (0 if use_open else 25000) + sum(
            int((levels.get(k, {}) or {}).get("level", 0) if isinstance(levels.get(k), dict) else 0) * 3000
            for k in norm
        )
        if state["company"]["capital"] < cost:
            return False, f"资金不足（需要 ${cost:,.0f}）", None
        state["company"]["capital"] -= cost
        ds = {
            "id": "ds_" + str(uuid.uuid4())[:8],
            "name": name,
            "open_source_base": use_open,
            "quality": round(q, 3),
            "weights": norm,
            "created_day": state.get("day", 0),
            "cost": cost,
        }
        state.setdefault("datasets", []).append(ds)
        return True, f"数据集已创建：{name}（质量 {ds['quality']}）", ds

    def start_training(
        self,
        state: dict[str, Any],
        ctx,
        *,
        name: str,
        model_type: str,
        params_b: float,
        dataset_id: str,
        from_scratch: bool = True,
        base_model_id: str | None = None,
        expected_days: int = 30,
        employee_ids: list[str] | None = None,
        distill: dict | None = None,
    ) -> tuple[bool, str, dict | None]:
        types = ctx.configs().load("model_types").get("model_types", {})
        tcfg = types.get(model_type)
        if not tcfg:
            return False, "未知模型类型", None
        if params_b < float(tcfg.get("min_params_b", 0.5)):
            return False, f"参数量过小（最少 {tcfg['min_params_b']}B）", None

        ds = next((d for d in state.get("datasets", []) if d["id"] == dataset_id), None)
        if not ds:
            return False, "数据集不存在", None

        employee_ids = (employee_ids or [])[:20]
        emps = []
        for eid in employee_ids:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if not emp:
                return False, f"员工 {eid} 不存在", None
            if emp.get("assigned_to"):
                return False, f"{emp['name']} 已有任务", None
            emps.append(emp)

        # compute requirement
        compute_sys = ctx.get_system("compute")
        pool = compute_sys.pool_stats(state, ctx) if compute_sys else {"flops_tf": 100}
        # rough units from params
        need_flops = params_b * 8 * float(tcfg.get("compute_multiplier", 1.0))
        if distill:
            need_flops *= 0.45
        if not from_scratch:
            need_flops *= 0.55

        if pool["flops_tf"] < need_flops * 0.15:
            return False, f"算力不足（需要约 {need_flops:.0f} TF 有效算力，当前 {pool['flops_tf']}）", None

        base_hidden = 0.0
        base_label = None
        if not from_scratch and base_model_id:
            base = self._find_base_model(state, base_model_id)
            if not base:
                return False, "基座模型不存在", None
            base_hidden = float(base.get("hidden_score", 40))
            base_label = base.get("name")
            # cost for using closed competitor
            if base.get("source") == "closed_competitor":
                # cost ∝ architecture strength ~ hidden
                fee = base_hidden * 800
                if state["company"]["capital"] < fee:
                    return False, f"闭源基座授权费不足（${fee:,.0f}）", None
                state["company"]["capital"] -= fee
            elif base.get("source") == "open":
                fee = float(base.get("params_b", params_b)) * 50
                state["company"]["capital"] -= fee

        if distill:
            teacher = self._find_base_model(state, distill["teacher_model_id"])
            if not teacher:
                return False, "教师模型不存在", None
            src = distill.get("teacher_source", "own")
            if src == "closed_competitor":
                fee = float(teacher.get("hidden_score", 50)) * 1000
            elif src == "open":
                fee = float(teacher.get("params_b", 7)) * 80
            else:
                fee = float(teacher.get("params_b", 7)) * 40
            if state["company"]["capital"] < fee:
                return False, f"蒸馏成本不足（${fee:,.0f}）", None
            state["company"]["capital"] -= fee
            base_hidden = float(teacher.get("hidden_score", 50))
            base_label = teacher.get("name")

        days = max(3, int(expected_days * float(tcfg.get("time_multiplier", 1.0))))
        upfront = 20000 + params_b * 800 * float(tcfg.get("difficulty", 1.0))
        if state["company"]["capital"] < upfront:
            return False, f"启动资金不足（需要 ${upfront:,.0f}）", None
        state["company"]["capital"] -= upfront

        share = min(0.85, need_flops / max(pool["flops_tf"], 1))
        state["compute"]["busy"] = min(1.0, float(state["compute"].get("busy", 0)) + share)

        job = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "model_type": model_type,
            "params_b": params_b,
            "dataset_id": dataset_id,
            "from_scratch": from_scratch and not distill,
            "base_model_id": base_model_id,
            "base_hidden": base_hidden,
            "base_label": base_label,
            "distill": distill,
            "expected_days": days,
            "progress": 0.0,
            "needed": float(days) * 10,
            "employee_ids": [e["id"] for e in emps],
            "daily_cost": upfront * 0.03 + pool["flops_tf"] * 0.5,
            "compute_share": share,
            "started_day": state.get("day", 0),
        }
        for e in emps:
            e["assigned_to"] = f"train:{job['id']}"
        state.setdefault("training", {}).setdefault("active", []).append(job)
        return True, f"开始训练 {name}", job

    def release(
        self,
        state: dict[str, Any],
        ctx,
        model_id: str,
        *,
        open_source: bool = False,
        preview: bool = False,
        api_enabled: bool = True,
        price_input: float | None = None,
        price_output: float | None = None,
    ) -> tuple[bool, str, dict | None]:
        model = next((m for m in state.get("models", []) if m["id"] == model_id), None)
        if not model:
            return False, "模型不存在", None
        if model.get("released") and not preview:
            return False, "模型已发布"
        market = ctx.configs().load("market")
        pricing = market.get("pricing", {})

        pin = price_input if price_input is not None else float(pricing.get("default_input_per_m", 2.0))
        pout = price_output if price_output is not None else float(pricing.get("default_output_per_m", 6.0))

        if open_source and api_enabled:
            # lock price near closest API model hidden score
            peers = [m for m in state.get("models", []) if m.get("api_enabled") and m.get("released") and m["id"] != model_id]
            peers += [m for m in state.get("competitor_models", []) if m.get("api_enabled")]
            if peers:
                hidden = float(model.get("hidden_score", 50))
                closest = min(peers, key=lambda m: abs(float(m.get("hidden_score", 50)) - hidden))
                ref = float(closest.get("price_output", pout))
                rng = float(pricing.get("open_source_price_lock_range", 1.0))
                lo, hi = ref * (1 - rng), ref * (1 + rng)
                lo = max(float(pricing.get("min_price", 0.05)), lo)
                hi = min(float(pricing.get("max_price", 100)), hi)
                pout = float(calc.clamp(pout, lo, hi))
                pin = float(calc.clamp(pin, lo * 0.3, hi * 0.5))

        model["released"] = True
        model["open_source"] = open_source
        model["preview"] = preview
        model["preview_only"] = preview and not model.get("full_release")
        if not preview:
            model["full_release"] = True
            model["preview_only"] = False
        model["api_enabled"] = api_enabled
        model["price_input"] = round(pin, 3)
        model["price_output"] = round(pout, 3)
        model["released_day"] = state.get("day", 0)
        model["is_new"] = True

        # reputation
        rep_cfg = market.get("reputation", {})
        peers = [
            (float(c.get("strength", 0.5)) * 100, 5.0, float(c.get("public_rep", 50)))
            for c in state.get("competitors", [])
        ]
        t = state["company"].setdefault("tendencies", {})
        t["public_rep"] = calc.reputation_after_release(
            current_rep=float(t.get("public_rep", 20)),
            hidden=float(model["hidden_score"]),
            api_price=pout,
            open_source=open_source,
            peer_reps=peers,
            cfg=rep_cfg,
        )
        # openness stored nudge
        if open_source:
            t["openness"] = calc.clamp(float(t.get("openness", 30)) + 4)
            # also push to open_models market
            state.setdefault("open_models", []).append(
                {
                    "id": model["id"],
                    "name": model["name"],
                    "company": state["company"]["name"],
                    "hidden_score": model["hidden_score"],
                    "params_b": model["params_b"],
                    "model_type": model["model_type"],
                    "source": "open",
                }
            )

        harm_lv = state.get("research", {}).get("levels", {}).get("harmlessness", {})
        hl = int(harm_lv.get("level", 0)) if isinstance(harm_lv, dict) else 0
        if hl > 0:
            t["public_rep"] = calc.clamp(float(t["public_rep"]) + hl * 0.3)

        label = "Preview" if preview else ("开源" if open_source else "闭源")
        msg = f"发布模型 {model['name']}（{label}）"
        state.setdefault("log", []).append({"day": state.get("day", 0), "msg": msg, "cat": "release"})
        return True, msg, model

    def set_price(self, state: dict[str, Any], ctx, model_id: str, pin: float, pout: float) -> tuple[bool, str]:
        model = next((m for m in state.get("models", []) if m["id"] == model_id), None)
        if not model:
            return False, "模型不存在"
        if not model.get("released"):
            return False, "模型未发布"
        pricing = ctx.configs().load("market").get("pricing", {})
        if model.get("open_source") and model.get("api_enabled"):
            peers = [m for m in state.get("models", []) if m.get("api_enabled") and m.get("released") and m["id"] != model_id]
            peers += [m for m in state.get("competitor_models", []) if m.get("api_enabled")]
            if peers:
                hidden = float(model.get("hidden_score", 50))
                closest = min(peers, key=lambda m: abs(float(m.get("hidden_score", 50)) - hidden))
                ref = float(closest.get("price_output", pout))
                rng = float(pricing.get("open_source_price_lock_range", 1.0))
                lo, hi = ref * (1 - rng), ref * (1 + rng)
                pout = float(calc.clamp(pout, lo, hi))
                pin = float(calc.clamp(pin, lo * 0.3, hi * 0.5))
        model["price_input"] = round(pin, 3)
        model["price_output"] = round(pout, 3)
        return True, "价格已更新"

    # ---- internals ----

    def _finalize_model(self, state: dict, job: dict, ctx) -> dict:
        research_cfg = ctx.configs().load("research").get("model_research", {})
        levels_raw = state.get("research", {}).get("levels", {})
        levels = {
            k: int(v.get("level", 0)) if isinstance(v, dict) else int(v or 0)
            for k, v in levels_raw.items()
        }
        data_levels = {
            k: levels.get(k, 0)
            for k in ctx.configs().load("research").get("data_research", {})
        }
        ds = next((d for d in state.get("datasets", []) if d["id"] == job["dataset_id"]), {})
        tcfg = ctx.configs().load("model_types").get("model_types", {}).get(job["model_type"], {})

        # training days factor: if finished faster/slower vs expected
        elapsed = max(1, state.get("day", 0) - int(job.get("started_day", 0)))
        expected = max(1, int(job.get("expected_days", 30)))
        days_factor = calc.clamp(0.7 + 0.3 * (elapsed / expected), 0.5, 1.3)

        # team quality
        emps = [e for e in state.get("employees", []) if e["id"] in job.get("employee_ids", [])]
        team_q = 1.0
        if emps:
            team_q = 0.85 + sum(float(e.get("skills", {}).get("ml_theory", 30)) for e in emps) / len(emps) / 200.0

        hidden = calc.compute_hidden_score(
            capacity_level=levels.get("capacity", 0),
            research_levels=levels,
            research_cfg=research_cfg,
            model_type_mult=float(tcfg.get("base_hidden_mult", 1.0)),
            params_b=float(job["params_b"]),
            data_quality=float(ds.get("quality", 0.7)) * team_q,
            training_days_factor=days_factor,
            from_scratch=bool(job.get("from_scratch", True)),
            base_model_hidden=float(job.get("base_hidden", 0)),
        )
        if job.get("distill"):
            # distillation pulls toward teacher
            teacher_h = float(job.get("base_hidden", hidden))
            hidden = round(teacher_h * 0.65 + hidden * 0.4, 2)
            hidden = calc.clamp(hidden, 1, 200)

        benchmarks = ctx.configs().load("market").get("eval_benchmarks", {})
        evals = calc.compute_eval_scores(
            hidden,
            research_levels=levels,
            data_levels=data_levels,
            benchmarks=benchmarks,
            model_type=job["model_type"],
            rng=ctx.rng(),
        )

        return {
            "id": "mdl_" + str(uuid.uuid4())[:8],
            "name": job["name"],
            "model_type": job["model_type"],
            "params_b": job["params_b"],
            "dataset_id": job["dataset_id"],
            "hidden_score": hidden,
            "eval_scores": evals,
            "from_scratch": job.get("from_scratch", True),
            "base_label": job.get("base_label"),
            "distilled": bool(job.get("distill")),
            "released": False,
            "open_source": False,
            "preview": False,
            "api_enabled": False,
            "price_input": 2.0,
            "price_output": 6.0,
            "created_day": state.get("day", 0),
            "segment_affinity": tcfg.get("segment_affinity", {}),
            "source": "own",
        }

    def _public_model(self, m: dict) -> dict:
        # hide nothing critical for own models; hidden_score visible to player
        return dict(m)

    def _find_base_model(self, state: dict, mid: str) -> dict | None:
        for m in state.get("models", []):
            if m["id"] == mid:
                return {**m, "source": "own"}
        for m in state.get("open_models", []):
            if m["id"] == mid:
                return {**m, "source": "open"}
        for m in state.get("competitor_models", []):
            if m["id"] == mid:
                return m
        return None

    def _train_speed(self, state: dict, job: dict, ctx) -> float:
        """Progress units/day. Target: finish near expected_days with adequate compute."""
        compute_sys = ctx.get_system("compute")
        pool = compute_sys.pool_stats(state, ctx) if compute_sys else {"flops_tf": 100, "efficiency": 1}
        needed = float(job.get("needed", 100))
        expected = max(1.0, float(job.get("expected_days", 30)))
        # Baseline pace hits `needed` in `expected` days at mult=1.0
        base = needed / expected

        # Compute adequacy vs param demand
        params_b = float(job.get("params_b", 7))
        tcfg = ctx.configs().load("model_types").get("model_types", {}).get(job.get("model_type", "text"), {})
        need_flops = params_b * 8 * float(tcfg.get("compute_multiplier", 1.0))
        if job.get("distill"):
            need_flops *= 0.45
        if not job.get("from_scratch", True):
            need_flops *= 0.55
        ratio = float(pool.get("flops_tf", 100)) / max(need_flops, 1.0)
        compute_mult = min(1.8, 0.45 + 0.55 * min(ratio, 2.0))

        emps = [e for e in state.get("employees", []) if e["id"] in job.get("employee_ids", [])]
        if emps:
            skill = sum(
                float(e.get("skills", {}).get("ml_theory", 20))
                + float(e.get("skills", {}).get("systems", 20))
                for e in emps
            ) / len(emps)
            team_mult = 0.75 + skill / 120.0 + min(0.35, len(emps) * 0.04)
        else:
            team_mult = 0.55

        busy = float(state.get("compute", {}).get("busy", 0))
        busy_mult = max(0.4, 1.0 - busy * 0.25)
        return max(0.5, base * compute_mult * team_mult * busy_mult)

    def _seed_open_models(self, state: dict, ctx) -> None:
        """Seed baseline open-weight models. Rival models come from CompetitorsSystem."""
        baseline = [
            {"id": "open_herd_7b", "name": "OpenHerd-7B", "params_b": 7, "hidden_score": 48, "model_type": "text"},
            {"id": "open_herd_70b", "name": "OpenHerd-70B", "params_b": 70, "hidden_score": 72, "model_type": "text"},
            {"id": "mistral_wind_7b", "name": "Mistral Wind 7B", "params_b": 7, "hidden_score": 55, "model_type": "text"},
            {"id": "falcon_40b", "name": "Falcon Peak 40B", "params_b": 40, "hidden_score": 58, "model_type": "text"},
            {"id": "zhiju_13b", "name": "智算-13B", "params_b": 13, "hidden_score": 52, "model_type": "text"},
            {"id": "open_vision_3b", "name": "OpenVision-3B", "params_b": 3, "hidden_score": 45, "model_type": "multimodal"},
        ]
        for m in baseline:
            m["source"] = "open"
            m["api_enabled"] = False
            m["open_source"] = True
            m["price_output"] = 0
        # Merge with any open models already seeded by CompetitorsSystem
        existing = {m["id"]: m for m in state.get("open_models", [])}
        for m in baseline:
            existing.setdefault(m["id"], m)
        state["open_models"] = list(existing.values())
        # Do NOT overwrite competitor_models — owned by CompetitorsSystem
        state.setdefault("competitor_models", [])
