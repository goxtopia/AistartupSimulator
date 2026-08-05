"""Smoke tests for the game engine."""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.engine.game import GameContext, GameEngine
from backend.app.engine.calculators.scores import (
    clamp,
    compute_hidden_score,
    parameter_compute_units,
    parameter_scaling_factor,
    segment_demand,
)


def _new():
    e = GameEngine()
    st = e.new_game(
        {
            "company_name": "UnitLab",
            "country": "usa",
            "founder_name": "Ada",
            "founder_gender": "female",
            "founder_background": "industrialist",
            "logo": {"shape": "circle", "icon": "brain", "layout": "icon_center", "palette": "midnight"},
            "seed": 42,
        }
    )
    return e, st


def test_new_game_capital_and_systems():
    e, st = _new()
    assert st["day"] == 0
    assert st["company"]["capital"] > 0
    assert "hr" in st["systems"]
    assert len(st["systems"]["research"]["catalog"]["model"]) >= 5
    assert st["systems"]["compute"]["pool"]["units"] >= 1
    assert st["systems"]["hr"]["candidates"][0]["hire_cost"] > 0
    assert st["systems"]["compute"]["available"][0]["effective_unit_cost"] >= 0
    assert st["systems"]["research"]["catalog"]["model"][0]["setup_cost_estimate"] > 0


def test_hire_and_research_and_train():
    e, st = _new()
    gid = st["game_id"]
    cand = st["systems"]["hr"]["candidates"][0]["id"]
    r = e.action(gid, "hire", {"candidate_id": cand})
    assert r["ok"], r["message"]
    emp = r["data"]["employee"]["id"]
    assert r["data"]["employee"]["hidden_tags_visible"]

    r = e.action(
        gid,
        "start_research",
        {"research_id": "capacity", "category": "model", "employee_ids": [emp]},
    )
    assert r["ok"], r["message"]

    r = e.action(
        gid,
        "create_dataset",
        {
            "name": "mix",
            "use_open_source_base": True,
            "data_research_weights": {"code": 1},
            "expected_days": 5,
        },
    )
    assert r["ok"], r["message"]
    dataset_job = r["data"]["dataset"]["id"]

    # Let research accumulate a bit, then move the person onto training (GDT staff juggling)
    st_r = e.advance(gid, 4)
    cap = next(x for x in st_r["systems"]["research"]["catalog"]["model"] if x["id"] == "capacity")
    assert cap["progress_pct"] > 0 or cap["level"] > 0

    e.action(gid, "pause_research", {"research_id": "capacity"})
    r = e.action(gid, "assign_dataset", {"job_id": dataset_job, "employee_ids": [emp]})
    assert r["ok"], r["message"]
    for _ in range(20):
        built = e.advance(gid, 1)
        if any(d["name"] == "mix" for d in built["systems"]["training"]["datasets"]):
            break
    ds = next(d["id"] for d in built["systems"]["training"]["datasets"] if d["name"] == "mix")
    r = e.action(
        gid,
        "start_training",
        {
            "name": "U-1B",
            "model_type": "text",
            "params_b": 1,
            "dataset_id": ds,
            "from_scratch": True,
            "expected_days": 8,
            "employee_ids": [emp],
        },
    )
    assert r["ok"], r["message"]
    assert r["data"]["job"]["progress"] == 0

    st_mid = e.advance(gid, 3)
    active = st_mid["systems"]["training"]["active"]
    if active:
        assert active[0]["progress_pct"] > 0
        r = e.action(gid, "assign_training", {"job_id": active[0]["id"], "employee_ids": [emp]})
        assert r["ok"], r["message"]

    st2 = e.advance(gid, 25)
    assert st2["day"] >= 20
    models = st2["systems"]["training"]["models"]
    assert len(models) >= 1
    assert models[0]["hidden_score"] > 0
    assert "average" in models[0]["eval_scores"]

    # paused research progress retained
    cap2 = next(x for x in st2["systems"]["research"]["catalog"]["model"] if x["id"] == "capacity")
    assert cap2["level"] > 0 or cap2["progress_pct"] > 0

    r = e.action(
        gid,
        "release_model",
        {"model_id": models[0]["id"], "open_source": True, "api_enabled": True},
    )
    assert r["ok"], r["message"]


def test_save_load():
    e, st = _new()
    gid = st["game_id"]
    e.advance(gid, 3)
    e.save(gid, "pytest_slot", "pytest")
    st2 = e.load("pytest_slot")
    assert st2["day"] == 3
    assert st2["company"]["name"] == "UnitLab"
    e.delete_save("pytest_slot")


def test_hidden_score_monotonic_capacity():
    cfg = {
        "capacity": {"effects": {"hidden_score_base": 10}},
        "performance": {"effects": {"hidden_score_mult": 0.08}},
    }
    a = compute_hidden_score(
        capacity_level=1, research_levels={"performance": 0}, research_cfg=cfg, params_b=7
    )
    b = compute_hidden_score(
        capacity_level=5, research_levels={"performance": 3}, research_cfg=cfg, params_b=7
    )
    assert b > a
    assert 1 <= a <= 200

    uncapped = compute_hidden_score(
        capacity_level=10,
        research_levels={"performance": 10},
        research_cfg=cfg,
        params_b=400,
        data_quality=1.2,
    )
    assert uncapped > 200


def test_parameter_scaling_is_strong_monotonic_and_boundary_diminishing():
    params = [1, 3, 7, 13, 34, 70, 180, 400, 1000]
    factors = [parameter_scaling_factor(value) for value in params]
    assert all(right > left for left, right in zip(factors, factors[1:]))
    assert factors[5] / factors[2] > 1.4  # 70B materially outscales 7B
    small_gain_per_b = (parameter_scaling_factor(7) - parameter_scaling_factor(1)) / 6
    medium_gain_per_b = (parameter_scaling_factor(70) - parameter_scaling_factor(7)) / 63
    large_gain_per_b = (parameter_scaling_factor(400) - parameter_scaling_factor(70)) / 330
    assert small_gain_per_b > medium_gain_per_b > large_gain_per_b
    assert parameter_scaling_factor(1000) < 2.8

    cfg = {"capacity": {"effects": {"hidden_score_base": 10}}}
    score_7b = compute_hidden_score(
        capacity_level=1, research_levels={}, research_cfg=cfg, params_b=7
    )
    score_70b = compute_hidden_score(
        capacity_level=1, research_levels={}, research_cfg=cfg, params_b=70
    )
    assert score_70b > score_7b * 1.4
    assert parameter_compute_units(70, [{"params_b": 70, "compute_units": 800}]) == 800


