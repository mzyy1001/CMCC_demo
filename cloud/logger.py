from datetime import datetime
import json

def log_chat(sid: str, user_msg: str, reply: str):
    print("[LOG] Chat log for session", sid)
    with open("chat_log.txt", "a", encoding="utf-8") as f:
        f.write("\n" + "="*60 + "\n")
        f.write(f"time: {datetime.now()}\n")
        f.write(f"session: {sid}\n")
        f.write(f"user: {user_msg}\n")
        f.write(f"assistant: {reply}\n")
