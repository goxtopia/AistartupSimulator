"""Model training, datasets, release, distillation."""

from __future__ import annotations

import re
import uuid
from typing import Any

from backend.app.engine.calculators import scores as calc


class TrainingSystem:
    name = "training"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        state["datasets"] = []
        state["models"] = []
        state["training"] = {
            "active": [],
            "dataset_jobs": [],
            "history": [],
            "auto_distill": {},
            "auto_rl": {"enabled": False, "status": "off", "cycles_completed": 0},
        }
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
        self._ensure_dataset_jobs(state)
        dataset_jobs = state.get("training", {}).get("dataset_jobs", [])
        datasets_done = []
        for job in dataset_jobs:
            if job.get("paused"):
                continue
            speed = self._dataset_speed(state, job)
            n = len(job.get("employee_ids") or [])
            daily = float(job.get("daily_cost_base", 700)) * (0.8 + 0.1 * max(1, n))
            job["speed_per_day"] = round(speed, 2)
            job["daily_cost"] = round(daily, 2)
            for _ in range(days):
                state["company"]["capital"] = float(state["company"].get("capital", 0)) - daily
                job["total_invested"] = float(job.get("total_invested", 0)) + daily
                job["progress"] = float(job.get("progress", 0)) + speed
                if job["progress"] >= float(job.get("needed", 100)):
                    datasets_done.append(job)
                    break

        for job in datasets_done:
            if job in dataset_jobs:
                dataset_jobs.remove(job)
            dataset = {
                "id": job["dataset_id"],
                "name": job["name"],
                "open_source_base": job["open_source_base"],
                "quality": job["quality"],
                "weights": job["weights"],
                "created_day": state.get("day", 0),
                "cost": round(float(job.get("total_invested", job.get("upfront_cost", 0))), 2),
            }
            state.setdefault("datasets", []).append(dataset)
            for eid in job.get("employee_ids", []):
                emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
                if emp and emp.get("assigned_to") == f"dataset:{job['id']}":
                    emp["assigned_to"] = None
                    emp.setdefault("skills", {})["data_eng"] = round(
                        min(100, float(emp.get("skills", {}).get("data_eng", 0)) + 2.0), 1
                    )
            msg = f"数据集构建完成：{dataset['name']}（质量 {dataset['quality']}）"
            events.append({"type": "dataset_done", "msg": msg, "dataset_id": dataset["id"]})
            state.setdefault("log", []).append({"day": state.get("day", 0), "msg": msg, "cat": "dataset"})

        events.extend(self._schedule_auto_rl(state, ctx))
        events.extend(self._schedule_auto_distill(state, ctx))
        active = state.get("training", {}).get("active", [])
        self._refresh_compute_allocations(state, ctx)
        done = []
        for job in active:
            if job.get("paused"):
                continue
            speed = self._train_speed(state, job, ctx)
            # Staff-dependent daily burn
            n = max(1, len(job.get("employee_ids") or []))
            daily = float(job.get("daily_cost_base", job.get("daily_cost", 0))) * (0.7 + 0.08 * n)
            job["daily_cost"] = daily
            job["speed_per_day"] = round(speed, 2)

            for _ in range(days):
                state["company"]["capital"] = float(state["company"].get("capital", 0)) - daily
                job["progress"] = float(job.get("progress", 0)) + speed
                job["person_days"] = float(job.get("person_days", 0)) + n
                # phase milestones
                pct = job["progress"] / max(float(job.get("needed", 100)), 1)
                phase = self._phase_for_pct(pct, job)
                if phase != job.get("phase"):
                    prev = job.get("phase")
                    job["phase"] = phase
                    if prev:
                        events.append(
                            {
                                "type": "train_phase",
                                "msg": f"训练「{job['name']}」进入阶段：{phase}",
                                "job_id": job["id"],
                            }
                        )
                if job["progress"] >= float(job.get("needed", 100)):
                    done.append(job)
                    break

        for job in done:
            if job in active:
                active.remove(job)
            model = (
                self._finalize_improvement(state, job, ctx)
                if job.get("improvement")
                else self._finalize_model(state, job, ctx)
            )
            state.setdefault("models", []).append(model)
            auto_distill_id = job.get("auto_distill_id")
            if auto_distill_id:
                automation = state.setdefault("training", {}).setdefault("auto_distill", {}).get(auto_distill_id)
                if automation:
                    automation["current_model_id"] = model["id"]
                    automation["cycles_completed"] = int(automation.get("cycles_completed", 0)) + 1
                    automation["last_completed_day"] = state.get("day", 0)
                    automation["last_job_id"] = job["id"]
                    automation["active_job_id"] = None
                    if automation.get("enabled"):
                        automation["status"] = "planning"
                    else:
                        automation["status"] = "paused"
                        automation["status_message"] = "已停止；最后一轮蒸馏已完成"
                    model["auto_distill_id"] = auto_distill_id
            if job.get("auto_rl"):
                automation = state.setdefault("training", {}).setdefault("auto_rl", {})
                automation["latest_model_id"] = model["id"]
                automation["latest_model_name"] = model["name"]
                automation["latest_score"] = round(float(model.get("hidden_score", 0)), 2)
                automation["cycles_completed"] = int(automation.get("cycles_completed", 0)) + 1
                automation["last_completed_day"] = state.get("day", 0)
                automation["last_job_id"] = job["id"]
                automation["active_job_id"] = None
                if automation.get("enabled"):
                    automation["status"] = "planning"
                    automation["status_message"] = "本轮完成，正在重新选择当前最强模型"
                else:
                    automation["status"] = "paused"
                    automation["status_message"] = "已停止；最后一轮 RL 后训练已完成"
                model["auto_rl"] = True
            state.setdefault("training", {}).setdefault("history", []).append(
                {
                    "job_id": job["id"],
                    "model_id": model["id"],
                    "model_name": model["name"],
                    "method": (job.get("improvement") or {}).get("method", "pretrain"),
                    "source_model_id": (job.get("improvement") or {}).get("source_model_id"),
                    "completed_day": state.get("day", 0),
                }
            )
            for eid in job.get("employee_ids", []):
                emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
                if emp:
                    emp["assigned_to"] = None
                    for sk in (emp.get("skill_focus") or [])[:2]:
                        emp["skills"][sk] = round(min(100, float(emp["skills"].get(sk, 0)) + 2.0), 1)
            action_label = (job.get("improvement") or {}).get("method_label", "训练")
            msg = f"{action_label}完成：{model['name']}（隐藏分 {model['hidden_score']}）"
            events.append({"type": "train_done", "msg": msg, "model_id": model["id"]})
            state.setdefault("log", []).append({"day": state.get("day", 0), "msg": msg, "cat": "training"})

        self._refresh_compute_allocations(state, ctx)
        events.extend(self._schedule_auto_rl(state, ctx))
        events.extend(self._schedule_auto_distill(state, ctx))

        for m in state.get("models", []):
            if m.get("is_new") and state.get("day", 0) - int(m.get("released_day") or m.get("created_day", 0)) > 21:
                m["is_new"] = False

        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        types = ctx.configs().load("model_types")
        self._ensure_dataset_jobs(state)
        self._refresh_compute_allocations(state, ctx)
        dataset_jobs_out = []
        for job in state.get("training", {}).get("dataset_jobs", []):
            speed = self._dataset_speed(state, job)
            needed = float(job.get("needed", 100))
            progress = float(job.get("progress", 0))
            pct = min(100.0, progress / max(needed, 1) * 100)
            staff = []
            for eid in job.get("employee_ids") or []:
                emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
                if emp:
                    staff.append({"id": emp["id"], "name": emp["name"], "role_name": emp.get("role_name")})
            dataset_jobs_out.append(
                {
                    **job,
                    "progress_pct": round(pct, 1),
                    "speed_per_day": round(speed, 2),
                    "eta_days": round((needed - progress) / speed, 1) if speed > 0 and progress < needed else None,
                    "staff": staff,
                    "paused": bool(job.get("paused")),
                }
            )
        active_out = []
        for job in state.get("training", {}).get("active", []):
            speed = self._train_speed(state, job, ctx)
            needed = float(job.get("needed", 100))
            progress = float(job.get("progress", 0))
            pct = min(100.0, (progress / needed) * 100.0) if needed else 0.0
            eta = round((needed - progress) / speed, 1) if speed > 0.01 and progress < needed else None
            staff = []
            for eid in job.get("employee_ids") or []:
                emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
                if emp:
                    staff.append({"id": emp["id"], "name": emp["name"], "role_name": emp.get("role_name")})
            active_out.append(
                {
                    **job,
                    "progress_pct": round(pct, 1),
                    "speed_per_day": round(speed, 2),
                    "eta_days": eta,
                    "phase": job.get("phase") or self._phase_for_pct(pct / 100.0, job),
                    "phases": self._phase_list(job),
                    "staff": staff,
                    "paused": bool(job.get("paused")),
                }
            )
        param_presets = [
            {
                **preset,
                "performance_factor": round(
                    calc.parameter_scaling_factor(float(preset.get("params_b", 1))), 3
                ),
            }
            for preset in types.get("param_presets", [])
        ]
        return {
            "datasets": state.get("datasets", []),
            "dataset_jobs": dataset_jobs_out,
            "models": [self._public_model(m) for m in state.get("models", [])],
            "active": active_out,
            "history": list(state.get("training", {}).get("history", []))[-30:],
            "auto_distill": self._public_auto_distill(state),
            "auto_rl": self._public_auto_rl(state),
            "model_types": types.get("model_types", {}),
            "param_presets": param_presets,
            "parameter_requirements": {
                "capacity_gate": False,
                "note": "参数规模不需要研究解锁；更大模型消耗更多资金与算力。",
            },
            "open_models": state.get("open_models", []),
            "competitor_models": state.get("competitor_models", []),
        }

    def create_dataset(
        self,
        state: dict[str, Any],
        ctx,
        name: str,
        use_open: bool,
        weights: dict[str, float],
        employee_ids: list[str] | None = None,
        expected_days: int = 20,
    ) -> tuple[bool, str, dict | None]:
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

        total_cost_estimate = 15000 + (0 if use_open else 25000) + sum(
            int((levels.get(k, {}) or {}).get("level", 0) if isinstance(levels.get(k), dict) else 0) * 3000
            for k in norm
        )
        upfront = max(4000.0, total_cost_estimate * 0.2)
        if state["company"]["capital"] < upfront:
            return False, f"启动资金不足（需要 ${upfront:,.0f}）", None

        employee_ids = list(employee_ids or [])[:12]
        emps = []
        for eid in employee_ids:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if not emp:
                return False, f"员工 {eid} 不存在", None
            if emp.get("assigned_to"):
                return False, f"{emp['name']} 已有任务", None
            emps.append(emp)

        state["company"]["capital"] -= upfront
        days = max(5, min(180, int(expected_days)))
        job_id = str(uuid.uuid4())[:8]
        job = {
            "id": job_id,
            "dataset_id": "ds_" + str(uuid.uuid4())[:8],
            "name": name,
            "open_source_base": use_open,
            "quality": round(q, 3),
            "weights": norm,
            "progress": 0.0,
            "needed": float(days) * 10,
            "expected_days": days,
            "employee_ids": [e["id"] for e in emps],
            "daily_cost_base": max(500.0, (total_cost_estimate - upfront) / days),
            "daily_cost": 0.0,
            "upfront_cost": upfront,
            "total_invested": upfront,
            "started_day": state.get("day", 0),
            "paused": not bool(emps),
            "team_cap": 12,
        }
        for emp in emps:
            emp["assigned_to"] = f"dataset:{job_id}"
        self._ensure_dataset_jobs(state)
        state["training"]["dataset_jobs"].append(job)
        suffix = f"，预计约 {days} 天" if emps else "，尚未分配人员，项目已暂停"
        return True, f"数据集「{name}」开始构建{suffix}", job

    def assign_dataset(
        self, state: dict[str, Any], job_id: str, employee_ids: list[str]
    ) -> tuple[bool, str, dict | None]:
        self._ensure_dataset_jobs(state)
        job = next((j for j in state["training"]["dataset_jobs"] if j["id"] == job_id), None)
        if not job:
            return False, "数据集构建任务不存在", None
        employee_ids = list(employee_ids or [])[: int(job.get("team_cap", 12))]
        valid = []
        for eid in employee_ids:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if not emp:
                return False, f"员工 {eid} 不存在", None
            if emp.get("assigned_to") and emp.get("assigned_to") != f"dataset:{job_id}":
                return False, f"{emp['name']} 已有任务", None
            valid.append(eid)
        for eid in job.get("employee_ids") or []:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if emp and emp.get("assigned_to") == f"dataset:{job_id}":
                emp["assigned_to"] = None
        for eid in valid:
            emp = next(e for e in state.get("employees", []) if e["id"] == eid)
            emp["assigned_to"] = f"dataset:{job_id}"
        job["employee_ids"] = valid
        job["paused"] = not bool(valid)
        return True, (f"数据集「{job['name']}」现有 {len(valid)} 人" if valid else f"已暂停数据集「{job['name']}」构建"), job

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
        need_flops = self._compute_required_tf(
            {
                "params_b": params_b,
                "model_type": model_type,
                "from_scratch": from_scratch and not distill,
                "distill": distill,
            },
            ctx,
        )

        if pool["flops_tf"] < need_flops * 0.04:
            return False, f"算力不足（需要约 {need_flops:.0f} TF 有效算力，当前 {pool['flops_tf']}）", None

        base_hidden = 0.0
        base_label = None
        license_fee = 0.0
        if not from_scratch and base_model_id:
            base = self._find_base_model(state, base_model_id)
            if not base:
                return False, "基座模型不存在", None
            base_hidden = float(base.get("hidden_score", 40))
            base_label = base.get("name")
            # cost for using closed competitor
            if base.get("source") == "closed_competitor":
                # cost ∝ architecture strength ~ hidden
                license_fee += base_hidden * 800
            elif base.get("source") == "open":
                license_fee += float(base.get("params_b", params_b)) * 50

        if distill:
            teacher = self._find_base_model(state, distill["teacher_model_id"])
            if not teacher:
                return False, "教师模型不存在", None
            # Resolve source from the actual teacher record so a caller cannot
            # disguise a closed competitor model as an own/open teacher.
            src = str(teacher.get("source") or distill.get("teacher_source", "own"))
            distill["teacher_source"] = src
            distill["teacher_model_name"] = teacher.get("name")
            if src == "closed_competitor":
                license_fee += float(teacher.get("hidden_score", 50)) * 1000
            elif src == "open":
                license_fee += float(teacher.get("params_b", 7)) * 80
            else:
                license_fee += float(teacher.get("params_b", 7)) * 40
            base_hidden = float(teacher.get("hidden_score", 50))
            base_label = teacher.get("name")

        days = max(3, int(expected_days * float(tcfg.get("time_multiplier", 1.0))))
        presets = ctx.configs().load("model_types").get("param_presets", [])
        parameter_units = calc.parameter_compute_units(params_b, presets)
        # Larger models require a superlinear compute footprint. Performance
        # approaches a boundary, but training cost keeps climbing.
        upfront = 8000 + parameter_units * 250 * float(tcfg.get("difficulty", 1.0))
        total_upfront = upfront + license_fee
        if state["company"]["capital"] < total_upfront:
            return False, f"启动资金不足（含授权共需 ${total_upfront:,.0f}）", None
        state["company"]["capital"] -= total_upfront

        daily_base = upfront * 0.04 + pool["flops_tf"] * 0.35 + parameter_units * 4.0
        job = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "model_type": model_type,
            "params_b": params_b,
            "parameter_compute_units": round(parameter_units, 2),
            "parameter_scale_factor": round(calc.parameter_scaling_factor(params_b), 3),
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
            "daily_cost_base": daily_base,
            "daily_cost": daily_base * (0.7 + 0.08 * max(1, len(emps))),
            "compute_required_tf": round(need_flops, 2),
            "compute_share": 0.0,
            "started_day": state.get("day", 0),
            "phase": "数据准备",
            "person_days": 0.0,
            "paused": False,
            "team_cap": 20,
            "upfront_cost": round(total_upfront, 2),
            "license_fee": round(license_fee, 2),
        }
        for e in emps:
            e["assigned_to"] = f"train:{job['id']}"
        state.setdefault("training", {}).setdefault("active", []).append(job)
        self._refresh_compute_allocations(state, ctx)
        eta_hint = f"，目标约 {days} 天" if emps else "（无人值守会很慢）"
        return True, f"立项训练 {name}{eta_hint} · 启动 ${total_upfront:,.0f}", job

    def start_improvement(
        self,
        state: dict[str, Any],
        ctx,
        *,
        model_id: str,
        method: str,
        name: str | None = None,
        dataset_id: str | None = None,
        teacher_model_id: str | None = None,
        teacher_source: str = "own",
        expected_days: int = 14,
        employee_ids: list[str] | None = None,
    ) -> tuple[bool, str, dict | None]:
        labels = {"fine_tune": "继续微调", "distill": "蒸馏优化", "rl": "RL 后训练"}
        if method not in labels:
            return False, "未知后训练方式", None
        source = next((m for m in state.get("models", []) if m["id"] == model_id), None)
        if not source:
            return False, "自有模型不存在", None
        if any(
            (job.get("improvement") or {}).get("source_model_id") == model_id
            for job in state.get("training", {}).get("active", [])
        ):
            return False, "该模型已有进行中的后训练任务", None

        dataset = None
        resolved_dataset_id = dataset_id or source.get("dataset_id")
        if resolved_dataset_id:
            dataset = next((d for d in state.get("datasets", []) if d["id"] == resolved_dataset_id), None)
        if method == "fine_tune" and not dataset:
            return False, "继续微调需要选择可用数据集", None

        teacher = None
        license_fee = 0.0
        if method == "distill":
            if not teacher_model_id:
                return False, "蒸馏优化需要选择教师模型", None
            teacher = self._find_base_model(state, teacher_model_id)
            if not teacher:
                return False, "教师模型不存在", None
            if teacher_model_id == model_id:
                return False, "不能使用模型自身作为教师", None
            teacher_source = str(teacher.get("source") or teacher_source)
            if teacher_source == "closed_competitor":
                license_fee = float(teacher.get("hidden_score", 50)) * 550
            elif teacher_source == "open":
                license_fee = float(teacher.get("params_b", 7)) * 35

        employee_ids = list(employee_ids or [])[:16]
        employees = []
        for employee_id in employee_ids:
            employee = next((e for e in state.get("employees", []) if e["id"] == employee_id), None)
            if not employee:
                return False, f"员工 {employee_id} 不存在", None
            if employee.get("assigned_to"):
                return False, f"{employee['name']} 已有任务", None
            employees.append(employee)

        compute_system = ctx.get_system("compute")
        pool = compute_system.pool_stats(state, ctx) if compute_system else {"flops_tf": 100}
        params_b = float(source.get("params_b", 7))
        presets = ctx.configs().load("model_types").get("param_presets", [])
        parameter_units = calc.parameter_compute_units(params_b, presets)
        compute_factor = {"fine_tune": 0.18, "distill": 0.12, "rl": 0.24}[method]
        need_flops = self._compute_required_tf(
            {
                "params_b": params_b,
                "model_type": source.get("model_type", "text"),
                "from_scratch": False,
                "improvement": {"method": method},
            },
            ctx,
        )
        if float(pool.get("flops_tf", 0)) < need_flops * 0.04:
            return False, f"算力不足（后训练需要约 {need_flops:.0f} TF，当前 {pool.get('flops_tf', 0)}）", None

        days = max(5, min(90, int(expected_days)))
        upfront = {
            "fine_tune": 4500 + parameter_units * 90,
            "distill": 3500 + parameter_units * 55,
            "rl": 7000 + parameter_units * 120,
        }[method]
        total_upfront = upfront + license_fee
        if float(state["company"].get("capital", 0)) < total_upfront:
            return False, f"启动资金不足（需要 ${total_upfront:,.0f}）", None
        state["company"]["capital"] = float(state["company"].get("capital", 0)) - total_upfront

        generation = int(source.get("generation", 1)) + 1
        family_name = self._model_family_name(source)
        version_number = self._next_family_version(state, source)
        output_name = (name or "").strip() or self._version_name(source, version_number)
        improvement = {
            "method": method,
            "method_label": labels[method],
            "source_model_id": source["id"],
            "source_model_name": source["name"],
            "source_hidden": float(source.get("hidden_score", 0)),
            "source_evals": dict(source.get("eval_scores", {})),
            "teacher_model_id": teacher_model_id,
            "teacher_model_name": teacher.get("name") if teacher else None,
            "teacher_hidden": float(teacher.get("hidden_score", 0)) if teacher else 0.0,
            "teacher_source": teacher_source if teacher else None,
        }
        daily_base = (
            upfront * 0.025
            + float(pool.get("flops_tf", 100)) * 0.1 * compute_factor
            + parameter_units * 0.9 * compute_factor
        )
        job = {
            "id": str(uuid.uuid4())[:8],
            "name": output_name,
            "model_type": source.get("model_type", "text"),
            "params_b": params_b,
            "parameter_compute_units": round(parameter_units, 2),
            "parameter_scale_factor": round(calc.parameter_scaling_factor(params_b), 3),
            "dataset_id": resolved_dataset_id,
            "from_scratch": False,
            "base_model_id": source["id"],
            "base_hidden": float(source.get("hidden_score", 0)),
            "base_label": source["name"],
            "expected_days": days,
            "progress": 0.0,
            "needed": float(days) * 10,
            "employee_ids": [e["id"] for e in employees],
            "daily_cost_base": daily_base,
            "daily_cost": daily_base * (0.7 + 0.08 * max(1, len(employees))),
            "compute_required_tf": round(need_flops, 2),
            "compute_share": 0.0,
            "started_day": state.get("day", 0),
            "phase": self._phase_list({"improvement": improvement})[0]["name"],
            "person_days": 0.0,
            "paused": False,
            "team_cap": 16,
            "improvement": improvement,
            "source_snapshot": dict(source),
            "family_name": family_name,
            "version_number": version_number,
            "dataset_quality": float((dataset or {}).get("quality", 0.7)),
            "dataset_weights": dict((dataset or {}).get("weights", {})),
            "upfront_cost": round(total_upfront, 2),
        }
        for employee in employees:
            employee["assigned_to"] = f"train:{job['id']}"
        state.setdefault("training", {}).setdefault("active", []).append(job)
        self._refresh_compute_allocations(state, ctx)
        return True, f"已启动{labels[method]}：{source['name']} → {output_name}，预计约 {days} 天", job

    def set_auto_distill(
        self,
        state: dict[str, Any],
        ctx,
        *,
        model_id: str,
        enabled: bool,
        mode: str = "open",
    ) -> tuple[bool, str, dict | None]:
        if mode not in {"open", "closed", "frontier"}:
            return False, "未知自动蒸馏策略", None
        model = next((item for item in state.get("models", []) if item["id"] == model_id), None)
        if not model:
            return False, "自有模型不存在", None
        self._ensure_dataset_jobs(state)
        automations = state["training"]["auto_distill"]
        automation_id = model.get("auto_distill_id")
        automation = automations.get(automation_id) if automation_id else None
        if not automation:
            automation = next(
                (
                    item
                    for item in automations.values()
                    if item.get("current_model_id") == model_id or item.get("root_model_id") == model_id
                ),
                None,
            )
            automation_id = automation.get("id") if automation else None

        if not enabled:
            if not automation:
                return True, "该模型未开启自动蒸馏", None
            automation["enabled"] = False
            automation["updated_day"] = state.get("day", 0)
            running = any(
                job.get("auto_distill_id") == automation["id"]
                for job in state.get("training", {}).get("active", [])
            )
            automation["status"] = "stopping" if running else "paused"
            automation["status_message"] = (
                "已关闭；当前轮完成后停止" if running else "已停止自动蒸馏"
            )
            if not running:
                automation["active_job_id"] = None
            suffix = "；当前轮完成后停止" if running else ""
            return True, f"已关闭自动蒸馏{suffix}", automation

        if not automation:
            automation_id = "ads_" + str(uuid.uuid4())[:8]
            automation = {
                "id": automation_id,
                "root_model_id": model_id,
                "root_model_name": model.get("name"),
                "current_model_id": model_id,
                "mode": mode,
                "enabled": True,
                "status": "planning",
                "threshold_ratio": 0.9,
                "cycles_completed": 0,
                "created_day": state.get("day", 0),
            }
            automations[automation_id] = automation
        else:
            # Existing chains always continue from their recorded latest version,
            # even if settings were opened from an older ancestor card.
            automation["mode"] = mode
            automation["enabled"] = True
            automation["status"] = "planning"
        automation["updated_day"] = state.get("day", 0)
        model["auto_distill_id"] = automation_id
        events = self._schedule_auto_distill(state, ctx, only_id=automation_id)
        mode_name = {"open": "开源优先", "closed": "闭源优先", "frontier": "最领先"}[mode]
        detail = events[-1]["msg"] if events else automation.get("status_message", "等待调度")
        return True, f"已开启自动蒸馏（{mode_name}）：{detail}", automation

    def set_auto_rl(
        self,
        state: dict[str, Any],
        ctx,
        *,
        enabled: bool,
    ) -> tuple[bool, str, dict]:
        """Toggle company-wide RL automation for the strongest owned model."""
        self._ensure_dataset_jobs(state)
        automation = state["training"]["auto_rl"]
        if not enabled:
            automation["enabled"] = False
            automation["updated_day"] = state.get("day", 0)
            running = any(job.get("auto_rl") for job in state["training"].get("active", []))
            automation["status"] = "stopping" if running else "paused"
            automation["status_message"] = (
                "已关闭；当前轮完成后停止" if running else "已停止自动 RL 后训练"
            )
            if not running:
                automation["active_job_id"] = None
            suffix = "；当前轮完成后停止" if running else ""
            return True, f"已关闭自动 RL 后训练{suffix}", automation

        automation.update(
            {
                "enabled": True,
                "status": "planning",
                "status_message": "正在选择当前最强模型与最合适的空闲员工",
                "updated_day": state.get("day", 0),
            }
        )
        automation.setdefault("created_day", state.get("day", 0))
        automation.setdefault("cycles_completed", 0)
        events = self._schedule_auto_rl(state, ctx)
        detail = events[-1]["msg"] if events else automation.get("status_message", "等待调度")
        return True, f"已开启自动 RL 后训练：{detail}", automation

    def assign(self, state: dict[str, Any], job_id: str, employee_ids: list[str]) -> tuple[bool, str, dict | None]:
        """Reassign staff on a running training job. Progress is kept."""
        job = next((j for j in state.get("training", {}).get("active", []) if j["id"] == job_id), None)
        if not job:
            return False, "训练任务不存在", None
        cap = int(job.get("team_cap", 20))
        employee_ids = list(employee_ids or [])[:cap]

        # free old
        for eid in job.get("employee_ids") or []:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if emp and emp.get("assigned_to") == f"train:{job_id}":
                emp["assigned_to"] = None

        valid = []
        for eid in employee_ids:
            emp = next((e for e in state.get("employees", []) if e["id"] == eid), None)
            if not emp:
                return False, f"员工 {eid} 不存在", None
            if emp.get("assigned_to") and emp.get("assigned_to") != f"train:{job_id}":
                return False, f"{emp['name']} 已有任务", None
            valid.append(eid)
            emp["assigned_to"] = f"train:{job_id}"

        job["employee_ids"] = valid
        job["paused"] = len(valid) == 0
        if job["paused"]:
            return True, f"已暂停训练「{job['name']}」（进度保留）", job
        return True, f"训练「{job['name']}」现有 {len(valid)} 人", job

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
        model.setdefault("auto_price_enabled", False)
        model.setdefault("auto_price_status", "off")
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
        model["auto_price_enabled"] = False
        model["auto_price_status"] = "manual"
        model["auto_price_reason"] = "已由手动价格接管"
        return True, "价格已更新"

    # ---- internals ----

    def _schedule_auto_rl(self, state: dict, ctx) -> list[dict]:
        self._ensure_dataset_jobs(state)
        automation = state.get("training", {}).get("auto_rl", {})
        if not automation.get("enabled"):
            return []

        active_job = next(
            (job for job in state.get("training", {}).get("active", []) if job.get("auto_rl")),
            None,
        )
        if active_job:
            automation["status"] = "running"
            automation["active_job_id"] = active_job["id"]
            automation["status_message"] = f"正在自动 RL 后训练 {active_job['name']}"
            return []

        strongest = max(
            state.get("models", []),
            key=lambda model: (
                float(model.get("hidden_score", 0)),
                float((model.get("eval_scores") or {}).get("average", 0)),
                int(model.get("created_day", 0)),
            ),
            default=None,
        )
        if not strongest:
            automation["status"] = "waiting_model"
            automation["status_message"] = "等待公司首个模型训练完成"
            automation["source_model_id"] = None
            automation["source_model_name"] = None
            return []

        score = float(strongest.get("hidden_score", 0))
        automation.update(
            {
                "source_model_id": strongest["id"],
                "source_model_name": strongest.get("name"),
                "source_score": round(score, 2),
            }
        )
        if any(
            (job.get("improvement") or {}).get("source_model_id") == strongest["id"]
            for job in state.get("training", {}).get("active", [])
        ):
            automation["status"] = "waiting_model"
            automation["status_message"] = "当前最强模型正在进行其他后训练，等待完成"
            return []

        free_employees = [
            employee for employee in state.get("employees", []) if not employee.get("assigned_to")
        ]
        employee = max(
            free_employees,
            key=lambda item: self._rl_employee_fit(state, item),
            default=None,
        )
        if not employee or self._rl_employee_fit(state, employee) < 25:
            automation["status"] = "waiting_staff"
            automation["status_message"] = "等待合适的空闲 RL 训练员工"
            automation["employee_id"] = None
            automation["employee_name"] = None
            return []

        cycle = int(automation.get("cycles_completed", 0)) + 1
        ok, message, job = self.start_improvement(
            state,
            ctx,
            model_id=strongest["id"],
            method="rl",
            name=None,
            dataset_id=strongest.get("dataset_id"),
            expected_days=14,
            employee_ids=[employee["id"]],
        )
        if not ok or not job:
            if "资金" in message or "成本" in message:
                status = "waiting_funds"
            elif "算力" in message:
                status = "waiting_compute"
            else:
                status = "waiting"
            automation["status"] = status
            automation["status_message"] = message
            return []

        job["auto_rl"] = True
        automation.update(
            {
                "status": "running",
                "status_message": f"第 {cycle} 轮：{strongest['name']} → {job['name']}",
                "active_job_id": job["id"],
                "employee_id": employee["id"],
                "employee_name": employee.get("name"),
                "employee_fit": round(self._rl_employee_fit(state, employee), 1),
                "last_started_day": state.get("day", 0),
            }
        )
        msg = (
            f"自动 RL 第 {cycle} 轮已启动：{strongest['name']} → {job['name']}，"
            f"负责人 {employee.get('name')}"
        )
        state.setdefault("log", []).append(
            {"day": state.get("day", 0), "msg": msg, "cat": "training"}
        )
        return [{"type": "auto_rl_started", "msg": msg, "job_id": job["id"]}]

    def _rl_employee_fit(self, state: dict, employee: dict) -> float:
        return (
            calc.employee_skill(state, employee, "rl") * 0.5
            + calc.employee_skill(state, employee, "alignment") * 0.3
            + calc.employee_skill(state, employee, "ml_theory") * 0.15
            + calc.employee_skill(state, employee, "systems") * 0.05
        )

    def _public_auto_rl(self, state: dict) -> dict:
        automation = dict(state.get("training", {}).get("auto_rl", {}))
        models = state.get("models", [])
        strongest = max(
            models,
            key=lambda model: (
                float(model.get("hidden_score", 0)),
                float((model.get("eval_scores") or {}).get("average", 0)),
                int(model.get("created_day", 0)),
            ),
            default=None,
        )
        if strongest:
            automation["strongest_model_id"] = strongest["id"]
            automation["strongest_model_name"] = strongest.get("name")
            automation["strongest_score"] = round(float(strongest.get("hidden_score", 0)), 2)
            automation["strongest_params_b"] = float(strongest.get("params_b", 0))
            automation["strongest_model_type"] = strongest.get("model_type", "text")
        return automation

    def _schedule_auto_distill(
        self, state: dict, ctx, only_id: str | None = None
    ) -> list[dict]:
        self._ensure_dataset_jobs(state)
        events: list[dict] = []
        automations = state.get("training", {}).get("auto_distill", {})
        for automation_id, automation in list(automations.items()):
            if only_id and automation_id != only_id:
                continue
            if not automation.get("enabled"):
                continue
            active_job = next(
                (
                    job
                    for job in state.get("training", {}).get("active", [])
                    if job.get("auto_distill_id") == automation_id
                ),
                None,
            )
            if active_job:
                automation["status"] = "running"
                automation["active_job_id"] = active_job["id"]
                automation["status_message"] = f"正在蒸馏 {active_job['name']}"
                continue

            source = next(
                (
                    model
                    for model in state.get("models", [])
                    if model["id"] == automation.get("current_model_id")
                ),
                None,
            )
            if not source:
                automation["enabled"] = False
                automation["status"] = "source_missing"
                automation["status_message"] = "最新版模型不存在，自动蒸馏已停止"
                continue
            if any(
                (job.get("improvement") or {}).get("source_model_id") == source["id"]
                for job in state.get("training", {}).get("active", [])
            ):
                automation["status"] = "waiting_model"
                automation["status_message"] = "最新版正在进行其他后训练，等待完成"
                continue

            teacher = self._select_auto_distill_teacher(state, source, automation.get("mode", "open"))
            if not teacher:
                automation["status"] = "waiting_teacher"
                automation["status_message"] = "暂无同类型的可用教师模型"
                automation["teacher_model_id"] = None
                continue
            target_score = float(teacher.get("hidden_score", 0))
            threshold = target_score * float(automation.get("threshold_ratio", 0.9))
            automation.update(
                {
                    "teacher_model_id": teacher.get("id"),
                    "teacher_model_name": teacher.get("name"),
                    "teacher_source": teacher.get("source"),
                    "target_score": round(target_score, 2),
                    "threshold_score": round(threshold, 2),
                    "current_score": round(float(source.get("hidden_score", 0)), 2),
                }
            )
            if float(source.get("hidden_score", 0)) >= threshold:
                automation["enabled"] = False
                automation["status"] = "target_reached"
                automation["completed_day"] = state.get("day", 0)
                automation["status_message"] = (
                    f"已达到 {teacher.get('name')} 能力的 90%（目标 H{threshold:.1f}）"
                )
                msg = f"自动蒸馏完成：{source['name']} 已达到目标教师能力的 90%"
                events.append({"type": "auto_distill_complete", "msg": msg, "model_id": source["id"]})
                state.setdefault("log", []).append(
                    {"day": state.get("day", 0), "msg": msg, "cat": "training"}
                )
                continue

            free_employees = [
                employee
                for employee in state.get("employees", [])
                if not employee.get("assigned_to")
            ]
            employee = max(
                free_employees,
                key=lambda item: self._distill_employee_fit(state, item),
                default=None,
            )
            if not employee or self._distill_employee_fit(state, employee) < 25:
                automation["status"] = "waiting_staff"
                automation["status_message"] = "等待合适的空闲训练员工"
                automation["employee_id"] = None
                continue

            cycle = int(automation.get("cycles_completed", 0)) + 1
            ok, message, job = self.start_improvement(
                state,
                ctx,
                model_id=source["id"],
                method="distill",
                name=None,
                dataset_id=source.get("dataset_id"),
                teacher_model_id=teacher["id"],
                teacher_source=teacher.get("source", "own"),
                expected_days=10,
                employee_ids=[employee["id"]],
            )
            if not ok or not job:
                if "资金" in message or "成本" in message or "授权费" in message:
                    status = "waiting_funds"
                elif "算力" in message:
                    status = "waiting_compute"
                else:
                    status = "waiting"
                automation["status"] = status
                automation["status_message"] = message
                continue
            job["auto_distill_id"] = automation_id
            automation.update(
                {
                    "status": "running",
                    "status_message": f"正在进行第 {cycle} 轮：{source['name']} → {job['name']}",
                    "active_job_id": job["id"],
                    "employee_id": employee["id"],
                    "employee_name": employee.get("name"),
                    "last_started_day": state.get("day", 0),
                }
            )
            msg = (
                f"自动蒸馏第 {cycle} 轮已启动：{source['name']} → {job['name']}，"
                f"教师 {teacher.get('name')}，负责人 {employee.get('name')}"
            )
            events.append({"type": "auto_distill_started", "msg": msg, "job_id": job["id"]})
            state.setdefault("log", []).append(
                {"day": state.get("day", 0), "msg": msg, "cat": "training"}
            )
        return events

    def _select_auto_distill_teacher(self, state: dict, source: dict, mode: str) -> dict | None:
        model_type = source.get("model_type", "text")
        candidates: list[dict] = []
        if mode in {"open", "frontier"}:
            candidates.extend({**model, "source": "open"} for model in state.get("open_models", []))
            candidates.extend(
                model
                for model in state.get("competitor_models", [])
                if model.get("source") == "open"
            )
        if mode in {"closed", "frontier"}:
            candidates.extend(
                model
                for model in state.get("competitor_models", [])
                if model.get("source") == "closed_competitor"
            )
        if mode == "frontier":
            candidates.extend(
                {**model, "source": "own"}
                for model in state.get("models", [])
                if model["id"] != source["id"]
            )
        unique = {
            model["id"]: model
            for model in candidates
            if model.get("id") != source.get("id")
            and model.get("model_type", "text") == model_type
        }
        return max(unique.values(), key=lambda model: float(model.get("hidden_score", 0)), default=None)

    def _distill_employee_fit(self, state: dict, employee: dict) -> float:
        return (
            calc.employee_skill(state, employee, "ml_theory") * 0.58
            + calc.employee_skill(state, employee, "systems") * 0.3
            + calc.employee_skill(state, employee, "data_eng") * 0.12
        )

    def _public_auto_distill(self, state: dict) -> list[dict]:
        output = []
        models = state.get("models", [])
        for automation in state.get("training", {}).get("auto_distill", {}).values():
            current = next(
                (model for model in models if model["id"] == automation.get("current_model_id")),
                None,
            )
            target = float(automation.get("threshold_score", 0))
            current_score = float((current or {}).get("hidden_score", automation.get("current_score", 0)))
            output.append(
                {
                    **automation,
                    "current_model_name": (current or {}).get("name"),
                    "current_score": round(current_score, 2),
                    "progress_pct": round(min(100.0, current_score / target * 100), 1) if target > 0 else 0.0,
                    "mode_name": {
                        "open": "开源优先",
                        "closed": "闭源优先",
                        "frontier": "最领先",
                    }.get(automation.get("mode"), automation.get("mode")),
                }
            )
        return sorted(output, key=lambda item: int(item.get("created_day", 0)), reverse=True)

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
            team_q = 0.85 + sum(
                calc.employee_skill(state, employee, "ml_theory", 30)
                for employee in emps
            ) / len(emps) / 200.0

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
            hidden = max(1.0, hidden)

        market_system = ctx.get_system("market")
        benchmarks = (
            market_system.benchmarks_for_state(state, ctx)
            if market_system
            else ctx.configs().load("market").get("eval_benchmarks", {})
        )
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
            "generation": 1,
            "root_model_id": None,
            "parent_model_id": None,
            "lineage": [],
            "operations": [],
            "family_name": job.get("family_name") or job.get("name"),
            "version_number": int(job.get("version_number", 1)),
        }

    def _finalize_improvement(self, state: dict, job: dict, ctx) -> dict:
        improvement = job.get("improvement") or {}
        source = dict(job.get("source_snapshot") or {})
        method = improvement.get("method", "fine_tune")
        base_hidden = float(improvement.get("source_hidden", source.get("hidden_score", 0)))
        source_evals = dict(improvement.get("source_evals") or source.get("eval_scores") or {})
        employees = [
            employee
            for employee in state.get("employees", [])
            if employee["id"] in (job.get("employee_ids") or [])
        ]
        skill_pairs = {
            "fine_tune": ("ml_theory", "data_eng"),
            "distill": ("ml_theory", "systems"),
            "rl": ("rl", "alignment"),
        }
        skills = skill_pairs.get(method, ("ml_theory", "systems"))
        if employees:
            team_skill = sum(
                calc.employee_skill(state, employee, skills[0], 20) * 0.6
                + calc.employee_skill(state, employee, skills[1], 20) * 0.4
                for employee in employees
            ) / len(employees)
        else:
            team_skill = 15.0

        levels_raw = state.get("research", {}).get("levels", {})
        levels = {
            key: int(value.get("level", 0)) if isinstance(value, dict) else int(value or 0)
            for key, value in levels_raw.items()
        }
        quality = float(job.get("dataset_quality", 0.7))
        # No hidden-score ceiling: repeated post-training can always improve a
        # model, while gains continuously shrink as capability rises.
        diminish = 1.0 / ((1.0 + max(0.0, base_hidden) / 160.0) ** 1.35)
        if method == "fine_tune":
            raw_gain = 1.5 + quality * 2.8 + team_skill / 75.0
        elif method == "distill":
            teacher_hidden = float(improvement.get("teacher_hidden", 0))
            raw_gain = 1.0 + max(0.0, teacher_hidden - base_hidden) * 0.22 + team_skill / 90.0
        else:
            raw_gain = 1.6 + levels.get("rl", 0) * 0.48 + team_skill / 65.0
        hidden_gain = max(0.05, raw_gain * diminish + ctx.rng().uniform(-0.18, 0.32))
        hidden = round(max(1.0, base_hidden + hidden_gain), 2)

        evals = {
            key: float(value)
            for key, value in source_evals.items()
            if key != "average" and isinstance(value, (int, float))
        }
        if not evals:
            evals = {"mmlu": base_hidden * 0.55, "gsm8k": base_hidden * 0.52}
        general_gain = hidden_gain * (0.6 if method == "fine_tune" else 0.48)
        for key in list(evals):
            evals[key] = float(evals[key]) + general_gain

        weights = job.get("dataset_weights") or {}
        if method == "fine_tune":
            domain_bonus = max(1.0, quality * 4.0)
            evals["mmlu"] = evals.get("mmlu", base_hidden * 0.55) + domain_bonus * (
                float(weights.get("frontier_science", 0))
                + float(weights.get("industrial", 0)) * 0.6
                + float(weights.get("admin", 0)) * 0.5
            )
            evals["gsm8k"] = evals.get("gsm8k", base_hidden * 0.52) + domain_bonus * float(
                weights.get("frontier_science", 0)
            )
            evals["humaneval"] = evals.get("humaneval", base_hidden * 0.5) + domain_bonus * float(
                weights.get("code", 0)
            ) * 1.4
            evals["mt_bench"] = evals.get("mt_bench", base_hidden * 0.54) + domain_bonus * float(
                weights.get("creative_writing", 0)
            )
        elif method == "distill":
            transfer = max(0.0, float(improvement.get("teacher_hidden", 0)) - base_hidden) * 0.035
            for key in list(evals):
                evals[key] += transfer
        else:
            rl_level = levels.get("rl", 0)
            alignment_level = levels.get("harmlessness", 0)
            evals["gsm8k"] = evals.get("gsm8k", base_hidden * 0.52) + 2.0 + rl_level * 0.55
            evals["humaneval"] = evals.get("humaneval", base_hidden * 0.5) + 1.2 + rl_level * 0.35
            evals["agentbench"] = evals.get("agentbench", base_hidden * 0.46) + 2.5 + rl_level * 0.65
            evals["safetybench"] = evals.get("safetybench", base_hidden * 0.5) + alignment_level * 0.45

        evals = {key: round(calc.clamp(value, 1, 100), 2) for key, value in evals.items()}
        market_system = ctx.get_system("market")
        benchmarks = (
            market_system.benchmarks_for_state(state, ctx)
            if market_system
            else ctx.configs().load("market").get("eval_benchmarks", {})
        )
        evals["average"] = calc.weighted_eval_average(evals, benchmarks)
        generation = int(source.get("generation", 1)) + 1
        lineage = list(source.get("lineage") or [])
        lineage.append({"id": source.get("id"), "name": source.get("name"), "method": method})
        operations = list(source.get("operations") or [])
        operations.append(
            {
                "method": method,
                "label": improvement.get("method_label"),
                "day": state.get("day", 0),
                "hidden_gain": round(hidden_gain, 2),
            }
        )
        model = {
            **source,
            "id": "mdl_" + str(uuid.uuid4())[:8],
            "name": job["name"],
            "hidden_score": hidden,
            "eval_scores": evals,
            "dataset_id": job.get("dataset_id") or source.get("dataset_id"),
            "from_scratch": False,
            "base_label": source.get("name"),
            "distilled": method == "distill",
            "released": False,
            "open_source": False,
            "preview": False,
            "preview_only": False,
            "full_release": False,
            "api_enabled": False,
            "created_day": state.get("day", 0),
            "released_day": None,
            "is_new": False,
            "daily_users": 0.0,
            "daily_revenue": 0.0,
            "parent_model_id": source.get("id"),
            "parent_model_name": source.get("name"),
            "root_model_id": source.get("root_model_id") or source.get("id"),
            "generation": generation,
            "improvement_method": method,
            "improvement_label": improvement.get("method_label"),
            "teacher_model_id": improvement.get("teacher_model_id"),
            "teacher_model_name": improvement.get("teacher_model_name"),
            "lineage": lineage,
            "operations": operations,
            "family_name": job.get("family_name") or self._model_family_name(source),
            "version_number": int(job.get("version_number", generation)),
        }
        model.pop("segment_performance", None)
        return model

    def _public_model(self, m: dict) -> dict:
        # hide nothing critical for own models; hidden_score visible to player
        return {
            **m,
            "parameter_scale_factor": round(
                calc.parameter_scaling_factor(float(m.get("params_b", 7))), 3
            ),
        }

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

    def _model_family_name(self, model: dict) -> str:
        if model.get("family_name"):
            return str(model["family_name"])
        lineage = model.get("lineage") or []
        if lineage and lineage[0].get("name"):
            root_name = str(lineage[0]["name"])
        else:
            root_name = str(model.get("name") or "Model")
        pattern = re.compile(
            r"(?:-(?:AutoRL|AutoDS|FT|SFT|DS|Distill|RL)(?:-?v\d+)?(?:-c\d+)?|-v\d+)$",
            re.IGNORECASE,
        )
        previous = None
        while root_name != previous:
            previous = root_name
            root_name = pattern.sub("", root_name)
        return root_name or "Model"

    def _version_name(self, source: dict, generation: int) -> str:
        return f"{self._model_family_name(source)}-v{max(1, int(generation)):02d}"

    def _next_family_version(self, state: dict, source: dict) -> int:
        family_name = self._model_family_name(source)
        versions = [1]
        for model in state.get("models", []):
            if self._model_family_name(model) != family_name:
                continue
            versions.append(int(model.get("version_number", model.get("generation", 1))))
        return max(versions) + 1

    def _train_speed(self, state: dict, job: dict, ctx) -> float:
        """Progress units/day. Staff + compute drive the bar; empty team crawls."""
        needed = float(job.get("needed", 100))
        expected = max(1.0, float(job.get("expected_days", 30)))
        base = needed / expected
        improvement_method = (job.get("improvement") or {}).get("method")
        compute_profile = self._compute_runtime_profile(state, job, ctx)
        compute_mult = float(compute_profile["speed_mult"])

        emps = [e for e in state.get("employees", []) if e["id"] in (job.get("employee_ids") or [])]
        if emps:
            skill_pair = {
                "fine_tune": ("ml_theory", "data_eng"),
                "distill": ("ml_theory", "systems"),
                "rl": ("rl", "alignment"),
            }.get(improvement_method, ("ml_theory", "systems"))
            skill = sum(
                calc.employee_skill(state, e, skill_pair[0], 20)
                + calc.employee_skill(state, e, skill_pair[1], 20)
                for e in emps
            ) / len(emps)
            n = len(emps)
            # diminishing returns on headcount
            head = n / (1.0 + 0.1 * max(0, n - 3))
            team_mult = (0.55 + skill / 130.0) * (0.55 + 0.12 * head)
        else:
            # Unstaffed training: compute-only trickle (very slow)
            team_mult = 0.18

        if job.get("paused"):
            return 0.0
        return max(0.08, base * compute_mult * team_mult)

    def _compute_required_tf(self, job: dict, ctx) -> float:
        """Baseline effective TF needed to hit the planned training duration."""
        params_b = float(job.get("params_b", 7))
        type_cfg = ctx.configs().load("model_types").get("model_types", {}).get(
            job.get("model_type", "text"), {}
        )
        presets = ctx.configs().load("model_types").get("param_presets", [])
        parameter_units = float(
            job.get("parameter_compute_units")
            or calc.parameter_compute_units(params_b, presets)
        )
        required = parameter_units * 3.0 * float(type_cfg.get("compute_multiplier", 1.0))
        improvement_method = (job.get("improvement") or {}).get("method")
        if improvement_method:
            required *= {
                "fine_tune": 0.18,
                "distill": 0.12,
                "rl": 0.24,
            }.get(improvement_method, 0.2)
        elif job.get("distill"):
            required *= 0.26
        elif not job.get("from_scratch", True):
            required *= 0.38
        return max(8.0, required)

    def _compute_runtime_profile(self, state: dict, job: dict, ctx) -> dict[str, float | str]:
        compute_system = ctx.get_system("compute")
        pool = compute_system.pool_stats(state, ctx) if compute_system else {"flops_tf": 100}
        pool_tf = max(1.0, float(pool.get("flops_tf", 100)))
        active_jobs = [
            item
            for item in state.get("training", {}).get("active", [])
            if not item.get("paused")
        ]
        if job not in active_jobs and not job.get("paused"):
            active_jobs.append(job)
        demands = {
            item["id"]: float(item.get("compute_required_tf") or self._compute_required_tf(item, ctx))
            for item in active_jobs
        }
        required = float(job.get("compute_required_tf") or self._compute_required_tf(job, ctx))
        total_demand = max(required, sum(demands.values()))
        ratio = pool_tf / max(total_demand, 1.0)
        # Sublinear scaling keeps upgrades valuable without making huge clusters
        # instantly finish a project. 1.0 means the plan duration is achievable.
        speed_mult = float(calc.clamp(ratio ** 0.72, 0.18, 3.5))
        allocated = pool_tf * required / max(total_demand, 1.0)
        if ratio < 0.45:
            status = "严重瓶颈"
        elif ratio < 0.9:
            status = "算力不足"
        elif ratio < 1.35:
            status = "匹配计划"
        else:
            status = "算力加速"
        return {
            "pool_tf": round(pool_tf, 2),
            "required_tf": round(required, 2),
            "total_demand_tf": round(total_demand, 2),
            "allocated_tf": round(allocated, 2),
            "ratio": round(ratio, 4),
            "speed_mult": round(speed_mult, 3),
            "status": status,
        }

    def _refresh_compute_allocations(self, state: dict, ctx) -> None:
        active = state.get("training", {}).get("active", [])
        compute_system = ctx.get_system("compute")
        pool = compute_system.pool_stats(state, ctx) if compute_system else {"flops_tf": 100}
        pool_tf = max(1.0, float(pool.get("flops_tf", 100)))
        total_demand = 0.0
        for job in active:
            required = self._compute_required_tf(job, ctx)
            job["compute_required_tf"] = round(required, 2)
            if not job.get("paused"):
                total_demand += required
        state.setdefault("compute", {})["busy"] = round(
            float(calc.clamp(total_demand / pool_tf, 0.0, 1.0)), 4
        )
        for job in active:
            profile = self._compute_runtime_profile(state, job, ctx)
            job["compute_profile"] = profile
            job["compute_share"] = round(
                float(profile["allocated_tf"]) / pool_tf if pool_tf > 0 else 0.0,
                4,
            )

    def _dataset_speed(self, state: dict, job: dict) -> float:
        if job.get("paused"):
            return 0.0
        emps = [e for e in state.get("employees", []) if e["id"] in (job.get("employee_ids") or [])]
        if not emps:
            return 0.0
        needed = float(job.get("needed", 100))
        expected = max(1.0, float(job.get("expected_days", 20)))
        base = needed / expected
        avg_skill = sum(
            calc.employee_skill(state, e, "data_eng", 20) * 0.7
            + calc.employee_skill(state, e, "product", 20) * 0.3
            for e in emps
        ) / len(emps)
        headcount = len(emps) / (1.0 + 0.14 * max(0, len(emps) - 3))
        return max(0.2, base * (0.55 + avg_skill / 100.0) * (0.72 + headcount * 0.18))

    def _ensure_dataset_jobs(self, state: dict) -> None:
        state.setdefault("training", {}).setdefault("active", [])
        state["training"].setdefault("dataset_jobs", [])
        state["training"].setdefault("history", [])
        state["training"].setdefault("auto_distill", {})
        state["training"].setdefault(
            "auto_rl", {"enabled": False, "status": "off", "cycles_completed": 0}
        )

    def _phase_list(self, job: dict | None = None) -> list[dict]:
        method = ((job or {}).get("improvement") or {}).get("method")
        if method == "fine_tune":
            return [
                {"id": "adapt", "name": "数据适配", "at": 0.0},
                {"id": "sft", "name": "监督微调", "at": 0.2},
                {"id": "validate", "name": "过拟合校验", "at": 0.72},
                {"id": "eval", "name": "评测打包", "at": 0.9},
            ]
        if method == "distill":
            return [
                {"id": "sample", "name": "教师采样", "at": 0.0},
                {"id": "labels", "name": "软标签生成", "at": 0.22},
                {"id": "distill", "name": "蒸馏训练", "at": 0.48},
                {"id": "eval", "name": "一致性评测", "at": 0.9},
            ]
        if method == "rl":
            return [
                {"id": "reward", "name": "奖励建模", "at": 0.0},
                {"id": "policy", "name": "策略优化", "at": 0.25},
                {"id": "align", "name": "对齐校验", "at": 0.7},
                {"id": "eval", "name": "红队评测", "at": 0.9},
            ]
        return [
            {"id": "data", "name": "数据准备", "at": 0.0},
            {"id": "pretrain", "name": "预训练", "at": 0.15},
            {"id": "mid", "name": "中期对齐", "at": 0.55},
            {"id": "sft", "name": "SFT / 精调", "at": 0.75},
            {"id": "eval", "name": "评测打包", "at": 0.92},
        ]

    def _phase_for_pct(self, pct: float, job: dict | None = None) -> str:
        phases = self._phase_list(job)
        name = phases[0]["name"]
        for p in phases:
            if pct >= float(p["at"]):
                name = p["name"]
        return name

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