def test_parameter_count_drives_training_cost_and_compute_without_research_gate():
    small_engine, small_state = _new()
    small = small_engine.action(
        small_state["game_id"],
        "start_training",
        {
            "name": "Small-1B",
            "model_type": "text",
            "params_b": 1,
            "dataset_id": "ds_open_base",
            "from_scratch": True,
            "expected_days": 30,
            "employee_ids": [],
        },
    )
    assert small["ok"], small["message"]
    small_job = small["data"]["job"]

    large_engine, large_state = _new()
    gid = large_state["game_id"]
    large = large_engine.action(
        gid,
        "start_training",
        {
            "name": "Large-70B",
            "model_type": "text",
            "params_b": 70,
            "dataset_id": "ds_open_base",
            "from_scratch": True,
            "expected_days": 30,
            "employee_ids": [],
        },
    )
    assert large["ok"], large["message"]
    large_job = large["data"]["job"]
    assert "required_capacity_level" not in large_job
    assert large_job["upfront_cost"] > small_job["upfront_cost"] * 10
    assert large_job["daily_cost"] > small_job["daily_cost"] * 5
    assert large_job["compute_required_tf"] > small_job["compute_required_tf"] * 50


def test_china_has_ascend():
    e, st = _new()
    st_cn = e.new_game(
        {
            "company_name": "CN",
            "country": "china",
            "founder_name": "Li",
            "founder_gender": "male",
            "founder_background": "industrialist",
            "logo": {},
            "seed": 1,
        }
    )
    ids = {c["id"] for c in st_cn["systems"]["compute"]["available"]}
    assert any("ascend" in i for i in ids)


def test_research_accumulates_and_levels():
    e, st = _new()
    gid = st["game_id"]
    cand = st["systems"]["hr"]["candidates"][0]["id"]
    emp = e.action(gid, "hire", {"candidate_id": cand})["data"]["employee"]["id"]
    r = e.action(
        gid,
        "start_research",
        {"research_id": "performance", "category": "model", "employee_ids": [emp]},
    )
    assert r["ok"], r["message"]
    st1 = e.advance(gid, 5)
    perf = next(x for x in st1["systems"]["research"]["catalog"]["model"] if x["id"] == "performance")
    assert perf["focused"]
    assert perf["progress_pct"] > 0 or perf["level"] > 0
    saved = (perf["level"], perf["progress_pct"])
    r = e.action(gid, "pause_research", {"research_id": "performance"})
    assert r["ok"]
    st2 = e.advance(gid, 5)
    perf2 = next(x for x in st2["systems"]["research"]["catalog"]["model"] if x["id"] == "performance")
    assert perf2["level"] == saved[0]
    assert abs(perf2["progress_pct"] - saved[1]) < 1.0


def test_research_staff_cap_is_shared_by_category():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    raw["employees"] = [
        {
            "id": f"researcher_{index}",
            "name": f"Researcher {index}",
            "role": "scientist",
            "role_name": "研究员",
            "seniority": "mid",
            "seniority_name": "中级",
            "salary": 10000,
            "skills": {"ml_theory": 50, "systems": 50, "data_eng": 50, "cuda": 50},
            "skill_focus": ["ml_theory", "systems"],
            "morale": 80,
            "fatigue": 0,
            "hidden_tags": [],
            "assigned_to": None,
        }
        for index in range(42)
    ]

    first = e.action(
        gid,
        "start_research",
        {
            "research_id": "capacity",
            "category": "model",
            "employee_ids": [f"researcher_{index}" for index in range(12)],
        },
    )
    assert first["ok"], first["message"]
    second = e.action(
        gid,
        "start_research",
        {
            "research_id": "performance",
            "category": "model",
            "employee_ids": [f"researcher_{index}" for index in range(12, 20)],
        },
    )
    assert second["ok"], second["message"]

    overflow = e.action(
        gid,
        "start_research",
        {
            "research_id": "speed",
            "category": "model",
            "employee_ids": ["researcher_41"],
        },
    )
    assert not overflow["ok"]
    assert "总上限为 20 人" in overflow["message"]

    data_result = e.action(
        gid,
        "start_research",
        {
            "research_id": "frontier_science",
            "category": "data",
            "employee_ids": [f"researcher_{index}" for index in range(20, 40)],
        },
    )
    assert data_result["ok"], data_result["message"]
    compute_result = e.action(
        gid,
        "start_research",
        {
            "research_id": "kernel_opt",
            "category": "compute",
            "employee_ids": ["researcher_40"],
        },
    )
    assert compute_result["ok"], compute_result["message"]

    category_staff = compute_result["state"]["systems"]["research"]["category_staff"]
    assert category_staff["model"] == {"used": 20, "cap": 20, "remaining": 0}
    assert category_staff["data"] == {"used": 20, "cap": 20, "remaining": 0}
    assert category_staff["compute"]["used"] == 1


