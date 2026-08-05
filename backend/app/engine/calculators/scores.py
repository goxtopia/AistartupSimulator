"""Pure calculators for model scores, reputation, and market share.

Keep side-effect free so they are easy to unit-test and reuse.
"""

from __future__ import annotations

import math
import random
from typing import Any


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def chief_scientist_profile(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the active chief scientist and their company-wide skill multiplier."""
    chief_id = state.get("hr", {}).get("chief_scientist_id")
    if not chief_id:
        return None
    chief = next(
        (employee for employee in state.get("employees", []) if employee.get("id") == chief_id),
        None,
    )
    if not chief:
        return None
    ranked_skills = sorted(
        (float(value) for value in (chief.get("skills") or {}).values()), reverse=True
    )[:4]
    ability = sum(ranked_skills) / max(1, len(ranked_skills))
    # A broadly capable 80-point chief grants ×1.20; a perfect chief grants ×1.25.
    multiplier = 1.0 + ability / 400.0
    return {
        "employee_id": chief["id"],
        "name": chief.get("name"),
        "role_name": chief.get("role_name"),
        "ability": round(ability, 1),
        "team_skill_multiplier": round(multiplier, 3),
        "poach_immune": True,
    }


def team_skill_multiplier(state: dict[str, Any]) -> float:
    profile = chief_scientist_profile(state)
    return float(profile.get("team_skill_multiplier", 1.0)) if profile else 1.0


def employee_skill(
    state: dict[str, Any], employee: dict[str, Any], skill: str, default: float = 0.0
) -> float:
    """Effective player-employee skill after the chief scientist team effect."""
    raw = float((employee.get("skills") or {}).get(skill, default))
    return raw * team_skill_multiplier(state)


def parameter_scaling_factor(params_b: float) -> float:
    """Capability multiplier from parameter count with a finite asymptote.

    The Hill-like exponential curve makes scaling from small to medium models
    strategically important while each additional billion parameters buys less
    capability near the ~2.8x boundary.
    """
    params = max(0.1, float(params_b))
    return 0.65 + 2.15 * (1.0 - math.exp(-((params / 45.0) ** 0.42)))


def parameter_compute_units(params_b: float, presets: list[dict[str, Any]] | None = None) -> float:
    """Interpolate the configured superlinear training footprint in log space."""
    params = max(0.1, float(params_b))
    points = sorted(
        (
            (float(item.get("params_b", 0)), float(item.get("compute_units", 0)))
            for item in (presets or [])
            if float(item.get("params_b", 0)) > 0 and float(item.get("compute_units", 0)) > 0
        ),
        key=lambda point: point[0],
    )
    if not points:
        return 10.0 * params ** 1.06
    if params <= points[0][0]:
        return points[0][1] * (params / points[0][0]) ** 1.06
    if params >= points[-1][0]:
        return points[-1][1] * (params / points[-1][0]) ** 1.06
    for (left_p, left_u), (right_p, right_u) in zip(points, points[1:]):
        if left_p <= params <= right_p:
            ratio = math.log(params / left_p) / math.log(right_p / left_p)
            return math.exp(math.log(left_u) + (math.log(right_u) - math.log(left_u)) * ratio)
    return 10.0 * params ** 1.06


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

    # Parameter scaling is one of the main capability drivers, but converges to
    # a finite boundary so brute-force scale cannot replace research and data.
    param_factor = parameter_scaling_factor(params_b)

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

    # Hidden capability has no hard ceiling. Above the frontier pivot, map raw
    # capability through a logarithmic curve: every improvement still counts,
    # but equal additions to research/scale produce progressively fewer points.
    frontier_pivot = 100.0
    if score > frontier_pivot:
        score = frontier_pivot + frontier_pivot * math.log1p(
            (score - frontier_pivot) / frontier_pivot
        )
    return round(max(1.0, score), 2)


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
        # Map hidden capability onto the bounded 0-100 public EVAL scale. Newer dynamic benchmarks can
        # declare difficulty > 1, making yesterday's SOTA meaningfully harder
        # to defend without changing the model's hidden capability.
        difficulty = max(0.5, float(bcfg.get("difficulty", 1.0)))
        center = hidden * 0.5 / difficulty + bias / (difficulty ** 0.35)
        roll = rng.gauss(0, noise * 40)
        results[bid] = round(clamp(center + roll, 0, 100), 2)
    if results:
        results["average"] = weighted_eval_average(results, benchmarks)
    else:
        results["average"] = round(clamp(hidden * 0.5, 0, 100), 2)
    return results


def weighted_eval_average(evals: dict[str, Any], benchmarks: dict[str, Any]) -> float:
    """Weighted market-facing EVAL average, including newly introduced tests."""
    weighted = 0.0
    total_weight = 0.0
    for key, value in evals.items():
        if key == "average" or not isinstance(value, (int, float)):
            continue
        weight = max(0.05, float((benchmarks.get(key) or {}).get("weight", 1.0)))
        weighted += float(value) * weight
        total_weight += weight
    if total_weight <= 0:
        return round(float(evals.get("average", 0)), 2)
    return round(weighted / total_weight, 2)


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
    output_share = clamp(float(segment.get("output_token_share", 0.7)), 0.0, 1.0)
    price = (
        float(model.get("price_output", 6.0)) * output_share
        + float(model.get("price_input", 2.0)) * (1.0 - output_share)
    )

    quality = avg / 100.0
    qsens = float(segment.get("quality_sensitivity", 1.0))
    if segment.get("prefers_best") and best_eval_in_market > 0:
        # Strong preference for top model
        quality *= 0.5 + 0.5 * (avg / best_eval_in_market)
    if best_eval_in_market > 0:
        # API buyers increasingly standardize on models that survive the latest
        # benchmark suite. This makes a genuine frontier lead commercially
        # meaningful instead of being drowned out by dozens of mediocre SKUs.
        relative = clamp(avg / best_eval_in_market, 0.05, 1.0)
        sharpness = (2.2 if segment.get("prefers_best") else 1.2) + 2.0 * qsens
        quality *= relative ** sharpness

    # Specialty spikes pull a smaller audience
    specialty = 0.0
    focus = segment.get("eval_focus") or []
    for f in focus:
        # map focus names to benchmarks loosely
        key = {"coding": "humaneval", "reasoning": "gsm8k", "safety": "safetybench"}.get(f, f)
        if key in evals and evals[key] > avg + 8:
            specialty += 0.15

    # A reference-price elasticity curve gives discount models an advantage and
    # prevents extreme prices from increasing revenue without bound.
    price_sensitivity = float(segment.get("price_sensitivity", 1.0))
    # Even low-sensitivity enterprise buyers have a finite budget; keeping the
    # exponent above 1 gives every segment a real revenue-maximising price.
    price_factor = (1.0 + price / 6.0) ** (-(1.1 + 1.2 * price_sensitivity))
    novelty = 1.0 + float(segment.get("novelty_bias", 0.3)) * (0.3 if model.get("preview") else 0.1)
    if model.get("is_new"):
        novelty += 0.2 * float(segment.get("novelty_bias", 0.3))

    gov = 1.0 + float(segment.get("gov_relation_factor", 0.0)) * (
        company_tendencies.get("gov_relation", 0) / 100.0
    )

    rep_mult = 0.5 + company_tendencies.get("public_rep", 20) / 100.0
    type_aff = float(model.get("segment_affinity", {}).get(segment["id"], 1.0))

    pay = float(segment.get("pay_willingness", 0.2))
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
    users: float,
    price_output: float,
    usage_tokens_m: float = 0.05,
    price_input: float = 2.0,
    output_token_share: float = 0.7,
) -> float:
    """Monthly API revenue from actual active users and their token usage."""
    output_share = clamp(output_token_share, 0.0, 1.0)
    blended_price = price_output * output_share + price_input * (1.0 - output_share)
    return max(0.0, users) * max(0.0, usage_tokens_m) * max(0.0, blended_price) * 30
