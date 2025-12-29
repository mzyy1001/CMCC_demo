from datetime import datetime
import json
from typing import Any, Dict, Optional

def log_chat(
    sid: str,
    user: str,
    assistant: str,
    extra: Optional[Dict[str, Any]] = None,
):
    print("[LOG] Chat log for session", sid)

    with open("chat_log.jsonl", "a", encoding="utf-8") as f:
        record = {
            "time": datetime.now().isoformat(),
            "session": sid,
            "user": user,
            "assistant": assistant,
            "extra": extra or {},
        }
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
