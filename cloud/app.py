from __future__ import annotations

import threading
import time

from fastapi import FastAPI, HTTPException

from .config import EDGE_BASE_URL, AUTO_INTERVAL_S
from .store import SessionStore
from .schemas import (
    CreateSessionResp, ChatReq, ChatResp, TickReq, TickResp, SessionStateResp
)
from .agent import run_agent_turn
from .trace import trace_agent_call


app = FastAPI(title="Cloud UAV Agent", version="0.1")
store = SessionStore()

# session_id -> background thread handle
_auto_threads: dict[str, threading.Thread] = {}
_auto_stop_flags: dict[str, threading.Event] = {}

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/sessions", response_model=CreateSessionResp)
def create_session():
    sess = store.create()
    # 初始给一条系统说明（可选）
    sess.messages.append({"role": "assistant", "content": "Session created. Automation is off. Say 'start automation' to enable."})
    return CreateSessionResp(session_id=sess.id)

@app.get("/sessions/{sid}/state", response_model=SessionStateResp)
def get_session_state(sid: str):
    try:
        sess = store.get(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown session")

    return SessionStateResp(
        session_id=sess.id,
        auto_enabled=sess.auto_enabled,
        last_edge_obs=sess.last_edge_obs,
        last_actions=sess.last_actions[-20:],
        messages_tail=sess.messages[-20:],
    )

@app.post("/sessions/{sid}/chat", response_model=ChatResp)
def chat(sid: str, req: ChatReq):
    try:
        sess = store.get(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown session")

    edge = EDGE_BASE_URL

    # 人类插话
    sess.messages.append({"role": "user", "content": req.message})

    # 如果用户说暂停自动化，这里先简单处理（也可以交给 LLM）
    if "pause automation" in req.message.lower() or "stop automation" in req.message.lower():
        _stop_auto(sid)
        sess.auto_enabled = False
        reply = "Automation stopped. Tell me what you want to do next."
        sess.messages.append({"role": "assistant", "content": reply})
        return ChatResp(reply=reply, actions=[], edge_obs=sess.last_edge_obs or {})

    try:
        reply, actions, obs = trace_agent_call(
            sid=sid,
            mode="CHAT",
            session_messages=sess.messages,
            user_message=req.message,
            call_fn=lambda: run_agent_turn(
                session_messages=sess.messages,
                user_message=None,
                mode="CHAT",
            )
        )
    except Exception as e:
        reply = f"[ERROR] {e}"
        actions = []
        obs = {}

    sess.last_edge_obs = obs
    sess.last_actions.extend(actions)
    sess.messages.append({"role": "assistant", "content": reply})

    # 如果用户说开启自动化
    if "start automation" in req.message.lower() or "enable automation" in req.message.lower():
        _start_auto(sid)

    return ChatResp(reply=reply, actions=actions, edge_obs=obs)

@app.post("/sessions/{sid}/tick", response_model=TickResp)
def tick(sid: str, req: TickReq):
    try:
        sess = store.get(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown session")

    edge = EDGE_BASE_URL
    reply, actions, obs = run_agent_turn(session_messages=sess.messages, user_message=None, mode="AUTO")
    sess.last_edge_obs = obs
    sess.last_actions.extend(actions)
    sess.messages.append({"role": "assistant", "content": reply})
    return TickResp(reply=reply, actions=actions, edge_obs=obs)

@app.post("/sessions/{sid}/auto/start")
def auto_start(sid: str):
    return _start_auto(sid)

@app.post("/sessions/{sid}/auto/stop")
def auto_stop(sid: str):
    _stop_auto(sid)
    try:
        sess = store.get(sid)
        sess.auto_enabled = False
    except KeyError:
        pass
    return {"ok": True}

def _auto_loop(sid: str, stop: threading.Event):
    while not stop.is_set():
        print(f"[AUTO] session {sid} tick")
        try:
            sess = store.get(sid)
        except KeyError:
            return
        if not sess.auto_enabled:
            time.sleep(2)
            continue

        try:
            print(f"[AUTO] session {sid} running agent turn")
            reply, actions, obs = run_agent_turn(session_messages=sess.messages, user_message=None, mode="AUTO")
            with open(f"/tmp/auto_{sid}.log", "a") as f:
                f.write(f"[AUTO] reply: {reply}\n")
                f.write(f"[AUTO] actions: {actions}\n")
                f.write(f"[AUTO] obs: {obs}\n")
            sess.last_edge_obs = obs
            sess.last_actions.extend(actions)
            sess.messages.append({"role": "assistant", "content": reply})
        except Exception as e:
            sess.messages.append({"role": "assistant", "content": f"[AUTO ERROR] {e}"})

        time.sleep(AUTO_INTERVAL_S)

def _start_auto(sid: str):
    sess = store.get(sid)
    sess.auto_enabled = True

    if sid in _auto_threads and _auto_threads[sid].is_alive():
        return {"ok": True, "auto": "already_running"}

    stop = threading.Event()
    _auto_stop_flags[sid] = stop
    t = threading.Thread(target=_auto_loop, args=(sid, stop), daemon=True)
    _auto_threads[sid] = t
    t.start()
    return {"ok": True, "auto": "started"}

def _stop_auto(sid: str):
    if sid in _auto_stop_flags:
        _auto_stop_flags[sid].set()
