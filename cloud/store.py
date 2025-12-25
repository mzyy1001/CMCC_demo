from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import uuid

@dataclass
class Session:
    id: str
    created_ts: float = field(default_factory=lambda: time.time())
    messages: List[Dict[str, str]] = field(default_factory=list)   # {"role": "...", "content": "..."}
    auto_enabled: bool = False
    last_edge_obs: Optional[Dict[str, Any]] = None
    last_actions: List[Dict[str, Any]] = field(default_factory=list)

class SessionStore:
    def __init__(self):
        self._s: Dict[str, Session] = {}

    def create(self) -> Session:
        sid = uuid.uuid4().hex[:12]
        sess = Session(id=sid)
        self._s[sid] = sess
        return sess

    def get(self, sid: str) -> Session:
        if sid not in self._s:
            raise KeyError(sid)
        return self._s[sid]
