# CMCC_demo


第二层的api
```py
def act_patrol(
    trace_id: str,
    num_drones: int,
    patrol_mode: str = "SWEEP",   # "SWEEP" | "HOLD_CORNERS"
    constraints: dict | None = None
) -> dict:
    """
    Request a patrol behavior.
    """
    pass


def act_firefight(
    trace_id: str,
    num_drones: int,
    target_zone_id: str = "z_fire",
    constraints: dict | None = None
) -> dict:
    """
    Request a firefighting behavior.
    """
    pass


def act_survey(
    trace_id: str,
    num_drones: int,
    target_pos: dict | None = None,   # {"x": float, "y": float}
    target_zone_id: str | None = None,
    constraints: dict | None = None
) -> dict:
    """
    Request a survey behavior.
    """
    pass
```

http 链接client端云接口的api
可以调用 tool.py 的工具


```java
GET /health
Request: (none)
Response 200:
{ "ok": true }

GET /state
Request: (none)
Response 200 (StateResponse):
{
  "ts": 94.4,
  "drones": [
    {
      "id": "D1",
      "pos": { "x": 21.84, "y": 15.0 },
      "status": "NAVIGATING",
      "battery": 98.11,
      "task": {
        "type": "PATH",
        "waypoints": [{"x": 5.0, "y": 5.0}],
        "loop": true
      }
    }
  ],
  "zones": [
    {
      "id": "z_fire",
      "name": "FireZone-A",
      "type": "FIRE_RISK",
      "rect": { "xmin": 42.0, "xmax": 58.0, "ymin": 42.0, "ymax": 58.0 }
    }
  ],
  "recent_events": [
    {
      "ts": 94.4,
      "type": "FIRE_DETECTED",
      "drone_id": "D1",
      "pos": { "x": 49.0, "y": 49.0 },
      "message": "optional",
      "payload": {},
      "severity": 0.9,
      "confidence": 0.85
    }
  ]
}
```
```java
POST /cmd/assign_task
Request body (AssignTaskRequest):
{
  "drone_id": "D1",
  "task": {
    "type": "GOTO",
    "target": { "x": 50.0, "y": 50.0 },
    "arrive_eps": 2.0
  }
}

Response 200:
{
  "ok": true,
  "drone_id": "D1",
  "assigned": {
    "type": "GOTO",
    "target": { "x": 50.0, "y": 50.0 },
    "arrive_eps": 2.0
  }
}

Response 400:
{ "detail": "Unknown drone_id=D9" }

1) POST /cmd/batch
Request body (BatchAssignRequest):
{
  "commands": [
    {
      "drone_id": "D1",
      "task": {
        "type": "PATH",
        "id": "path_fire_1",
        "waypoints": [
          { "x": 42, "y": 42 },
          { "x": 58, "y": 42 },
          { "x": 58, "y": 58 },
          { "x": 42, "y": 58 }
        ],
        "loop": true
      }
    },
    {
      "drone_id": "D2",
      "task": {
        "type": "GOTO",
        "id": "goto_fire_center",
        "target": { "x": 50, "y": 50 },
        "arrive_eps": 2.0
      }
    }
  ]
}

Response 200:
{
  "ok": true,
  "results": [
    { "ok": true, "drone_id": "D1", "assigned": { "...": "..." } },
    { "ok": true, "drone_id": "D2", "assigned": { "...": "..." } }
  ]
}

If a command fails, it is reported per-item:
{
  "ok": true,
  "results": [
    { "ok": true, "drone_id": "D1", "assigned": { "...": "..." } },
    { "ok": false, "drone_id": "D9", "error": "Unknown drone_id=D9" }
  ]
}

```

```java
GOTO
{
  "type": "GOTO",
  "id": "optional_string",
  "target": { "x": 50.0, "y": 50.0 },
  "arrive_eps": 2.0
}

Rules:
- target required: {x,y}
- arrive_eps optional, default 2.0
- id optional; if omitted, auto-generated "goto_{int(ts*10)}"

PATH
{
  "type": "PATH",
  "id": "optional_string",
  "waypoints": [
    { "x": 10.0, "y": 10.0 },
    { "x": 90.0, "y": 10.0 }
  ],
  "loop": true
}

Rules:
- waypoints required: list of {x,y}
- loop optional, default true
- id optional; if omitted, auto-generated "path_{int(ts*10)}"

C) HOLD (special)
{
  "type": "HOLD",
  "drone_id": "D1",
  "id": "optional_string"
}



```

