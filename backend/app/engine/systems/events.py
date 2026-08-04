"""Random / country early events — fully config-indexed."""

from __future__ import annotations

import uuid
from typing import Any


class EventSystem:
    name = "events"

    def on_new_game(self, state: dict[str, Any], ctx) -> None:
        country = state["company"]["country"]
        country_cfg = ctx.configs().get("countries", "countries", country, default={}) or {}
        state["events"] = {
            "queue": [],  # pending player choices
            "history": [],
            "fired_ids": [],
            "country_early": list(country_cfg.get("early_events", [])),
            "early_index": 0,
            "next_early_day": ctx.rng().randint(3, 12),
            "next_random_day": ctx.rng().randint(15, 40),
        }

    def on_tick(self, state: dict[str, Any], ctx, days: int = 1) -> list[dict]:
        events: list[dict] = []
        day = state.get("day", 0)
        ev = state.setdefault("events", {})

        # Don't stack too many pending
        if len(ev.get("queue", [])) >= 2:
            return events

        # Early country events in sequence-ish order
        if day >= int(ev.get("next_early_day", 9999)) and ev.get("country_early"):
            early_ids = ev["country_early"]
            # pick next not fired
            pick = None
            for eid in early_ids:
                if eid not in ev.get("fired_ids", []):
                    pick = eid
                    break
            if pick:
                inst = self._instantiate(state, ctx, pick)
                if inst:
                    ev.setdefault("queue", []).append(inst)
                    ev.setdefault("fired_ids", []).append(pick)
                    events.append({"type": "event", "msg": f"事件：{inst['title']}", "event": inst})
            ev["next_early_day"] = day + ctx.rng().randint(18, 40)

        # Generic random from all early_events pool later
        if day >= int(ev.get("next_random_day", 9999)) and len(ev.get("queue", [])) < 2:
            all_events = ctx.configs().load("events").get("early_events", {})
            candidates = []
            for eid, ecfg in all_events.items():
                if eid in ev.get("fired_ids", []):
                    continue
                min_d = int(ecfg.get("min_day", 0))
                max_d = int(ecfg.get("max_day", 9999))
                if day < min_d or day > max_d:
                    continue
                if int(ecfg.get("requires_employees", 0)) > len(state.get("employees", [])):
                    continue
                candidates.append((eid, float(ecfg.get("weight", 1.0))))
            if candidates:
                ids, weights = zip(*candidates)
                # weighted
                total = sum(weights)
                r = ctx.rng().random() * total
                acc = 0.0
                chosen = ids[0]
                for i, w in zip(ids, weights):
                    acc += w
                    if r <= acc:
                        chosen = i
                        break
                inst = self._instantiate(state, ctx, chosen)
                if inst:
                    ev.setdefault("queue", []).append(inst)
                    ev.setdefault("fired_ids", []).append(chosen)
                    events.append({"type": "event", "msg": f"事件：{inst['title']}", "event": inst})
            ev["next_random_day"] = day + ctx.rng().randint(20, 45)

        return events

    def serialize_public(self, state: dict[str, Any], ctx) -> dict[str, Any]:
        return {
            "queue": state.get("events", {}).get("queue", []),
            "history": state.get("events", {}).get("history", [])[-20:],
        }

    def choose(self, state: dict[str, Any], ctx, event_instance_id: str, choice_id: str) -> tuple[bool, str, list[str]]:
        queue = state.get("events", {}).get("queue", [])
        inst = next((e for e in queue if e["instance_id"] == event_instance_id), None)
        if not inst:
            return False, "事件不存在或已处理", []
        choice = next((c for c in inst.get("choices", []) if c["id"] == choice_id), None)
        if not choice:
            return False, "无效选项", []

        logs = ctx.effects().apply(state, choice.get("effects", {}), ctx)
        queue.remove(inst)
        record = {
            **inst,
            "chosen": choice_id,
            "chosen_label": choice.get("label"),
            "result_logs": logs,
            "resolved_day": state.get("day", 0),
        }
        state["events"].setdefault("history", []).append(record)
        state.setdefault("log", []).append(
            {
                "day": state.get("day", 0),
                "msg": f"事件「{inst['title']}」→ {choice.get('label')}（{'; '.join(logs) or '无直接效果'}）",
                "cat": "event",
            }
        )
        return True, f"已选择：{choice.get('label')}", logs

    def _instantiate(self, state: dict, ctx, event_id: str) -> dict | None:
        ecfg = ctx.configs().get("events", "early_events", event_id, default=None)
        if not ecfg:
            return None
        return {
            "instance_id": str(uuid.uuid4())[:8],
            "event_id": event_id,
            "title": ecfg.get("title", event_id),
            "description": ecfg.get("description", ""),
            "choices": ecfg.get("choices", []),
            "day": state.get("day", 0),
        }
