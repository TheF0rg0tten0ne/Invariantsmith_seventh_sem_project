"""
Thin wrapper around the Invariantsmith API.

Every call here can block on network/model inference, so the UI layer
(editor_widget.py, main_window.py) always runs these through a
QThreadPool worker -- never directly on the GUI thread.
"""
import requests

from . import config


class ApiError(Exception):
    def __init__(self, message: str, stale: bool = False):
        super().__init__(message)
        self.stale = stale  # True for a 409 "stale_diff" -- retrying won't help, Regenerate will


class InvariantsmithClient:
    def __init__(self, base_url: str = config.API_BASE_URL):
        self.base_url = base_url
        self.session_id: str | None = None

    def ensure_session(self) -> str:
        if not self.session_id:
            r = requests.get(f"{self.base_url}/session/new", timeout=10)
            r.raise_for_status()
            self.session_id = r.json()["session_id"]
        return self.session_id

    def analyze(self, file_path: str, code: str, language: str | None = None) -> dict:
        r = requests.post(f"{self.base_url}/analyze", json={
            "session_id": self.ensure_session(),
            "file_path": file_path,
            "code": code,
            "language": language,
        }, timeout=10)
        r.raise_for_status()
        return r.json()  # {"errors": [...], "detected_language": "..."}

    def suggest_fix(self, file_path: str, code: str, error_type: str,
                     error_message: str, language: str | None = None,
                     line: int | None = None) -> dict:
        r = requests.post(f"{self.base_url}/suggest_fix", json={
            "session_id": self.ensure_session(),
            "file_path": file_path,
            "code": code,
            "error_type": error_type,
            "error_message": error_message,
            "line": line,
            "language": language,
        }, timeout=config.MODEL_REQUEST_TIMEOUT_S)  # must stay >= server's LLAMA_TIMEOUT_CEILING_S
        if r.status_code == 503:
            raise ApiError("Model not loaded on the server. Run scripts/download_model.sh.")
        r.raise_for_status()
        return r.json()

    def apply_fix(self, file_path: str, action_id: int, code: str, diff: str,
                  outcome: str = "accepted") -> str:
        r = requests.post(f"{self.base_url}/apply_fix", json={
            "session_id": self.ensure_session(),
            "file_path": file_path,
            "action_id": action_id,
            "code": code,
            "diff": diff,
            "outcome": outcome,
        }, timeout=10)
        if r.status_code == 409:
            detail = {}
            try:
                detail = r.json().get("detail", {})
            except ValueError:
                pass
            message = detail.get("message") if isinstance(detail, dict) else None
            raise ApiError(message or "This fix no longer matches the current code.", stale=True)
        r.raise_for_status()
        return r.json()["code"]

    def reject_fix(self, action_id: int) -> None:
        requests.post(f"{self.base_url}/reject_fix", params={"action_id": action_id}, timeout=10)

    def explain(self, file_path: str, code: str, error_type: str, error_message: str,
                language: str | None = None) -> str:
        r = requests.post(f"{self.base_url}/explain", json={
            "session_id": self.ensure_session(),
            "file_path": file_path,
            "code": code,
            "error_type": error_type,
            "error_message": error_message,
            "language": language,
        }, timeout=config.MODEL_REQUEST_TIMEOUT_S)
        r.raise_for_status()
        return r.json()["explanation"]

    def detect_language(self, code: str, file_path: str | None = None) -> str:
        r = requests.post(f"{self.base_url}/detect_language", json={
            "code": code,
            "file_path": file_path,
        }, timeout=10)
        r.raise_for_status()
        return r.json()["language"]

    def languages(self) -> list[dict]:
        r = requests.get(f"{self.base_url}/languages", timeout=10)
        r.raise_for_status()
        return r.json()["languages"]

    def convert(self, file_path: str, code: str, target_language: str,
                source_language: str | None = None) -> dict:
        r = requests.post(f"{self.base_url}/convert", json={
            "session_id": self.ensure_session(),
            "file_path": file_path,
            "code": code,
            "target_language": target_language,
            "source_language": source_language,
        }, timeout=config.MODEL_REQUEST_TIMEOUT_S)  # must stay >= server's LLAMA_TIMEOUT_CEILING_S
        if r.status_code == 503:
            raise ApiError("Model not loaded on the server. Run scripts/download_model.sh.")
        r.raise_for_status()
        return r.json()

    def convert_apply(self, file_path: str, action_id: int, outcome: str = "accepted") -> None:
        requests.post(f"{self.base_url}/convert/apply", json={
            "session_id": self.ensure_session(),
            "file_path": file_path,
            "action_id": action_id,
            "outcome": outcome,
        }, timeout=10)

    def history(self, file_path: str | None = None) -> list[dict]:
        r = requests.get(f"{self.base_url}/history",
                          params={"file_path": file_path} if file_path else {}, timeout=10)
        r.raise_for_status()
        return r.json()["history"]

    def themes(self) -> list[dict]:
        r = requests.get(f"{self.base_url}/themes", timeout=10)
        r.raise_for_status()
        return r.json()["themes"]

    def model_status(self) -> dict:
        r = requests.get(f"{self.base_url}/model/status", timeout=10)
        r.raise_for_status()
        return r.json()