def test_auto_research_rebalances_and_reserves_trainer():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]

    def employee(employee_id, skills, assigned_to=None):
        return {
            "id": employee_id,
            "name": employee_id.title(),
            "role": "scientist",
            "role_name": "研究员",
            "seniority": "senior",
            "seniority_name": "高级",
            "salary": 12000,
            "skills": skills,
            "skill_focus": list(skills)[:2],
            "morale": 85,
            "fatigue": 0,
            "hidden_tags": [],
            "assigned_to": assigned_to,
        }

    raw["employees"] = [
        employee("trainer", {"ml_theory": 96, "systems": 92, "data_eng": 88, "rl": 75, "alignment": 72}),
        employee("architect", {"ml_theory": 82, "architecture": 96, "systems": 40}),
        employee("systems", {"ml_theory": 32, "architecture": 62, "systems": 94}),
        employee("generalist", {"ml_theory": 36, "architecture": 34, "systems": 35}),
        employee("dataset_busy", {"ml_theory": 99, "systems": 99}, "dataset:external"),
    ]

    capacity = e.action(
        gid,
        "set_research_auto",
        {"research_id": "capacity", "category": "model", "enabled": True},
    )
    assert capacity["ok"], capacity["message"]
    automation = capacity["state"]["systems"]["research"]["automation"]
    assert automation["reserved_employee"]["id"] == "trainer"
    assert next(item for item in raw["employees"] if item["id"] == "trainer")["assigned_to"] is None
    assert next(item for item in raw["employees"] if item["id"] == "dataset_busy")["assigned_to"] == "dataset:external"

    performance = e.action(
        gid,
        "set_research_auto",
        {"research_id": "performance", "category": "model", "enabled": True},
    )
    assert performance["ok"], performance["message"]
    architect = next(item for item in raw["employees"] if item["id"] == "architect")
    assert architect["assigned_to"] == "research:performance"

    train = e.action(
        gid,
        "start_training",
        {
            "name": "AutoReserve-1B",
            "model_type": "text",
            "params_b": 1,
            "dataset_id": "ds_open_base",
            "from_scratch": True,
            "expected_days": 5,
            "employee_ids": ["trainer"],
        },
    )
    assert train["ok"], train["message"]
    progressed = e.advance(gid, 1)
    automation = progressed["systems"]["research"]["automation"]
    assert automation["reserved_employee"]
    assert automation["reserved_employee"]["id"] != "trainer"
    newly_reserved = next(
        item for item in raw["employees"] if item["id"] == automation["reserved_employee"]["id"]
    )
    assert newly_reserved["assigned_to"] is None
    assert next(item for item in raw["employees"] if item["id"] == "trainer")["assigned_to"].startswith("train:")

    manual = e.action(
        gid,
        "assign_research",
        {"research_id": "capacity", "category": "model", "employee_ids": []},
    )
    assert manual["ok"], manual["message"]
    capacity_public = next(
        item
        for item in manual["state"]["systems"]["research"]["catalog"]["model"]
        if item["id"] == "capacity"
    )
    assert not capacity_public["auto_enabled"]


def test_ai_rivals_exist_and_act():
    e, st = _new()
    ai = st["systems"]["competitors"]
    assert len(ai["rivals"]) >= 5
    assert ai["rivals"][0].get("strategy_name")
    assert ai["rivals"][0].get("flagship")
    gid = st["game_id"]
    # hire bait
    for c in st["systems"]["hr"]["candidates"][:2]:
        e.action(gid, "hire", {"candidate_id": c["id"]})
    st2 = e.advance(gid, 40)
    ai2 = st2["systems"]["competitors"]
    assert len(ai2["models"]) >= len(ai["models"])
    # player can attempt poach
    target = ai2["rivals"][0]["id"]
    r = e.action(gid, "poach", {"target_company_id": target, "offer_multiplier": 2.0})
    assert "message" in r


def test_market_leaderboard_api_and_contract_income():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    model = {
        "id": "mdl_contract_test",
        "name": "Contract-70B",
        "model_type": "text",
        "params_b": 70,
        "hidden_score": 95,
        "eval_scores": {"average": 74, "safetybench": 72},
        "released": True,
        "api_enabled": True,
        "open_source": False,
        "price_input": 2.0,
        "price_output": 6.0,
        "released_day": 0,
        "segment_affinity": {},
    }
    raw["models"].append(model)
    raw["company"]["tendencies"]["gov_relation"] = 60
    r = e.action(
        gid,
        "sign_contract",
        {"offer_id": "public_digital_service", "model_id": model["id"], "duration_years": 2},
    )
    assert r["ok"], r["message"]
    before = raw["company"]["capital"]
    st2 = e.advance(gid, 1)
    market = st2["systems"]["market"]
    assert market["api_daily_revenue"] > 0
    assert market["contract_daily_revenue"] > 0
    assert raw["company"]["capital"] > before
    own_row = next(x for x in market["model_leaderboard"] if x["id"] == model["id"])
    assert own_row["is_player"]
    assert own_row["rank"] >= 1
    assert len(market["model_leaderboards"]["closed"]) <= 20
    assert len(market["model_leaderboards"]["open"]) <= 20
    assert all(not row["open_source"] for row in market["model_leaderboards"]["closed"])
    assert all(row["open_source"] for row in market["model_leaderboards"]["open"])


def test_auto_api_pricing_optimizes_revenue_and_manual_price_takes_over():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    model = {
        "id": "mdl_auto_price",
        "name": "AutoPrice-7B",
        "model_type": "text",
        "params_b": 7,
        "hidden_score": 90,
        "eval_scores": {"mmlu": 75, "gsm8k": 73, "average": 74},
        "released": True,
        "api_enabled": True,
        "open_source": False,
        "price_input": 30.0,
        "price_output": 80.0,
        "released_day": 0,
        "segment_affinity": {},
    }
    raw["models"].append(model)
    market_system = e.systems.get("market")
    before = market_system._estimate_model_api_revenue(
        raw, GameContext(e), model, model["price_input"], model["price_output"]
    )

    enabled = e.action(gid, "set_auto_price", {"model_id": model["id"], "enabled": True})
    assert enabled["ok"], enabled["message"]
    priced = next(
        item
        for item in enabled["state"]["systems"]["training"]["models"]
        if item["id"] == model["id"]
    )
    assert priced["auto_price_enabled"]
    assert priced["auto_price_status"] == "active"
    assert priced["price_output"] < 80
    assert priced["auto_price_estimated_daily_revenue"] > before
    assert priced["auto_price_target_output"] > priced["auto_price_target_input"]

    segment = {**e.configs.load("market")["api_segments"]["consumer"], "id": "consumer"}
    low_input = segment_demand(
        segment=segment,
        model={**model, "price_input": 1, "price_output": 6},
        company_tendencies={"public_rep": 50},
        country_bias=1.0,
        best_eval_in_market=74,
    )
    high_input = segment_demand(
        segment=segment,
        model={**model, "price_input": 50, "price_output": 6},
        company_tendencies={"public_rep": 50},
        country_bias=1.0,
        best_eval_in_market=74,
    )
    assert high_input < low_input

    manual = e.action(
        gid,
        "set_api_price",
        {"model_id": model["id"], "price_input": 2.5, "price_output": 7.5},
    )
    assert manual["ok"], manual["message"]
    manual_model = next(
        item
        for item in manual["state"]["systems"]["training"]["models"]
        if item["id"] == model["id"]
    )
    assert not manual_model["auto_price_enabled"]
    assert manual_model["auto_price_status"] == "manual"


