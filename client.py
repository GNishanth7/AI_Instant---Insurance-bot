from __future__ import annotations

from typing import Any

import requests


class BackendUnavailableError(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


class PolicyApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def list_plans(self) -> list[dict[str, Any]]:
        return self._request("GET", "/plans")

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        return self._request("GET", f"/plans/{plan_id}")

    def rebuild_plan(self, plan_id: str) -> dict[str, Any]:
        return self._request("POST", f"/plans/{plan_id}/rebuild")

    def chat(self, plan_id: str, message: str, session_id: str | None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/chat",
            json={
                "plan_id": plan_id,
                "message": message,
                "session_id": session_id,
            },
        )

    def reset_session(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{session_id}/reset")

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = requests.request(
                method=method,
                url=f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise BackendUnavailableError(
                f"Backend request failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            detail = self._extract_error_detail(response)
            raise ApiError(detail)

        return response.json()

    @staticmethod
    def _extract_error_detail(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or "Backend request failed."

        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        return response.text or "Backend request failed."
