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
            "employee_ids": [],
        },
    )
    assert r["ok"], r["message"]

    st2 = e.advance(gid, 20)
    assert st2["day"] == 20
    models = st2["systems"]["training"]["models"]
    assert len(models) >= 1
    assert models[0]["hidden_score"] > 0
    assert "average" in models[0]["eval_scores"]

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


if __name__ == "__main__":
    test_new_game_capital_and_systems()
    test_hire_and_research_and_train()
    test_save_load()
    test_hidden_score_monotonic_capacity()
    test_china_has_ascend()
    print("all passed")
