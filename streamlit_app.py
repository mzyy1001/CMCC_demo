import json
from typing import Any, Dict, Optional, Tuple, List

import requests
import streamlit as st

# =========================================================
# Page
# =========================================================
st.set_page_config(page_title="UAV Agent UI", layout="wide")

# =========================================================
# State init (MUST be before widgets)
# =========================================================
st.session_state.setdefault("cloud_url", "http://127.0.0.1:9001")
st.session_state.setdefault("mode", "CHAT")

# IMPORTANT: separate widget input vs active session id
st.session_state.setdefault("sid_input", "")      # only user edits (widget)
st.session_state.setdefault("sid_current", "")    # app uses
st.session_state.setdefault("sid_pending", None)  # app requests to sync into sid_input on next run

# Chat stream: list of messages rendered like ChatGPT
# message schema:
# {
#   "role": "user"|"assistant"|"tool",
#   "text": str,
#   "meta": dict (optional),
#   "kind": "final"|"trace_answer"|"tool_outputs" (optional)
# }
st.session_state.setdefault("chat", [])
st.session_state.setdefault("last", {})           # last extracted fields

# UI toggles
st.session_state.setdefault("show_trace_qa", True)
st.session_state.setdefault("trace_question_ignore_edge_obs", True)
st.session_state.setdefault("trace_attach_tool_outputs", True)
st.session_state.setdefault("inject_trace_into_chat", True)
st.session_state.setdefault("show_tool_messages_in_chat", True)

# ---- safe sync pending SID -> sid_input (ONLY here, before widgets) ----
if st.session_state.get("sid_pending"):
    st.session_state["sid_input"] = st.session_state["sid_pending"]
    st.session_state["sid_pending"] = None


# =========================================================
# Helpers
# =========================================================
def jdump(x: Any) -> str:
    try:
        return json.dumps(x, ensure_ascii=False, indent=2)
    except Exception:
        return str(x)

def api_post(base: str, path: str, body: Optional[Dict[str, Any]] = None, timeout: float = 20.0) -> Any:
    url = base.rstrip("/") + path
    r = requests.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"_raw_text": r.text}

def create_session(base: str) -> str:
    resp = api_post(base, "/sessions", body=None)
    sid = resp.get("session_id") or resp.get("sid")
    if not sid:
        raise RuntimeError(f"/sessions 返回里没找到 session_id: {resp}")
    return sid

def get_active_sid(base: str) -> str:
    """
    Returns the SID used for requests. If empty, create a new session.
    NEVER writes to sid_input directly (widget key).
    """
    sid = (st.session_state.get("sid_current") or "").strip()
    if sid:
        return sid

    sid = create_session(base)
    st.session_state["sid_current"] = sid
    st.session_state["sid_pending"] = sid   # will be synced to sid_input next run
    return sid

def _dig(d: Any, keys: Tuple[str, ...]) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur

def _as_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return jdump(content)

