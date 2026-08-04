"""Pure calculators for model scores, reputation, and market share.

Keep side-effect free so they are easy to unit-test and reuse.
"""

from __future__ import annotations

import math
import random
from typing import Any


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def compute_hidden_score(
    *,
    capacity_level: int,
    research_levels: dict[str, int],
    research_cfg: dict[str, Any],
    model_type_mult: float = 1.0,
    params_b: float = 7.0,
    data_quality: float = 1.0,
    training_days_factor: float = 1.0,
    from_scratch: bool = True,
    base_model_hidden: float = 0.0,
) -> float:
    """Hidden score = capacity base * product of mult effects * data * params curve."""
    cap_cfg = research_cfg.get("capacity", {})
    base_per_lv = float(cap_cfg.get("effects", {}).get("hidden_score_base", 10))
    base = 20.0 + capacity_level * base_per_lv

    # Param scale (log-ish)
    param_factor = 1.0 + math.log10(max(params_b, 0.5) + 1) * 0.35

    mult = 1.0
    for rid, level in research_levels.items():
        if level <= 0:
            continue
        cfg = research_cfg.get(rid, {})
        effects = cfg.get("effects", {})
        if "hidden_score_mult" in effects:
            mult *= (1.0 + float(effects["hidden_score_mult"]) * level)

    # Soft bonuses from non-mult researches
    for rid, key in (
        ("harmlessness", "safety_score"),
        ("cot", "eval_reasoning_bias"),
        ("agentic", "agent_capability"),
    ):
        lv = research_levels.get(rid, 0)
        cfg = research_cfg.get(rid, {})
        effects = cfg.get("effects", {})
        if lv > 0 and key in effects:
            mult *= 1.0 + float(effects[key]) * lv * 0.25

    score = base * param_factor * mult * model_type_mult * max(0.4, data_quality) * max(0.5, training_days_factor)

    if not from_scratch and base_model_hidden > 0:
        # Finetune: blend upward from base
        score = base_model_hidden * 0.55 + score * 0.55

    return round(clamp(score, 1, 200), 2)


def compute_eval_scores(
    hidden: float,
    *,
    research_levels: dict[str, int],
    data_levels: dict[str, int],
    benchmarks: dict[str, Any],
    model_type: str,
    rng: random.Random,
) -> dict[str, float]:
    """EVAL scores with noise and research-driven bias."""
    results: dict[str, float] = {}
    for bid, bcfg in benchmarks.items():
        allowed = bcfg.get("model_types")
        if allowed and model_type not in allowed:
            continue
        noise = float(bcfg.get("noise", 0.05))
        bias = 0.0
        for src in bcfg.get("bias_from", []):
            lv = research_levels.get(src, 0) + data_levels.get(src, 0)
            bias += lv * 0.8
        # Map hidden 0-200 -> roughly 0-100 scale with noise
        center = hidden * 0.5 + bias
        roll = rng.gauss(0, noise * 40)
        results[bid] = round(clamp(center + roll, 0, 100), 2)
    if results:
        results["average"] = round(sum(results.values()) / len(results), 2)
    else:
        results["average"] = round(clamp(hidden * 0.5, 0, 100), 2)
    return results


def compute_open_source_ratio(models: list[dict]) -> float:
    released = [m for m in models if m.get("released") and not m.get("preview_only")]
    if not released:
        return 0.5  # neutral before any release
    opens = sum(1 for m in released if m.get("open_source"))
    return opens / len(released)


def compute_transparency(
    *,
    interpretability_level: int,
    gov_relation: float,
    base: float = 20.0,
) -> float:
    """Transparency rises with interpretability; higher gov relation lowers base."""
    gov_penalty = gov_relation * 0.25
    score = base - gov_penalty + interpretability_level * 4.0
    return clamp(score)


def compute_innovation(research_levels: dict[str, int], model_research_ids: list[str]) -> float:
    total = sum(research_levels.get(rid, 0) for rid in model_research_ids)
    # Soft saturation
    return clamp(total * 2.2)