def test_successful_rival_poach_pays_breach_fee():
    class SuccessRng:
        def random(self):
            return 0.0

        def uniform(self, low, high):
            return (low + high) / 2

        def choice(self, values):
            return values[0]

        def randint(self, low, high):
            return low

    e, st = _new()
    gid = st["game_id"]
    candidate = st["systems"]["hr"]["candidates"][0]["id"]
    hired = e.action(gid, "hire", {"candidate_id": candidate})["data"]["employee"]
    raw = e.sessions[gid]
    raw["day"] = 30
    rival = raw["competitors"][0]
    rival["poach_cooldown"] = 0
    strategy = e.configs.load("competitors")["strategies"][rival["strategy"]]
    before = raw["company"]["capital"]
    e.rng = SuccessRng()
    system = e.systems.get("competitors")
    event = system._try_poach_player(rival, strategy, raw, GameContext(e))
    assert event and event["type"] == "poach_success"
    assert event["employee_id"] == hired["id"]
    assert event["breach_fee"] > 0
    assert raw["company"]["capital"] == before + event["breach_fee"]


def test_chief_scientist_multiplies_team_skills_and_is_poach_immune():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    chief = {
        "id": "chief_scientist",
        "name": "Dr. Chief",
        "role": "researcher",
        "role_name": "研究科学家",
        "seniority": "principal",
        "seniority_name": "首席",
        "salary": 24000,
        "skills": {
            "ml_theory": 90,
            "systems": 80,
            "data_eng": 70,
            "rl": 60,
            "alignment": 40,
            "product": 30,
        },
        "skill_focus": ["ml_theory", "systems"],
        "morale": 90,
        "satisfaction": 80,
        "fatigue": 0,
        "hidden_tags": [],
        "assigned_to": None,
    }
    teammate = {
        **chief,
        "id": "team_researcher",
        "name": "Team Researcher",
        "seniority": "senior",
        "seniority_name": "高级",
        "skills": {
            "ml_theory": 50,
            "systems": 45,
            "data_eng": 40,
            "rl": 35,
            "alignment": 30,
            "product": 25,
        },
    }
    raw["employees"] = [chief, teammate]

    appointed = e.action(gid, "set_chief_scientist", {"employee_id": chief["id"]})
    assert appointed["ok"], appointed["message"]
    profile = appointed["state"]["systems"]["hr"]["chief_scientist"]
    assert profile["employee_id"] == chief["id"]
    assert profile["poach_immune"]
    assert profile["ability"] == 75.0
    assert profile["team_skill_multiplier"] == 1.188
    public_teammate = next(
        employee
        for employee in appointed["state"]["systems"]["hr"]["employees"]
        if employee["id"] == teammate["id"]
    )
    assert public_teammate["effective_skills"]["ml_theory"] > teammate["skills"]["ml_theory"]

    research = e.systems.get("research")
    boosted_speed = research._team_speed(
        raw, "performance", "model", [teammate["id"]], GameContext(e)
    )
    raw["hr"]["chief_scientist_id"] = None
    base_speed = research._team_speed(
        raw, "performance", "model", [teammate["id"]], GameContext(e)
    )
    assert boosted_speed > base_speed * 1.15

    raw["hr"]["chief_scientist_id"] = chief["id"]
    raw["employees"] = [chief]
    raw["day"] = 30
    raw["competitor_ai"]["last_poach_day"] = -999
    rival = raw["competitors"][0]
    rival["poach_cooldown"] = 0
    strategy = e.configs.load("competitors")["strategies"][rival["strategy"]]
    event = e.systems.get("competitors")._try_poach_player(
        rival, strategy, raw, GameContext(e)
    )
    assert event is None
    assert raw["employees"] == [chief]

    fired = e.action(gid, "fire", {"employee_id": chief["id"]})
    assert fired["ok"], fired["message"]
    assert fired["state"]["systems"]["hr"]["chief_scientist"] is None


def test_auto_hire_prioritizes_unstaffed_auto_research_by_roi():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    raw["company"]["capital"] = 1_000_000
    existing = {
        "id": "existing_data",
        "name": "Existing Data",
        "role": "engineer",
        "role_name": "数据工程师",
        "seniority": "mid",
        "seniority_name": "中级",
        "salary": 10000,
        "skills": {"data_eng": 70, "systems": 65, "ml_theory": 20, "architecture": 10},
        "skill_focus": ["data_eng", "systems"],
        "preferences": {},
        "hidden_tags": [],
        "hidden_tags_visible": [],
        "morale": 75,
        "satisfaction": 60,
        "fatigue": 0,
        "assigned_to": "research:code",
    }
    raw["employees"] = [existing]
    performance = raw["research"]["levels"]["performance"]
    performance.update({"auto_enabled": True, "category": "model", "employee_ids": []})
    code = raw["research"]["levels"]["code"]
    code.update({"auto_enabled": True, "category": "data", "employee_ids": [existing["id"]]})

    def candidate(candidate_id: str, name: str, skills: dict, salary: float) -> dict:
        return {
            "id": candidate_id,
            "name": name,
            "role": "researcher",
            "role_name": "研究员",
            "seniority": "senior",
            "seniority_name": "高级",
            "salary": salary,
            "signing_bonus": salary,
            "skills": skills,
            "skill_focus": list(skills)[:2],
            "preferences": {},
            "hidden_tags": [],
            "hidden_tags_visible": [],
            "morale": 75,
            "satisfaction": 50,
            "fatigue": 0,
            "assigned_to": None,
        }

    architecture_candidate = candidate(
        "architecture_candidate",
        "Architecture Scientist",
        {"ml_theory": 88, "architecture": 92, "data_eng": 15, "systems": 18},
        18000,
    )
    cheaper_data_candidate = candidate(
        "data_candidate",
        "Cheap Data Engineer",
        {"ml_theory": 10, "architecture": 8, "data_eng": 98, "systems": 96},
        6000,
    )
    raw["hr"]["candidates"] = [cheaper_data_candidate, architecture_candidate]

    enabled = e.action(gid, "set_auto_hire", {"enabled": True})
    assert enabled["ok"], enabled["message"]
    automation = enabled["state"]["systems"]["hr"]["auto_hire"]
    assert automation["enabled"]
    assert automation["max_hires_per_cycle"] == 3
    assert automation["hires_this_cycle"] == 2
    assert automation["last_cycle_hires"][0]["research_id"] == "performance"
    assert automation["last_cycle_hires"][0]["employee_id"] == architecture_candidate["id"]
    assert automation["last_cycle_hires"][1]["research_id"] == "code"
    assert automation["last_cycle_hires"][1]["employee_id"] == cheaper_data_candidate["id"]
    assert automation["hires_completed"] == 2
    assert any(item["id"] == architecture_candidate["id"] for item in raw["employees"])
    assert any(item["id"] == cheaper_data_candidate["id"] for item in raw["employees"])

    updated = e.action(
        gid,
        "set_auto_hire",
        {"enabled": True, "max_hires_per_cycle": 7},
    )
    assert updated["ok"], updated["message"]
    assert updated["state"]["systems"]["hr"]["auto_hire"]["max_hires_per_cycle"] == 7


