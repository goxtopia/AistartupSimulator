"""Smoke tests for the game engine."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.engine.game import GameEngine
from backend.app.engine.calculators.scores import compute_hidden_score, clamp


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
        {"name": "mix", "use_open_source_base": True, "data_research_weights": {"code": 1}},
    )
    assert r["ok"], r["message"]
    ds = r["data"]["dataset"]["id"]

    # Let research accumulate a bit, then move the person onto training (GDT staff juggling)
    st_r = e.advance(gid, 4)
    cap = next(x for x in st_r["systems"]["research"]["catalog"]["model"] if x["id"] == "capacity")
    assert cap["progress_pct"] > 0 or cap["level"] > 0

    e.action(gid, "pause_research", {"research_id": "capacity"})
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


if __name__ == "__main__":
    test_new_game_capital_and_systems()
    test_hire_and_research_and_train()
    test_save_load()
    test_hidden_score_monotonic_capacity()
    test_china_has_ascend()
    test_research_accumulates_and_levels()
    test_ai_rivals_exist_and_act()
    print("all passed")
