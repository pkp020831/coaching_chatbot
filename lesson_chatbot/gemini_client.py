"""Gemini generateContent REST API의 최소 JSON 클라이언트."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
GENERATE_CONTENT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiAPIError(RuntimeError):
    """안전하게 사용자에게 전달할 수 있는 Gemini 호출 오류."""


@dataclass(frozen=True)
class GeminiJSONResponse:
    data: dict[str, Any]
    usage: dict[str, Any]
    model_version: str | None
    latency_ms: float


class GeminiJSONClient:
    """구조화 JSON 응답만 요청하는 서버 측 Gemini 클라이언트."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_GEMINI_MODEL,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        request_fn: Callable[..., Any] = urlopen,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("GEMINI_API_KEY가 비어 있습니다.")
        if not model.strip():
            raise ValueError("Gemini 모델명이 비어 있습니다.")
        if max_retries < 0:
            raise ValueError("max_retries는 0 이상이어야 합니다.")
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._request_fn = request_fn
        self._sleep_fn = sleep_fn

    def generate_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        response_schema: dict[str, Any],
        temperature: float = 0.2,
        max_output_tokens: int = 1400,
    ) -> GeminiJSONResponse:
        body = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": response_schema,
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        request = Request(
            GENERATE_CONTENT_URL.format(model=quote(self.model, safe="-_.")),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        started = time.perf_counter()
        payload = self._send_with_retry(request)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        data = self._extract_json(payload)
        usage = payload.get("usageMetadata")
        return GeminiJSONResponse(
            data=data,
            usage=usage if isinstance(usage, dict) else {},
            model_version=str(payload.get("modelVersion")) if payload.get("modelVersion") else None,
            latency_ms=latency_ms,
        )

    def _send_with_retry(self, request: Request) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                with self._request_fn(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                retryable = error.code in (408, 429) or 500 <= error.code <= 599
                if not retryable or attempt >= self.max_retries:
                    if error.code in (401, 403):
                        raise GeminiAPIError("Gemini API 인증에 실패했습니다. API 키를 확인해 주세요.") from error
                    if error.code == 429:
                        raise GeminiAPIError("Gemini API 사용 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.") from error
                    raise GeminiAPIError(f"Gemini API 요청에 실패했습니다. (HTTP {error.code})") from error
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
                if attempt >= self.max_retries:
                    raise GeminiAPIError("Gemini API 서버에 연결하지 못했습니다.") from error
            delay = (2**attempt) + random.uniform(0.0, 0.25)
            self._sleep_fn(delay)
        raise GeminiAPIError("Gemini API 요청을 완료하지 못했습니다.")

    @staticmethod
    def _extract_json(payload: dict[str, Any]) -> dict[str, Any]:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = payload.get("promptFeedback")
            reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
            if reason:
                raise GeminiAPIError("안전 정책에 따라 답변을 생성할 수 없는 질문입니다.")
            raise GeminiAPIError("Gemini가 답변 후보를 반환하지 않았습니다.")

        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise GeminiAPIError("Gemini 응답 형식이 올바르지 않습니다.")
        finish_reason = str(candidate.get("finishReason") or "")
        if finish_reason in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
            raise GeminiAPIError("안전 정책에 따라 답변을 생성할 수 없는 질문입니다.")
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise GeminiAPIError("Gemini가 빈 답변을 반환했습니다.")
        text = "".join(
            str(part.get("text", "")) for part in parts if isinstance(part, dict)
        ).strip()
        if not text:
            raise GeminiAPIError("Gemini가 빈 답변을 반환했습니다.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise GeminiAPIError("Gemini의 구조화 답변을 해석하지 못했습니다.") from error
        if not isinstance(data, dict):
            raise GeminiAPIError("Gemini의 구조화 답변이 JSON 객체가 아닙니다.")
        return data