def test_voluntary_leave_pays_no_severance_and_clears_assignments():
    e, st = _new()
    gid = st["game_id"]
    candidate_id = st["systems"]["hr"]["candidates"][0]["id"]
    hired = e.action(gid, "hire", {"candidate_id": candidate_id})["data"]["employee"]
    raw = e.sessions[gid]
    raw["research"]["levels"]["performance"]["employee_ids"] = [hired["id"]]
    raw["research"]["active"] = [
        {"research_id": "performance", "employee_ids": [hired["id"]]}
    ]
    employee = next(item for item in raw["employees"] if item["id"] == hired["id"])
    employee["assigned_to"] = "research:performance"
    before = raw["company"]["capital"]

    messages = e.effects.apply(raw, {"risk_employee_leave": 1.0}, GameContext(e))

    assert raw["company"]["capital"] == before
    assert all(item["id"] != hired["id"] for item in raw["employees"])
    assert hired["id"] not in raw["research"]["levels"]["performance"]["employee_ids"]
    assert hired["id"] not in raw["research"]["active"][0]["employee_ids"]
    assert messages and "不支付离职补偿" in messages[0]


def test_loan_financing_repayment_and_early_payoff():
    e, st = _new()
    gid = st["game_id"]
    finance = st["systems"]["finance"]
    assert finance["credit_score"] > 0
    bridge = next(p for p in finance["products"] if p["id"] == "startup_bridge")
    assert bridge["eligible"]
    assert bridge["available_amount"] >= 50000

    e.advance(gid, 7)
    before = e.sessions[gid]["company"]["capital"]
    result = e.action(gid, "borrow", {"product_id": "startup_bridge", "amount": 50000})
    assert result["ok"], result["message"]
    loan = result["data"]["loan"]
    assert e.sessions[gid]["company"]["capital"] == before + 49000
    assert result["state"]["systems"]["finance"]["total_balance"] == 50000

    before_due = e.advance(gid, 29)
    assert not before_due["systems"]["finance"]["payment_log"]
    after_month = e.advance(gid, 1)
    finance_after = after_month["systems"]["finance"]
    assert len(finance_after["payment_log"]) == 1
    assert finance_after["total_balance"] < 50000

    payoff = e.action(gid, "repay_loan_early", {"loan_id": loan["id"]})
    assert payoff["ok"], payoff["message"]
    assert not payoff["state"]["systems"]["finance"]["active_loans"]
    assert payoff["state"]["systems"]["finance"]["completed_loans"]


def test_financial_statement_includes_payroll_interest_and_active_projects():
    e, st = _new()
    raw = e.sessions[st["game_id"]]
    raw["market"]["api_daily_revenue"] = 1000
    raw["market"]["contract_daily_revenue"] = 500
    raw["employees"] = [
        {"id": "e1", "salary": 10000},
        {"id": "e2", "salary": 20000},
    ]
    raw["compute"]["cloud"] = {"nvidia_4090": 2}
    raw["research"]["levels"]["capacity"].update(
        {"category": "model", "level": 0, "employee_ids": ["e1", "e2"], "paused": False}
    )
    raw["training"]["active"] = [
        {"daily_cost_base": 100, "employee_ids": ["e1", "e2"], "paused": False}
    ]
    raw["training"]["dataset_jobs"] = [
        {"daily_cost_base": 50, "employee_ids": ["e1"], "paused": False}
    ]
    raw["finance"]["active_loans"] = [
        {"balance": 120000, "apr": 0.12, "monthly_payment": 11200}
    ]

    finance = e.systems.get("finance").serialize_public(raw, GameContext(e))
    statement = finance["financial_statement"]

    assert statement["income"] == {"api": 30000.0, "contracts": 15000.0, "total": 45000.0}
    assert statement["expenses"]["payroll"] == 30000.0
    assert statement["expenses"]["cloud_compute"] == 600.0
    assert statement["expenses"]["research"] == 16200.0
    assert statement["expenses"]["model_training"] == 2580.0
    assert statement["expenses"]["dataset_building"] == 1350.0
    assert statement["expenses"]["debt_interest"] == 1200.0
    assert statement["expenses"]["total"] == 51930.0
    assert statement["monthly_net_income"] == -6930.0
    assert statement["monthly_debt_principal"] == 10000.0
    assert statement["monthly_net_cash_flow"] == -16930.0


def test_equity_and_revenue_share_funding_tools_have_distinct_costs():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    finance_system = e.systems.get("finance")

    before_equity = raw["company"]["capital"]
    equity = e.action(gid, "use_funding_tool", {"tool_id": "seed_equity"})
    assert equity["ok"], equity["message"]
    assert raw["company"]["capital"] == before_equity + 750000
    assert equity["state"]["systems"]["finance"]["founder_ownership"] == 0.9
    duplicate = e.action(gid, "use_funding_tool", {"tool_id": "seed_equity"})
    assert not duplicate["ok"]

    raw["day"] = 30
    raw["market"]["api_daily_revenue"] = 1000
    raw["market"]["contract_daily_revenue"] = 0
    raw["market"]["daily_revenue"] = 1000
    revenue_funding = e.action(gid, "use_funding_tool", {"tool_id": "revenue_advance"})
    assert revenue_funding["ok"], revenue_funding["message"]
    agreement = raw["finance"]["active_revenue_financing"][0]
    assert agreement["remaining"] == 810000

    before_payment = raw["company"]["capital"]
    raw["day"] = 31
    events = finance_system.on_tick(raw, GameContext(e), days=1)
    assert raw["company"]["capital"] == before_payment - 120
    assert agreement["remaining"] == 809880
    assert not events

    statement = finance_system.serialize_public(raw, GameContext(e))["financial_statement"]
    assert statement["monthly_revenue_financing_payment"] == 3600.0
    assert statement["expenses"]["revenue_financing_cost"] > 0
    assert statement["monthly_financing_principal"] > statement["monthly_debt_principal"]


