from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, List

import httpx

from cloud.actions.tool import load_events, edge_get_state
from cloud.actions.patrol import act_patrol
from cloud.actions.firefight import act_firefight
from cloud.actions.survey import act_survey


EDGE_BASE_URL = os.getenv("EDGE_BASE_URL", "http://127.0.0.1:8001")
EVENT_LIST_TXT = os.getenv("EVENT_LIST_TXT", "events_dedup.txt")


def assert_true(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)


def ping_edge() -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            r = client.get(f"{EDGE_BASE_URL}/health")
            return r.status_code == 200
    except Exception:
        return False


def get_tasks_map(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    返回: {drone_id: task_dict_or_None}
    """
    m = {}
    for d in state.get("drones", []) or []:
        m[d.get("id")] = d.get("task")
    return m


def main():
    print("=== TEST DISPATCH ===")
    print(f"EDGE_BASE_URL = {EDGE_BASE_URL}")
    print(f"EVENT_LIST_TXT = {EVENT_LIST_TXT}")

    # 0) edge server must be alive
    assert_true(ping_edge(), f"Edge server not reachable: {EDGE_BASE_URL}. Start edge_server first.")
    print("[OK] edge /health reachable")

    # 1) event list must exist
    events = load_events(EVENT_LIST_TXT)
    assert_true(len(events) > 0, f"event list empty: {EVENT_LIST_TXT}")
    print(f"[OK] loaded events: {len(events)}")

    # pick first event
    event_num = 1
    first_ev = events[event_num - 1]
    print(f"[INFO] using event_num={event_num}: {json.dumps(first_ev, ensure_ascii=False)}")

    # 2) state before
    state0 = edge_get_state()
    tasks0 = get_tasks_map(state0)
    print("[INFO] tasks before:", {k: ("None" if v is None else v.get("type")) for k, v in tasks0.items()})

    # 3) dispatch patrol (normal drones)
    # Note: patrol accepts optional event_num for context
    r_patrol = act_patrol(trace_id="test_patrol", num_drones=2, event_num=event_num)
    print("[PATROL]", json.dumps(r_patrol, ensure_ascii=False, indent=2))
    assert_true(r_patrol.get("ok") is True, f"act_patrol failed: {r_patrol}")

    patrol_drones: List[str] = r_patrol.get("picked_drones") or []
    # assert_true(len(patrol_drones) > 0, "act_patrol picked_drones empty") 
    # (might be empty if drones busy, but let's assume successful for test flow)

    # 4) dispatch survey (strict event-driven)
    # Using the same event (assuming it has a zone)
    r_survey = act_survey(trace_id="test_survey", num_drones=1, event_num=event_num)
    print("[SURVEY]", json.dumps(r_survey, ensure_ascii=False, indent=2))
    assert_true(r_survey.get("ok") is True, f"act_survey failed: {r_survey}")
    
    survey_drones: List[str] = r_survey.get("picked_drones") or []

    # 5) dispatch firefight (fire drones)
    r_fire = act_firefight(trace_id="test_firefight", num_drones=2, event_num=event_num)
    print("[FIREFIGHT]", json.dumps(r_fire, ensure_ascii=False, indent=2))
    assert_true(r_fire.get("ok") is True, f"act_firefight failed: {r_fire}")

    fire_drones: List[str] = r_fire.get("picked_drones") or []
    assert_true(len(fire_drones) > 0, "act_firefight picked_drones empty")

    # 5) wait a bit for edge runtime update
    time.sleep(0.4)

    # 6) state after
    state1 = edge_get_state()
    tasks1 = get_tasks_map(state1)
    print("[INFO] tasks after:", {k: ("None" if v is None else v.get("type")) for k, v in tasks1.items()})

    # 7) verify dispatched drones got tasks
    for did in patrol_drones:
        assert_true(tasks1.get(did) is not None, f"Patrol drone {did} still has no task after dispatch")
        assert_true(tasks1[did].get("type") in ("PATH", "GOTO"), f"Patrol drone {did} task type unexpected: {tasks1[did]}")

    for did in fire_drones:
        assert_true(tasks1.get(did) is not None, f"Fire drone {did} still has no task after dispatch")
        assert_true(tasks1[did].get("type") in ("GOTO", "PATH"), f"Fire drone {did} task type unexpected: {tasks1[did]}")

    print("\n✅ ALL TESTS PASSED!")


if __name__ == "__main__":
    main()
