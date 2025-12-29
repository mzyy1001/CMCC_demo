from __future__ import annotations
from typing import Any, Dict, List, Optional
import requests
import json
import time
import uuid
from datetime import datetime, timezone
from threading import Lock
import os

# ======================================================
# Edge trace config
# ======================================================
EDGE_TRACE_PATH = os.getenv("EDGE_TRACE_PATH", "edge_trace.jsonl")
_TRACE_LOCK = Lock()

import re

def normalize_drone_id(drone_id: str) -> str:
    """
    Accept:
      - D1 / D2 / ...
      - drone_1 / drone-1 / drone1
    Return:
      - D1 / D2 / ...
    """
    if not drone_id:
        return drone_id

    s = drone_id.strip()

    # already in canonical form
    if re.fullmatch(r"D\d+", s, flags=re.IGNORECASE):
        return f"D{int(s[1:])}"

    # drone_1 / drone-1 / drone1 -> D1
    m = re.fullmatch(r"drone[_-]?(\d+)", s, flags=re.IGNORECASE)
    if m:
        return f"D{int(m.group(1))}"

    # fallback: pass-through
    return s


def normalize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Edge accepts type: GOTO | PATH | HOLD.
    Allow cloud side to send PATROL as alias of PATH.
    """
    if not isinstance(task, dict):
        return task

    t = (task.get("type") or "").upper()

    # PATROL -> PATH
    if t == "PATROL":
        task = dict(task)          # avoid mutating caller dict
        task["type"] = "PATH"

    return task



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(record: Dict[str, Any]) -> None:
    with _TRACE_LOCK:
        with open(EDGE_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _safe_json(x: Any) -> Any:
    try:
        json.dumps(x, ensure_ascii=False)
        return x
    except Exception:
        return {"_repr": repr(x)}


def _edge_call(
    *,
    op: str,
    method: str,
    url: str,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """
    Unified Cloud -> Edge call with full tracing.

    Returns:
      {
        "ok": bool,
        "status": int | None,
        "data": Any | None,
        "text": str | None,
        "error": str | None,
      }
    """
    trace_id = uuid.uuid4().hex
    t0 = time.perf_counter()

    record: Dict[str, Any] = {
        "ts_utc": _utc_now(),
        "trace_id": trace_id,
        "op": op,
        "request": {
            "method": method,
            "url": url,
            "json": _safe_json(json_body),
        },
        "response": {},
        "latency_ms": None,
        "error": None,
    }

    try:
        r = requests.request(
            method=method,
            url=url,
            json=json_body,
            timeout=timeout,
        )
        record["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        record["response"]["status"] = r.status_code
        record["response"]["headers"] = dict(r.headers)

        try:
            data = r.json()
            record["response"]["json"] = _safe_json(data)
        except Exception:
            data = None
            record["response"]["text"] = r.text

        if not r.ok:
            record["error"] = f"HTTP {r.status_code}"
            _append_jsonl(record)
            return {
                "ok": False,
                "status": r.status_code,
                "data": data,
                "text": r.text,
                "error": record["error"],
            }

        _append_jsonl(record)
        return {
            "ok": True,
            "status": r.status_code,
            "data": data,
            "text": r.text,
            "error": None,
        }

    except Exception as e:
        record["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        record["error"] = repr(e)
        _append_jsonl(record)
        return {
            "ok": False,
            "status": None,
            "data": None,
            "text": None,
            "error": repr(e),
        }


# ======================================================
# ---- edge http (WITH TRACE) ----
# ======================================================
def edge_fetch_state(edge_base_url: str) -> Dict[str, Any]:
    r = _edge_call(
        op="fetch_state",
        method="GET",
        url=f"{edge_base_url}/state",
    )
    if not r["ok"]:
        raise RuntimeError(f"edge_fetch_state failed: {r['error']}")
    return r["data"]


def edge_assign(edge_base_url: str, drone_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
    drone_id = normalize_drone_id(drone_id)
    task = normalize_task(task)

    payload = {"drone_id": drone_id, "task": task}
    r = _edge_call(
        op="assign_task",
        method="POST",
        url=f"{edge_base_url}/cmd/assign_task",
        json_body=payload,
    )
    if not r["ok"]:
        raise RuntimeError(
            f"edge_assign failed: {r['error']} | status={r['status']} | body={r['text']}"
        )
    return r["data"]


def edge_batch(edge_base_url: str, commands: List[Dict[str, Any]]) -> Dict[str, Any]:
    # normalize each command
    normalized_cmds: List[Dict[str, Any]] = []
    for c in commands:
        c2 = dict(c)
        c2["drone_id"] = normalize_drone_id(str(c2.get("drone_id", "")))
        c2["task"] = normalize_task(c2.get("task", {}))
        normalized_cmds.append(c2)

    payload = {"commands": normalized_cmds}
    r = _edge_call(
        op="batch_assign",
        method="POST",
        url=f"{edge_base_url}/cmd/batch",
        json_body=payload,
    )
    if not r["ok"]:
        raise RuntimeError(
            f"edge_batch failed: {r['error']} | status={r['status']} | body={r['text']}"
        )
    return r["data"]

# ======================================================
# ---- routing (LLM 不做几何) ----
# ======================================================
def plan_perimeter_rect(rect: Dict[str, float], margin: float = 4.0) -> List[Dict[str, float]]:
    xmin, xmax, ymin, ymax = rect["xmin"], rect["xmax"], rect["ymin"], rect["ymax"]
    xmin -= margin; xmax += margin; ymin -= margin; ymax += margin
    return [
        {"x": xmin, "y": ymin},
        {"x": xmax, "y": ymin},
        {"x": xmax, "y": ymax},
        {"x": xmin, "y": ymax},
        {"x": xmin, "y": ymin},
    ]


def plan_lawnmower(rect: Dict[str, float], n_stripes: int = 6) -> List[Dict[str, float]]:
    xmin, xmax, ymin, ymax = rect["xmin"], rect["xmax"], rect["ymin"], rect["ymax"]
    n_stripes = max(2, int(n_stripes))
    step = (xmax - xmin) / (n_stripes - 1)
    pts: List[Dict[str, float]] = []
    for i in range(n_stripes):
        x = xmin + i * step
        if i % 2 == 0:
            pts += [{"x": x, "y": ymin}, {"x": x, "y": ymax}]
        else:
            pts += [{"x": x, "y": ymax}, {"x": x, "y": ymin}]
    return pts
