from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from cloud.logger import log_chat
from .config import EDGE_BASE_URL



from .tools import (
    edge_fetch_state, edge_assign, edge_batch,
    plan_perimeter_rect, plan_lawnmower
)

from pathlib import Path
import time

def _history_log_path(mode: str) -> Path:
    mode_dir = (mode or "unknown").strip().lower()
    base = Path("logs") / mode_dir
    base.mkdir(parents=True, exist_ok=True)
    return base / "chat_all_history.log"

client = OpenAI()

SYSTEM = """You are a UAV dispatch agent running in the cloud.

You receive the latest edge observation inside a block:
[EDGE_OBS] ... [/EDGE_OBS]

CRITICAL RULES (must follow):
1) You MUST treat [EDGE_OBS] as the only source of truth. Do NOT invent drones, zones, events, or coordinates.
2) When dispatching, you MUST use drone_id exactly from [EDGE_OBS].drones[].id (e.g., "D1"). NEVER output or use IDs like "Drone_001", "D123", "P3-D4", etc.
3) If you need to pick drones, choose from the available IDs in [EDGE_OBS]. Prefer higher battery and closer position.
4) Tool usage order:
   - If you need geometry/waypoints, call plan_route first.
   - Then dispatch using dispatch_batch (preferred) or dispatch_task.
   - After tools are done, output a concise natural-language status message.
5) Never call plan_route more than once per turn.

POLICY:
- Default behavior: keep drones patrolling the main area (lawnmower or perimeter as appropriate).
- If latest_fire is present (FIRE_DETECTED):
  - Dispatch >=3 drones to recon the fire zone boundary.
  - Use plan_route(kind="PERIMETER_RECT") with rect taken from the fire zone rect.
  - Use a PATH task with loop=true for each selected drone, using the planned waypoints.
  - Do NOT send a task to a non-existent drone_id.
- Human messages override automation:
  - If user says "pause automation", do not dispatch; ask what to do next.
  - If user gives explicit drone IDs or tasks, follow them as long as drone IDs exist in EDGE_OBS.

OUTPUT STYLE:
- Keep responses concise and actionable.
- If a tool call is needed, make the tool call (no extra text).
- If tools are complete, summarize: which drones, what task, and why (e.g., FIRE_DETECTED).
"""
TOOLS = [
    {
        "type": "function",
        "name": "plan_route",
        "description": "Generate waypoints for patrol/perimeter. Use this for geometry.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["PERIMETER_RECT", "PATROL_LAWNMOWER"]},
                "rect": {
                    "type": "object",
                    "properties": {
                        "xmin": {"type": "number"},
                        "xmax": {"type": "number"},
                        "ymin": {"type": "number"},
                        "ymax": {"type": "number"},
                    },
                    "required": ["xmin", "xmax", "ymin", "ymax"],
                },
                "margin": {"type": "number", "minimum": 0, "maximum": 50},
                "n_stripes": {"type": "integer", "minimum": 2, "maximum": 30},
            },
            "required": ["kind", "rect"],
        },
    },
    {
        "type": "function",
        "name": "dispatch_task",
        "description": "Send one task to one edge drone. MUST include a valid task object.",
        "parameters": {
            "type": "object",
            "properties": {
            "drone_id": {"type": "string"},
            "task": {
                "type": "object",
                "oneOf": [
                {
                    "type": "object",
                    "properties": {
                    "type": {"const": "PATH"},
                    "waypoints": {
                        "type": "array",
                        "items": {
                        "type": "object",
                        "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                        "required": ["x", "y"]
                        }
                    },
                    "loop": {"type": "boolean"}
                    },
                    "required": ["type", "waypoints", "loop"]
                },
                {
                    "type": "object",
                    "properties": {
                    "type": {"const": "GOTO"},
                    "target": {
                        "type": "object",
                        "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                        "required": ["x", "y"]
                    },
                    "arrive_eps": {"type": "number"}
                    },
                    "required": ["type", "target"]
                },
                {
                    "type": "object",
                    "properties": {
                    "type": {"const": "PERIMETER"},
                    "zone_id": {"type": "string"},
                    "offset": {"type": "number"},
                    "loop": {"type": "boolean"}
                    },
                    "required": ["type", "zone_id", "offset", "loop"]
                },
                {
                    "type": "object",
                    "properties": {
                    "type": {"const": "HOLD"},
                    "duration_s": {"type": "number"}
                    },
                    "required": ["type"]
                }
                ]
            }
            },
            "required": ["drone_id", "task"]
        }
    },
    {
        "type": "function",
        "name": "dispatch_batch",
        "description": "Send tasks to multiple drones.",
        "parameters": {
            "type": "object",
            "properties": {
            "commands": {"type": "array", "items": {"type": "object"}}
            },
            "required": ["commands"]
        }
    },
]

