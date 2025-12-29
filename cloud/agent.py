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

client = OpenAI()

SYSTEM = """You are a UAV dispatch agent running in the cloud.

You can:
- Observe edge state (drones, zones, events)
- Talk with the human operator
- Dispatch tasks to drones on the edge server
- Ask the route planner tool to generate waypoints (do NOT compute geometry yourself)

Policy:
- Default: keep drones patrolling.
- If FIRE_DETECTED occurs: assign >=3 drones to perimeter reconnaissance around the fire zone boundary.
- Human messages override automation. If user says "pause automation", stop dispatching and ask what to do next.
- Keep responses concise and actionable.
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
    Tool: plan_route
    Input schema (from OpenAI tool params):
      kind: "PERIMETER_RECT" | "PATROL_LAWNMOWER"
      rect: {xmin,xmax,ymin,ymax}
      margin?: number
      n_stripes?: integer

    Output:
      {"waypoints": [{"x":..,"y":..}, ...]}
    """
    kind = (args.get("kind") or "").upper()
    rect = args.get("rect")
    if not isinstance(rect, dict):
        raise ValueError("plan_route.rect must be an object")

    # validate rect keys
    for k in ("xmin", "xmax", "ymin", "ymax"):
        if k not in rect:
            raise ValueError(f"plan_route.rect missing key: {k}")

    if kind == "PERIMETER_RECT":
        margin = float(args.get("margin", 4.0))
        waypoints = plan_perimeter_rect(rect, margin=margin)
        return {"waypoints": waypoints}

    if kind == "PATROL_LAWNMOWER":
        n_stripes = int(args.get("n_stripes", 6))
        waypoints = plan_lawnmower(rect, n_stripes=n_stripes)
        return {"waypoints": waypoints}

    raise ValueError(f"Unsupported kind: {kind}")


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
    trace: List[Dict[str, Any]] = []   # ✅ 记录全过程
    assistant_text = ""

    resp = client.responses.create(
        model="gpt-4o",
        input=input_items,
        tools=TOOLS,
    )

    with open(f"chat_all_history.log", "a") as f:
        f.write(f"[AGENT] input: {json.dumps(input_items, ensure_ascii=False)}\n")
        f.write(f"[AGENT] output: {resp}\n")

    while True:
        # ✅ 记录每一轮模型输出（包含 function_call / message 等）
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

        # ✅ 记录你喂回去的 tool outputs
        trace.append({
            "stage": "tool_outputs",
            "tool_outputs": tool_outputs,
        })

        resp = client.responses.create(
            model="gpt-4o",
            input=resp.output + tool_outputs,
            tools=TOOLS,
        )

    # ✅ 注意：log 和 return 一定要在 while 外面
    try:
        log_chat(
            sid="N/A",
            user=user_message or "",
            assistant=assistant_text,
            extra={
                "mode": mode,
                "edge_obs": obs,
                "actions": actions,
                "trace": trace,  # ✅ 这就是你缺的“LLM过程”
                "input_items": input_items,  # 可选：把输入也存下来便于复现
            }
        )
    except Exception as e:
        print("[WARN] log_chat failed:", e)

    return assistant_text, actions, obs