def compute_company_tendencies(state: dict[str, Any], configs: Any) -> dict[str, float]:
    company = state.get("company", {})
    research = state.get("research", {}).get("levels", {})
    levels = {k: int(v.get("level", 0)) if isinstance(v, dict) else int(v) for k, v in research.items()}
    models = state.get("models", [])

    research_cfg = configs.load("research")
    model_ids = list(research_cfg.get("model_research", {}).keys())

    openness = clamp(
        30 * compute_open_source_ratio(models)
        + float(company.get("tendencies", {}).get("openness", 30)) * 0.5
        + float(company.get("modifiers", {}).get("openness", 0)),
        0,
        100,
    )
    # Blend stored with computed
    stored = company.get("tendencies", {})
    gov = clamp(float(stored.get("gov_relation", 20)))
    pub = clamp(float(stored.get("public_rep", 20)))
    interp = levels.get("interpretability", 0)
    transparency = compute_transparency(interpretability_level=interp, gov_relation=gov)
    # slight blend with stored
    transparency = clamp(transparency * 0.7 + float(stored.get("transparency", transparency)) * 0.3)
    innovation = clamp(
        compute_innovation(levels, model_ids) * 0.6
        + float(stored.get("innovation", 20)) * 0.4
        + float(company.get("modifiers", {}).get("innovation", 0))
    )

    # Openness also nudged by stored openness_bonus path
    openness = clamp(openness * 0.6 + float(stored.get("openness", 30)) * 0.4)

    return {
        "openness": round(openness, 2),
        "gov_relation": round(gov, 2),
        "public_rep": round(pub, 2),
        "transparency": round(transparency, 2),
        "innovation": round(innovation, 2),
    }


def reputation_after_release(
    *,
    current_rep: float,
    hidden: float,
    api_price: float,
    open_source: bool,
    peer_reps: list[tuple[float, float, float]],
    cfg: dict[str, Any],
) -> float:
    """Move public rep toward peers with similar hidden/price; OS always boosts."""
    price = max(api_price, 0.1)
    ratio = hidden / price
    if peer_reps:
        # peer: (hidden, price, rep)
        peers_sorted = sorted(peer_reps, key=lambda p: abs((p[0] / max(p[1], 0.1)) - ratio))
        target = peers_sorted[0][2]
    else:
        target = clamp(hidden * float(cfg.get("hidden_to_rep_factor", 0.15)) * 10)

    rate = float(cfg.get("rep_convergence_rate", 0.08))
    impact = float(cfg.get("release_rep_impact", 0.25))
    new_rep = current_rep + (target - current_rep) * rate * (1 + impact)

    if open_source:
        bonus = float(cfg.get("open_source_rep_bonus", 5)) + hidden * float(
            cfg.get("open_source_hidden_scale", 0.05)
        )
        new_rep += bonus

    return round(clamp(new_rep), 2)


def segment_demand(
    *,
    segment: dict[str, Any],
    model: dict[str, Any],
    company_tendencies: dict[str, float],
    country_bias: float,
    best_eval_in_market: float,
    demand_mod: float = 1.0,
) -> float:
    """Relative attraction score for one segment toward one model."""
    if not model.get("api_enabled") or not model.get("released"):
        return 0.0

    evals = model.get("eval_scores", {})
    avg = float(evals.get("average", 50))
    hidden = float(model.get("hidden_score", 50))
    price = float(model.get("price_output", 6.0))

    quality = avg / 100.0
    if segment.get("prefers_best") and best_eval_in_market > 0:
        # Strong preference for top model
        quality *= 0.5 + 0.5 * (avg / best_eval_in_market)

    # Specialty spikes pull a smaller audience
    specialty = 0.0
    focus = segment.get("eval_focus") or []
    for f in focus:
        # map focus names to benchmarks loosely
        key = {"coding": "humaneval", "reasoning": "gsm8k", "safety": "safetybench"}.get(f, f)
        if key in evals and evals[key] > avg + 8:
            specialty += 0.15

    price_factor = 1.0 / (1.0 + price * float(segment.get("price_sensitivity", 1.0)) * 0.08)
    novelty = 1.0 + float(segment.get("novelty_bias", 0.3)) * (0.3 if model.get("preview") else 0.1)
    if model.get("is_new"):
        novelty += 0.2 * float(segment.get("novelty_bias", 0.3))

    gov = 1.0 + float(segment.get("gov_relation_factor", 0.0)) * (
        company_tendencies.get("gov_relation", 0) / 100.0
    )

    rep_mult = 0.5 + company_tendencies.get("public_rep", 20) / 100.0
    type_aff = float(model.get("segment_affinity", {}).get(segment["id"], 1.0))

    pay = float(segment.get("pay_willingness", 0.2))
    qsens = float(segment.get("quality_sensitivity", 1.0))

    score = (
        float(segment.get("base_population", 1000))
        * country_bias
        * pay
        * (quality ** qsens)
        * price_factor
        * novelty
        * gov
        * rep_mult
        * type_aff
        * (1.0 + specialty)
        * demand_mod
        * (0.7 + hidden / 250.0)
    )
    return max(0.0, score)


def monthly_api_revenue(
    attraction: float,
    price_output: float,
    usage_tokens_m: float = 0.05,
) -> float:
    """Crude conversion from attraction score to revenue."""
    users = attraction * 0.0008
    return users * usage_tokens_m * price_output * 30