def _summarize_edge_state(edge_state: Dict[str, Any]) -> Dict[str, Any]:
    drones = edge_state.get("drones", [])
    zones = edge_state.get("zones", [])
    evs = edge_state.get("recent_events", [])

    latest_fire = None
    for e in reversed(evs):
        if e.get("type") == "FIRE_DETECTED":
            latest_fire = e
            break

    return {
        "ts": edge_state.get("ts"),
        "drones": [
            {"id": d["id"], "status": d["status"], "battery": d["battery"], "pos": d["pos"], "task": d.get("task")}
            for d in drones
        ],
        "zones": zones,
        "latest_fire": latest_fire,
    }

def _tool_plan_route(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tool: plan_route (+AUTO DISPATCH)
    Input schema (from OpenAI tool params):
      kind: "PERIMETER_RECT" | "PATROL_LAWNMOWER"
      rect: {xmin,xmax,ymin,ymax}
      margin?: number
      n_stripes?: integer

    Optional extra args (not required):
      drone_ids?: list[str]   # explicit target drones
      n_drones?: int          # pick top-N by battery if drone_ids not given
      loop?: bool             # PATH.loop, default True

    Output:
      {
        "waypoints": [...],
        "selected_drones": [...],
        "dispatch_result": {...}
      }
    """
    kind = (args.get("kind") or "").upper()
    rect = args.get("rect")
    if not isinstance(rect, dict):
        raise ValueError("plan_route.rect must be an object")

    for k in ("xmin", "xmax", "ymin", "ymax"):
        if k not in rect:
            raise ValueError(f"plan_route.rect missing key: {k}")

    # 1) plan waypoints (pure geometry)
    if kind == "PERIMETER_RECT":
        margin = float(args.get("margin", 4.0))
        waypoints = plan_perimeter_rect(rect, margin=margin)
    elif kind == "PATROL_LAWNMOWER":
        n_stripes = int(args.get("n_stripes", 6))
        waypoints = plan_lawnmower(rect, n_stripes=n_stripes)
    else:
        raise ValueError(f"Unsupported kind: {kind}")

    # 2) AUTO DISPATCH (POST happens here)
    edge_state = edge_fetch_state(EDGE_BASE_URL)
    drones = edge_state.get("drones", [])

    # pick targets
    requested_ids = args.get("drone_ids")
    if isinstance(requested_ids, list) and requested_ids:
        requested_ids = [str(x) for x in requested_ids]
        selected = [d for d in drones if d.get("id") in requested_ids]
    else:
        n_drones = args.get("n_drones")
        # sort by battery desc, then stable by id
        drones_sorted = sorted(
            drones,
            key=lambda d: (float(d.get("battery", 0.0)), str(d.get("id", ""))),
            reverse=True,
        )
        if isinstance(n_drones, int) and n_drones > 0:
            selected = drones_sorted[:n_drones]
        else:
            selected = drones_sorted  # default: all drones

    selected_ids = [d.get("id") for d in selected if d.get("id")]
    if not selected_ids:
        return {
            "waypoints": waypoints,
            "selected_drones": [],
            "dispatch_result": {"note": "no drones available to dispatch"},
        }

    loop = args.get("loop")
    if not isinstance(loop, bool):
        loop = True

    commands = [
        {
            "drone_id": did,
            "task": {
                "type": "PATH",
                "waypoints": waypoints,
                "loop": loop,
            },
        }
        for did in selected_ids
    ]

    dispatch_result = edge_batch(EDGE_BASE_URL, commands)

    return {
        "waypoints": waypoints,
        "selected_drones": selected_ids,
        "dispatch_result": dispatch_result,
    }


def _tool_dispatch_task(args: Dict[str, Any]) -> Dict[str, Any]:
    if "task" not in args:
        raise ValueError(f"Missing 'task' in args for edge_assign. keys={list(args.keys())}, args={args}")
    if "drone_id" not in args:
        raise ValueError(f"Missing 'drone_id' in args for edge_assign. keys={list(args.keys())}, args={args}")
    return edge_assign(EDGE_BASE_URL, args["drone_id"], args["task"])


def _tool_dispatch_batch(args: Dict[str, Any]) -> Dict[str, Any]:
    cmds = args.get("commands")
    if cmds is None:
        single = args.get("command")
        if single is not None:
            cmds = [single]
    if cmds is None:
        return {"results": [], "note": "no commands provided"}

    return edge_batch(EDGE_BASE_URL, cmds)


def run_agent_turn(
    session_messages: List[Dict[str, str]],
    user_message: Optional[str],
    mode: str,
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    edge_state = edge_fetch_state(EDGE_BASE_URL)
    obs = _summarize_edge_state(edge_state)

    input_items = [{"role": "system", "content": SYSTEM}]
    input_items += session_messages[-20:]
    input_items.append({
        "role": "user",
        "content": f"[EDGE_OBS]\n{json.dumps(obs, ensure_ascii=False)}\n[/EDGE_OBS]\nMode={mode}"
    })
    if user_message:
        input_items.append({"role": "user", "content": user_message})

    actions: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    assistant_text = ""

    resp = client.responses.create(
        model="gpt-4o",
        input=input_items,
        tools=TOOLS,
    )

    log_path = _history_log_path(mode)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[AGENT] input: {json.dumps(input_items, ensure_ascii=False)}\n")
        f.write(f"[AGENT] output: {resp}\n")


    while True:
        trace.append({
            "stage": "model_output",
            "output": [o.model_dump() if hasattr(o, "model_dump") else dict(o) for o in resp.output],
            "output_text": getattr(resp, "output_text", None),
        })

        calls = [o for o in resp.output if o.type == "function_call"]
        if not calls:
            assistant_text = resp.output_text or ""
            break

        tool_outputs = []
        plan_route_called = False

        for c in calls:
            name = c.name
            args = json.loads(c.arguments or "{}")

            if name == "plan_route":
                if plan_route_called:
                    out = {"skipped": True, "reason": "duplicate plan_route in same turn"}
                    tool_outputs.append({
                        "type": "function_call_output",
                        "call_id": c.call_id,
                        "output": json.dumps(out, ensure_ascii=False),
                    })
                    continue

                plan_route_called = True
                out = _tool_plan_route(args)
                actions.append({"tool": "plan_route", "args": args, "result": out})
            elif name == "dispatch_task":
                out = _tool_dispatch_task(args)
                actions.append({"tool": "dispatch_task", "args": args, "result": out})
            elif name == "dispatch_batch":
                out = _tool_dispatch_batch(args)
                actions.append({"tool": "dispatch_batch", "args": args, "result": out})
            else:
                out = {"error": f"unknown tool {name}"}
                actions.append({"tool": name, "args": args, "result": out})

            tool_outputs.append({
                "type": "function_call_output",
                "call_id": c.call_id,
                "output": json.dumps(out, ensure_ascii=False),
            })

        trace.append({
            "stage": "tool_outputs",
            "tool_outputs": tool_outputs,
        })

        resp = client.responses.create(
            model="gpt-4o",
            input=resp.output + tool_outputs,
            tools=TOOLS,
        )

    try:
        log_chat(
            sid="N/A",
            user=user_message or "",
            assistant=assistant_text,
            extra={
                "mode": mode,
                "edge_obs": obs,
                "actions": actions,
                "trace": trace,
                "input_items": input_items,
            }
        )
    except Exception as e:
        print("[WARN] log_chat failed:", e)

    return assistant_text, actions, obs