def test_model_improvement_creates_derived_versions():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    base = {
        "id": "mdl_lifecycle_base",
        "name": "Lifecycle-7B",
        "model_type": "text",
        "params_b": 7,
        "dataset_id": "ds_open_base",
        "hidden_score": 61.0,
        "eval_scores": {
            "mmlu": 55.0,
            "gsm8k": 52.0,
            "humaneval": 49.0,
            "safetybench": 58.0,
            "average": 53.5,
        },
        "released": True,
        "open_source": False,
        "preview": False,
        "api_enabled": True,
        "price_input": 2.0,
        "price_output": 6.0,
        "created_day": 0,
        "released_day": 0,
        "segment_affinity": {},
        "source": "own",
        "generation": 1,
        "root_model_id": None,
        "parent_model_id": None,
        "lineage": [],
        "operations": [],
    }
    raw["models"].append(base)

    result = e.action(
        gid,
        "improve_model",
        {
            "model_id": base["id"],
            "method": "fine_tune",
            "name": "Lifecycle-7B-FT-v2",
            "dataset_id": "ds_open_base",
            "expected_days": 5,
            "employee_ids": [],
        },
    )
    assert result["ok"], result["message"]
    job = result["data"]["job"]
    assert job["improvement"]["source_model_id"] == base["id"]
    assert job["improvement"]["method"] == "fine_tune"

    for _ in range(60):
        progressed = e.advance(gid, 1)
        derived = [
            model
            for model in progressed["systems"]["training"]["models"]
            if model.get("parent_model_id") == base["id"]
        ]
        if derived:
            break
    assert derived
    version = derived[0]
    assert version["generation"] == 2
    assert version["root_model_id"] == base["id"]
    assert version["improvement_method"] == "fine_tune"
    assert version["hidden_score"] > base["hidden_score"]
    assert not version["released"]
    assert version["lineage"][-1]["id"] == base["id"]
    history = progressed["systems"]["training"]["history"]
    assert history[-1]["model_id"] == version["id"]
    assert history[-1]["method"] == "fine_tune"

    distill = e.action(
        gid,
        "improve_model",
        {
            "model_id": base["id"],
            "method": "distill",
            "teacher_model_id": "open_herd_70b",
            "teacher_source": "open",
            "expected_days": 5,
            "employee_ids": [],
        },
    )
    assert distill["ok"], distill["message"]
    assert distill["data"]["job"]["improvement"]["teacher_source"] == "open"
    rl = e.action(
        gid,
        "improve_model",
        {
            "model_id": version["id"],
            "method": "rl",
            "expected_days": 5,
            "employee_ids": [],
        },
    )
    assert rl["ok"], rl["message"]

    for _ in range(70):
        progressed = e.advance(gid, 1)
        methods = {
            model.get("improvement_method")
            for model in progressed["systems"]["training"]["models"]
        }
        if {"fine_tune", "distill", "rl"}.issubset(methods):
            break
    assert {"fine_tune", "distill", "rl"}.issubset(methods)


def test_more_compute_materially_accelerates_training():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    raw["research"]["levels"]["capacity"]["level"] = 6
    raw["employees"] = [
        {
            "id": "compute_trainer",
            "name": "Compute Trainer",
            "role": "engineer",
            "role_name": "训练工程师",
            "seniority": "senior",
            "seniority_name": "高级",
            "salary": 15000,
            "skills": {"ml_theory": 75, "systems": 82},
            "skill_focus": ["ml_theory", "systems"],
            "morale": 85,
            "fatigue": 0,
            "hidden_tags": [],
            "assigned_to": None,
        }
    ]
    started = e.action(
        gid,
        "start_training",
        {
            "name": "Compute-Bound-70B",
            "model_type": "text",
            "params_b": 70,
            "dataset_id": "ds_open_base",
            "from_scratch": True,
            "expected_days": 30,
            "employee_ids": ["compute_trainer"],
        },
    )
    assert started["ok"], started["message"]
    before_job = started["state"]["systems"]["training"]["active"][0]
    assert before_job["compute_profile"]["status"] == "严重瓶颈"

    purchased = e.action(
        gid,
        "purchase_compute",
        {"chip_id": "nvidia_h100", "quantity": 2, "mode": "buy"},
    )
    assert purchased["ok"], purchased["message"]
    after_job = purchased["state"]["systems"]["training"]["active"][0]
    assert after_job["compute_profile"]["allocated_tf"] > before_job["compute_profile"]["allocated_tf"]
    assert after_job["compute_profile"]["speed_mult"] > before_job["compute_profile"]["speed_mult"] * 3
    assert after_job["speed_per_day"] > before_job["speed_per_day"] * 3
    assert after_job["eta_days"] < before_job["eta_days"]


def test_standalone_closed_competitor_distillation():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    raw["research"]["levels"]["capacity"]["level"] = 2
    teacher = next(
        model
        for model in raw["competitor_models"]
        if model.get("source") == "closed_competitor" and model.get("model_type") == "text"
    )
    before = raw["company"]["capital"]
    result = e.action(
        gid,
        "distill",
        {
            "name": "Closed-Teacher-Distill-7B",
            "teacher_model_id": teacher["id"],
            # Deliberately spoof the source; backend must charge the closed fee.
            "teacher_source": "own",
            "params_b": 7,
            "dataset_id": "ds_open_base",
            "expected_days": 3,
            "employee_ids": [],
            "model_type": "text",
        },
    )
    assert result["ok"], result["message"]
    job = result["data"]["job"]
    assert job["distill"]["teacher_source"] == "closed_competitor"
    assert job["distill"]["teacher_model_name"] == teacher["name"]
    assert before - raw["company"]["capital"] >= teacher["hidden_score"] * 1000

    for _ in range(50):
        progressed = e.advance(gid, 1)
        distilled = [
            model
            for model in progressed["systems"]["training"]["models"]
            if model["name"] == "Closed-Teacher-Distill-7B"
        ]
        if distilled:
            break
    assert distilled
    assert distilled[0]["distilled"]
    assert distilled[0]["base_label"] == teacher["name"]
    release = e.action(
        gid,
        "release_model",
        {
            "model_id": distilled[0]["id"],
            "open_source": False,
            "api_enabled": True,
        },
    )
    assert release["ok"], release["message"]
    released_model = next(
        model
        for model in release["state"]["systems"]["training"]["models"]
        if model["id"] == distilled[0]["id"]
    )
    assert released_model["released"] and not released_model["open_source"]


