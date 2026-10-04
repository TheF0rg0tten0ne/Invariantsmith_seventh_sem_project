"""
Quick smoke test against a running Invariantsmith server.
Run with the server already up: uvicorn server.main:app --host 127.0.0.1 --port 8731

    python scripts/smoke_test.py
"""
import requests

BASE = "http://127.0.0.1:8731"

# 1. new session
r = requests.get(f"{BASE}/session/new")
r.raise_for_status()
session_id = r.json()["session_id"]
print("session_id:", session_id)

code = "def foo():\n    return bar\n"

# 2. analyze
r = requests.post(f"{BASE}/analyze", json={
    "session_id": session_id,
    "file_path": "test.py",
    "code": code,
})
print("\n/analyze ->", r.status_code)
print(r.json())

# 3. suggest_fix (this is the real test — hits the model)
r = requests.post(f"{BASE}/suggest_fix", json={
    "session_id": session_id,
    "file_path": "test.py",
    "code": code,
    "error_type": "NameError",
    "error_message": "undefined name 'bar'",
})
print("\n/suggest_fix ->", r.status_code)
print(r.json())
