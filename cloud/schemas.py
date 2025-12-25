from __future__ import annotations
from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class CreateSessionResp(BaseModel):
    session_id: str


class ChatReq(BaseModel):
    message: str


class ChatResp(BaseModel):
    reply: str
    actions: List[Dict[str, Any]]
    edge_obs: Dict[str, Any]


class TickReq(BaseModel):
    # 预留：如果你以后想支持 tick 的“模式”，可以加 mode
    pass


class TickResp(BaseModel):
    reply: str
    actions: List[Dict[str, Any]]
    edge_obs: Dict[str, Any]


class SessionStateResp(BaseModel):
    session_id: str
    auto_enabled: bool
    last_edge_obs: Optional[Dict[str, Any]] = None
    last_actions: List[Dict[str, Any]]
    messages_tail: List[Dict[str, str]]
