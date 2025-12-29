# trace.py
from __future__ import annotations
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

TRACE_PATH = "/tmp/agent_trace.jsonl"

def trace_agent_call(
    *,
    sid: str,
    mode: str,
    session_messages: List[Dict[str, Any]],
    user_message: Optional[str],
    call_fn,
) -> Tuple[str, list, dict]:
    call_id = uuid.uuid4().hex
    t0 = time.time()

    record = {
        "call_id": call_id,
        "sid": sid,
        "mode": mode,
        "start_ts": t0,
        "input": {
            "num_messages": len(session_messages),
            "last_role": session_messages[-1]["role"] if session_messages else None,
            "user_message": user_message,
        },
    }

    try:
        reply, actions, obs = call_fn()
        ok = True
        err = None
    except Exception as e:
        reply, actions, obs = None, [], {}
        ok = False
        err = repr(e)

    t1 = time.time()

    record.update({
        "end_ts": t1,
        "duration_s": round(t1 - t0, 4),
        "ok": ok,
        "error": err,
        "output": {
            "reply": reply,
            "actions": actions,
            "obs": obs,
        },
    })

    with open(TRACE_PATH, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if not ok:
        raise RuntimeError(err)

    return reply, actions, obs