def _is_edge_obs_block(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("[EDGE_OBS]") or t.startswith("{\"ts\":") or t.startswith("{'ts':")

def trace_to_qa_pairs(
    trace: Any,
    ignore_edge_obs_question: bool = True,
    attach_tool_outputs: bool = True
) -> List[Dict[str, Any]]:
    """
    Parse trace timeline into Q/A pairs.

    - Each `stage == "model_output"` with non-empty `output_text` => an assistant answer
    - question = last user content in that step's input_items
      (optionally ignoring EDGE_OBS blocks)
    - tool_outputs: tool outputs collected between last answer and this answer
    """
    if not isinstance(trace, list):
        return []

    pairs: List[Dict[str, Any]] = []
    pending_tool_outputs: List[Dict[str, Any]] = []

    def last_user_text(input_items: Any) -> str:
        if not isinstance(input_items, list):
            return ""
        for it in reversed(input_items):
            if isinstance(it, dict) and it.get("role") == "user":
                c = _as_text(it.get("content", ""))
                if ignore_edge_obs_question and _is_edge_obs_block(c):
                    continue
                return c
        # 如果全是 EDGE_OBS，被忽略后找不到，那就退回：不忽略再取一次
        if ignore_edge_obs_question:
            for it in reversed(input_items):
                if isinstance(it, dict) and it.get("role") == "user":
                    return _as_text(it.get("content", ""))
        return ""

    for step in trace:
        if not isinstance(step, dict):
            continue

        stage = step.get("stage")

        if stage == "tool_outputs" and attach_tool_outputs:
            outs = step.get("tool_outputs")
            if isinstance(outs, list):
                pending_tool_outputs.extend(outs)
            continue

        if stage == "model_output":
            out_text = _as_text(step.get("output_text", "")) or ""
            # 只处理有自然语言输出的 model_output（function_call-only 的跳过）
            if not out_text.strip():
                continue

            q = last_user_text(step.get("input_items"))
            pairs.append({
                "question": q,
                "answer": out_text,
                "tool_outputs": pending_tool_outputs if attach_tool_outputs else [],
                "raw_step": step,
            })
            pending_tool_outputs = []

    return pairs

def extract_fields(resp: Any) -> Dict[str, Any]:
    """
    Try best to extract:
      assistant_text, edge_obs, actions, trace, qa_pairs, raw
    """
    if not isinstance(resp, dict):
        return {"assistant_text": str(resp), "edge_obs": None, "actions": None, "trace": None, "qa_pairs": [], "raw": resp}

    assistant_text = (
        resp.get("assistant_text")
        or resp.get("assistant")
        or resp.get("output_text")
        or resp.get("text")
        or ""
    )

    extra = resp.get("extra") if isinstance(resp.get("extra"), dict) else {}

    edge_obs = (
        extra.get("edge_obs")
        or resp.get("obs")
        or resp.get("edge_obs")
        or _dig(resp, ("extra", "edge_obs"))
        or _dig(resp, ("extra", "obs"))
    )

    actions = (
        extra.get("actions")
        or resp.get("actions")
        or _dig(resp, ("extra", "actions"))
    )

    trace = (
        extra.get("trace")
        or resp.get("trace")
        or _dig(resp, ("extra", "trace"))
    )
    if trace is None:
        trace = _dig(resp, ("extra", "extra", "trace"))

    qa_pairs = trace_to_qa_pairs(
        trace,
        ignore_edge_obs_question=st.session_state.get("trace_question_ignore_edge_obs", True),
        attach_tool_outputs=st.session_state.get("trace_attach_tool_outputs", True),
    )

    return {
        "assistant_text": assistant_text,
        "edge_obs": edge_obs,
        "actions": actions,
        "trace": trace,
        "qa_pairs": qa_pairs,
        "raw": resp,
    }


def append_trace_into_chat(fields: Dict[str, Any], sid: str) -> None:
    """
    Insert trace-derived Q/A into chat stream for ChatGPT-like feel.
    """
    qa_pairs = fields.get("qa_pairs") or []
    if not qa_pairs:
        return

    inject = st.session_state.get("inject_trace_into_chat", True)
    show_tool_msgs = st.session_state.get("show_tool_messages_in_chat", True)

    if not inject:
        return

    for qa in qa_pairs:
        q = (qa.get("question") or "").strip()
        a = (qa.get("answer") or "").strip()
        tool_outs = qa.get("tool_outputs") or []

        # 可选：把 trace 内的 question 也展示出来（更像“模型在内部自问自答”）
        # 这里默认不重复展示 user（因为用户已经在 chat 里有一条了）
        # 你如果想显示也可以解除注释：
        # if q:
        #     st.session_state["chat"].append({"role": "user", "text": q, "meta": {"sid": sid}, "kind": "trace_question"})

        if show_tool_msgs and tool_outs:
            st.session_state["chat"].append({
                "role": "tool",
                "text": jdump(tool_outs),
                "meta": {"sid": sid, "label": "tool outputs"},
                "kind": "tool_outputs",
            })

        if a:
            st.session_state["chat"].append({
                "role": "assistant",
                "text": a,
                "meta": {"sid": sid, "from": "trace"},
                "kind": "trace_answer",
            })


# =========================================================
# Sidebar
# =========================================================
with st.sidebar:
    st.title("UAV Agent UI")

    st.text_input("Cloud URL", key="cloud_url")
    st.text_input("SID (editable)", key="sid_input", placeholder="留空则自动创建")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Use SID"):
            st.session_state["sid_current"] = st.session_state["sid_input"].strip()
            st.session_state["chat"] = []
            st.session_state["last"] = {}
            st.rerun()

    with col2:
        if st.button("New Session"):
            base = st.session_state["cloud_url"]
            try:
                sid = create_session(base)
                st.session_state["sid_current"] = sid
                st.session_state["sid_pending"] = sid
                st.session_state["chat"] = []
                st.session_state["last"] = {}
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.selectbox("Mode", ["CHAT", "AUTO"], key="mode")

    st.divider()

    st.checkbox("Show trace Q&A panel (right)", key="show_trace_qa")
    st.checkbox("Trace question: ignore EDGE_OBS blocks", key="trace_question_ignore_edge_obs")
    st.checkbox("Trace: attach tool outputs to next answer", key="trace_attach_tool_outputs")
    st.checkbox("Inject trace into main chat (left)", key="inject_trace_into_chat")
    st.checkbox("Show tool outputs as chat messages", key="show_tool_messages_in_chat")

    st.divider()

    if st.button("Clear UI"):
        st.session_state["chat"] = []
        st.session_state["last"] = {}
        st.rerun()

    st.caption("说明：左侧使用 chat_input，避免 msg_input 生命周期报错；SID 同步逻辑保留。")


# =========================================================
# Main layout
# =========================================================
left, right = st.columns([1.05, 1.0], gap="large")

with left:
    st.subheader("Chat")

    # ---- render chat history (old -> new, like ChatGPT) ----
    for item in st.session_state["chat"]:
        role = item.get("role", "assistant")
        text = item.get("text", "")
        meta = item.get("meta") or {}
        kind = item.get("kind") or ""

        if role == "tool":
            # tool message: render as assistant bubble but with code block
            with st.chat_message("assistant"):
                label = (meta.get("label") or "tool").strip()
                st.markdown(f"**🛠 {label}**")
                st.code(text or "", language="json")
        else:
            with st.chat_message("user" if role == "user" else "assistant"):
                st.write(text or "")
                # debug meta (optional)
                if meta:
                    with st.expander("meta", expanded=False):
                        st.code(jdump({"kind": kind, **meta}), language="json")

    # ---- input at bottom (ChatGPT-like) ----
    prompt = st.chat_input("输入：开始巡逻 / pause automation / ...")

    if prompt is not None:
        base = st.session_state["cloud_url"]
        mode = st.session_state["mode"]
        text = (prompt or "").strip()

        if not text:
            st.warning("消息不能为空")
        else:
            try:
                sid = get_active_sid(base)

                # show user message
                st.session_state["chat"].append({"role": "user", "text": text, "meta": {"mode": mode, "sid": sid}, "kind": "user"})

                # request
                resp = api_post(base, f"/sessions/{sid}/chat", body={"message": text, "mode": mode})
                fields = extract_fields(resp)
                st.session_state["last"] = fields

                # Option A: inject trace Q/A + tool outputs into chat (ChatGPT-like)
                append_trace_into_chat(fields, sid)

                # Option B: also show the final assistant_text (if it's not already identical to last trace answer)
                final_text = (fields.get("assistant_text") or "").strip()
                if final_text:
                    # 避免和 trace 最后一条 answer 重复
                    last_trace = ""
                    qa_pairs = fields.get("qa_pairs") or []
                    if qa_pairs:
                        last_trace = ((qa_pairs[-1].get("answer") or "").strip())

                    if final_text != last_trace:
                        st.session_state["chat"].append({
                            "role": "assistant",
                            "text": final_text,
                            "meta": {"sid": sid, "from": "final"},
                            "kind": "final",
                        })

                st.rerun()

            except Exception as e:
                st.error(f"请求失败：{e}")


with right:
    st.subheader("Debug Panels")

    last = st.session_state.get("last") or {}
    edge_obs = last.get("edge_obs")
    actions = last.get("actions")
    trace = last.get("trace")
    qa_pairs = last.get("qa_pairs") or []
    raw = last.get("raw")

    if st.session_state.get("show_trace_qa", True):
        with st.expander("LLM Q&A (from trace)", expanded=True):
            if not qa_pairs:
                st.write("(no qa pairs parsed from trace)")
            else:
                for idx, qa in enumerate(qa_pairs):
                    q = qa.get("question", "")
                    a = qa.get("answer", "")
                    tool_outs = qa.get("tool_outputs") or []

                    st.markdown(f"**Turn #{idx}**")

                    with st.chat_message("user"):
                        st.write(q or "(empty user)")

                    if tool_outs:
                        with st.expander("tool outputs", expanded=False):
                            st.code(jdump(tool_outs), language="json")

                    with st.chat_message("assistant"):
                        st.write(a or "(empty answer)")

                    st.divider()

    with st.expander("Latest edge_obs", expanded=True):
        st.code(jdump(edge_obs), language="json")

    with st.expander("Actions (what executed)", expanded=True):
        st.code(jdump(actions), language="json")

    with st.expander("Trace timeline (LLM steps)", expanded=False):
        if isinstance(trace, list) and trace:
            for i, step in enumerate(trace):
                stage = step.get("stage", f"step_{i}") if isinstance(step, dict) else f"step_{i}"
                with st.expander(f"#{i}  {stage}", expanded=(i >= len(trace) - 2)):
                    st.code(jdump(step), language="json")
        else:
            st.write("(no trace)")

    with st.expander("Raw response", expanded=False):
        st.code(jdump(raw), language="json")
