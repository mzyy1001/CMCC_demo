import os

EDGE_BASE_URL = os.getenv("EDGE_BASE_URL", "http://127.0.0.1:8001")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
AUTO_INTERVAL_S = float(os.getenv("AUTO_INTERVAL_S", "2.0"))
EDGE_BASE_URL = "http://127.0.0.1:8001" 