def test_auto_distill_chains_latest_until_ninety_percent_target():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    # Keep this test focused on automation rather than the independent poaching simulation.
    raw["competitor_ai"]["last_poach_day"] = 10**9
    base = {
        "id": "mdl_auto_distill_base",
        "name": "AutoSeed-1B",
        "model_type": "text",
        "params_b": 1,
        "dataset_id": "ds_open_base",
        "hidden_score": 50.0,
        "eval_scores": {"mmlu": 45.0, "gsm8k": 43.0, "average": 44.0},
        "released": False,
        "open_source": False,
        "preview": False,
        "api_enabled": False,
        "price_input": 2.0,
        "price_output": 6.0,
        "created_day": 0,
        "segment_affinity": {},
        "source": "own",
        "generation": 1,
        "root_model_id": None,
        "parent_model_id": None,
        "lineage": [],
        "operations": [],
    }
    raw["models"].append(base)
    raw["employees"] = [
        {
            "id": "auto_distiller",
            "name": "Auto Distiller",
            "role": "engineer",
            "role_name": "训练工程师",
            "seniority": "senior",
            "seniority_name": "高级",
            "salary": 14000,
            "skills": {"ml_theory": 88, "systems": 90, "data_eng": 70},
            "skill_focus": ["ml_theory", "systems"],
            "morale": 88,
            "fatigue": 0,
            "hidden_tags": [],
            "assigned_to": None,
        }
    ]

    enabled = e.action(
        gid,
        "set_auto_distill",
        {"model_id": base["id"], "enabled": True, "mode": "open"},
    )
    assert enabled["ok"], enabled["message"]
    automation = enabled["state"]["systems"]["training"]["auto_distill"][0]
    assert automation["status"] == "running"
    assert automation["teacher_source"] == "open"
    assert automation["employee_id"] == "auto_distiller"

    disabled = e.action(
        gid,
        "set_auto_distill",
        {"model_id": base["id"], "enabled": False, "mode": "open"},
    )
    assert disabled["ok"], disabled["message"]
    automation = disabled["state"]["systems"]["training"]["auto_distill"][0]
    assert not automation["enabled"]
    assert automation["status"] == "stopping"
    for _ in range(30):
        stopped_state = e.advance(gid, 1)
        automation = stopped_state["systems"]["training"]["auto_distill"][0]
        if automation["status"] == "paused":
            break
    assert automation["status"] == "paused"
    assert automation["cycles_completed"] == 1
    assert not any(
        job.get("auto_distill_id")
        for job in stopped_state["systems"]["training"]["active"]
    )

    restarted = e.action(
        gid,
        "set_auto_distill",
        {"model_id": base["id"], "enabled": True, "mode": "open"},
    )
    assert restarted["ok"], restarted["message"]
    assert restarted["state"]["systems"]["training"]["auto_distill"][0]["status"] == "running"

    for _ in range(100):
        progressed = e.advance(gid, 1)
        automation = progressed["systems"]["training"]["auto_distill"][0]
        if automation["status"] == "target_reached":
            break
    assert automation["status"] == "target_reached"
    assert not automation["enabled"]
    assert automation["cycles_completed"] >= 1
    assert automation["current_model_id"] != base["id"]
    assert automation["current_score"] >= automation["threshold_score"]

    models = progressed["systems"]["training"]["models"]
    current = next(model for model in models if model["id"] == automation["current_model_id"])
    chain_length = 0
    while current.get("parent_model_id"):
        assert current["improvement_method"] == "distill"
        chain_length += 1
        current = next(model for model in models if model["id"] == current["parent_model_id"])
    assert current["id"] == base["id"]
    assert chain_length == automation["cycles_completed"]


def test_auto_rl_uses_strongest_model_best_employee_and_keeps_chaining():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    raw["company"]["capital"] = 20_000_000

    def owned_model(model_id: str, name: str, hidden: float) -> dict:
        return {
            "id": model_id,
            "name": name,
            "model_type": "text",
            "params_b": 1,
            "dataset_id": "ds_open_base",
            "hidden_score": hidden,
            "eval_scores": {"mmlu": 92.0, "gsm8k": 90.0, "average": 91.0},
            "released": False,
            "open_source": False,
            "preview": False,
            "api_enabled": False,
            "price_input": 2.0,
            "price_output": 6.0,
            "created_day": 0,
            "segment_affinity": {},
            "source": "own",
            "generation": 1,
            "root_model_id": None,
            "parent_model_id": None,
            "lineage": [],
            "operations": [],
        }

    weak = owned_model("mdl_auto_rl_weak", "Weak-1B", 80.0)
    strongest = owned_model("mdl_auto_rl_strong", "Strong-1B", 210.0)
    raw["models"].extend([weak, strongest])
    raw["employees"] = [
        {
            "id": "rl_specialist",
            "name": "RL Specialist",
            "role": "researcher",
            "role_name": "RL 研究员",
            "seniority": "senior",
            "seniority_name": "高级",
            "salary": 16000,
            "skills": {"rl": 94, "alignment": 90, "ml_theory": 72, "systems": 45},
            "skill_focus": ["rl", "alignment"],
            "morale": 90,
            "fatigue": 0,
            "hidden_tags": [],
            "assigned_to": None,
        },
        {
            "id": "general_trainer",
            "name": "General Trainer",
            "role": "engineer",
            "role_name": "训练工程师",
            "seniority": "senior",
            "seniority_name": "高级",
            "salary": 15000,
            "skills": {"rl": 25, "alignment": 28, "ml_theory": 96, "systems": 96},
            "skill_focus": ["ml_theory", "systems"],
            "morale": 90,
            "fatigue": 0,
            "hidden_tags": [],
            "assigned_to": None,
        },
    ]

    enabled = e.action(gid, "set_auto_rl", {"enabled": True})
    assert enabled["ok"], enabled["message"]
    automation = enabled["state"]["systems"]["training"]["auto_rl"]
    assert automation["enabled"] and automation["status"] == "running"
    assert automation["source_model_id"] == strongest["id"]
    assert automation["employee_id"] == "rl_specialist"
    first_job = next(
        job for job in enabled["state"]["systems"]["training"]["active"] if job.get("auto_rl")
    )
    assert first_job["improvement"]["source_model_id"] == strongest["id"]
    assert first_job["improvement"]["method"] == "rl"
    assert first_job["name"] == "Strong-1B-v02"

    for _ in range(80):
        progressed = e.advance(gid, 1)
        automation = progressed["systems"]["training"]["auto_rl"]
        if automation["cycles_completed"] >= 1:
            break
    assert automation["cycles_completed"] >= 1
    derived = next(
        model
        for model in progressed["systems"]["training"]["models"]
        if model.get("auto_rl") and model.get("parent_model_id") == strongest["id"]
    )
    assert derived["hidden_score"] > 210.0
    next_job = next(
        job for job in progressed["systems"]["training"]["active"] if job.get("auto_rl")
    )
    assert next_job["improvement"]["source_model_id"] == derived["id"]
    assert next_job["employee_ids"] == ["rl_specialist"]
    assert next_job["name"] == "Strong-1B-v03"

    stopped = e.action(gid, "set_auto_rl", {"enabled": False})
    assert stopped["ok"], stopped["message"]
    assert not stopped["state"]["systems"]["training"]["auto_rl"]["enabled"]


def test_late_api_market_outgrows_stable_contract_income():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    model = {
        "id": "mdl_late_api",
        "name": "Late-API-180B",
        "model_type": "text",
        "params_b": 180,
        "hidden_score": 150,
        "eval_scores": {
            "mmlu": 90,
            "humaneval": 90,
            "gsm8k": 90,
            "mt_bench": 90,
            "longbench": 90,
            "agentbench": 90,
            "safetybench": 90,
            "average": 90,
        },
        "released": True,
        "api_enabled": True,
        "open_source": False,
        "price_input": 2.0,
        "price_output": 6.0,
        "released_day": 0,
        "segment_affinity": {},
    }
    raw["models"].append(model)
    raw["company"]["tendencies"]["gov_relation"] = 80
    for offer_id in ("nebula_retail", "meridian_finance", "public_digital_service"):
        result = e.action(
            gid,
            "sign_contract",
            {"offer_id": offer_id, "model_id": model["id"], "duration_years": 2},
        )
        assert result["ok"], result["message"]
    raw["day"] = 719
    raw["market"]["next_eval_day"] = 9999
    raw["market"]["next_contract_offer_day"] = 9999
    late = e.advance(gid, 1)["systems"]["market"]
    assert late["api_market_multiplier"] > 20
    assert late["api_daily_revenue"] > late["contract_daily_revenue"] * 3
    assert late["player_api_market_share"] > 0


def test_dynamic_evals_contracts_competitor_churn_and_player_distillation():
    e, st = _new()
    gid = st["game_id"]
    raw = e.sessions[gid]
    initial_rivals = len(raw["competitors"])
    raw["market"]["next_eval_day"] = 1
    raw["market"]["next_contract_offer_day"] = 1
    raw["competitor_ai"]["next_entrant_day"] = 1
    progressed = e.advance(gid, 1)
    market = progressed["systems"]["market"]
    assert market["dynamic_evals"]
    dynamic_offers = [offer for offer in market["contract_offers"] if offer.get("dynamic")]
    assert dynamic_offers and dynamic_offers[0]["requirements"]["min_eval"] > 50
    assert len(progressed["systems"]["competitors"]["rivals"]) == initial_rivals + 1
    assert all(len(rival["top_models"]) <= 5 for rival in progressed["systems"]["competitors"]["rivals"])
    priced = next(
        model
        for rival in progressed["systems"]["competitors"]["rivals"]
        for model in rival["top_models"]
        if model["api_enabled"]
    )
    assert priced["price_input"] is not None and priced["price_output"] is not None
    assert progressed["systems"]["research"]["catalog"]["model"][0]["max_level"] == 40

    player_model = {
        "id": "mdl_player_teacher",
        "name": "Player-Frontier",
        "model_type": "text",
        "params_b": 70,
        "hidden_score": 190,
        "eval_scores": {"mmlu": 94, "gsm8k": 94, "average": 94},
        "released": True,
        "api_enabled": True,
        "open_source": False,
        "price_input": 2,
        "price_output": 6,
        "released_day": 1,
        "segment_affinity": {},
    }
    raw["models"].append(player_model)
    raw["day"] = 100
    raw["competitor_ai"]["last_player_distill_day"] = -999
    for rival in raw["competitors"]:
        rival["capital"] = max(float(rival.get("capital", 0)), 50_000_000)
    e.rng = random.Random(1)
    competitor_system = e.systems.get("competitors")
    msg = competitor_system._try_distill_player_model(
        raw["competitors"],
        e.configs.load("competitors")["strategies"],
        raw,
        GameContext(e),
    )
    assert msg and msg["type"] == "player_model_distilled"
    distilled = next(model for model in raw["competitor_models"] if model["id"] == msg["model_id"])
    assert distilled["distilled_from_player"]
    assert distilled["teacher_model_id"] == player_model["id"]

    bankrupt = raw["competitors"][0]
    bankrupt["capital"] = -300_000
    events = competitor_system._handle_bankruptcies(raw, GameContext(e))
    assert events and events[0]["type"] == "rival_bankrupt"
    assert raw["competitor_ai"]["bankruptcies"][-1]["id"] == bankrupt["id"]


if __name__ == "__main__":
    test_new_game_capital_and_systems()
    test_hire_and_research_and_train()
    test_save_load()
    test_hidden_score_monotonic_capacity()
    test_parameter_scaling_is_strong_monotonic_and_boundary_diminishing()
    test_parameter_count_drives_training_cost_and_compute_without_research_gate()
    test_china_has_ascend()
    test_research_accumulates_and_levels()
    test_research_staff_cap_is_shared_by_category()
    test_auto_research_rebalances_and_reserves_trainer()
    test_ai_rivals_exist_and_act()
    test_market_leaderboard_api_and_contract_income()
    test_auto_api_pricing_optimizes_revenue_and_manual_price_takes_over()
    test_successful_rival_poach_pays_breach_fee()
    test_chief_scientist_multiplies_team_skills_and_is_poach_immune()
    test_auto_hire_prioritizes_unstaffed_auto_research_by_roi()
    test_voluntary_leave_pays_no_severance_and_clears_assignments()
    test_loan_financing_repayment_and_early_payoff()
    test_model_improvement_creates_derived_versions()
    test_more_compute_materially_accelerates_training()
    test_standalone_closed_competitor_distillation()
    test_auto_distill_chains_latest_until_ninety_percent_target()
    test_auto_rl_uses_strongest_model_best_employee_and_keeps_chaining()
    test_late_api_market_outgrows_stable_contract_income()
    test_dynamic_evals_contracts_competitor_churn_and_player_distillation()
    print("all passed")
