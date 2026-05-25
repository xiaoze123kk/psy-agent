from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class SmokeCase:
    id: str
    question: str
    expected_date: str
    expected_patterns: tuple[str, ...]
    expected_source_hosts: tuple[str, ...]


@dataclass(frozen=True)
class Diagnosis:
    layer: str
    reason: str


CASES: tuple[SmokeCase, ...] = (
    SmokeCase(
        id="zhang_xuefeng_death_time",
        question="张雪峰去世时间是什么？",
        expected_date="2026年3月24日15时50分",
        expected_patterns=(r"2026\s*年\s*3\s*月\s*24\s*日\s*15\s*时\s*50\s*分",),
        expected_source_hosts=("chisa.edu.cn", "finance.sina.com.cn", "news.sina.com.cn"),
    ),
    SmokeCase(
        id="trump_china_visit",
        question="特朗普访华是什么时候？",
        expected_date="2026年5月13日至15日",
        expected_patterns=(
            r"2026\s*年\s*5\s*月\s*13\s*日\s*(?:至|到|—|-|~)\s*(?:5\s*月\s*)?15\s*日",
            r"2026-0?5-13\s*(?:至|到|-|~)\s*(?:2026-)?0?5-15",
        ),
        expected_source_hosts=("news.cctv.com", "cn.chinadiplomacy.org.cn", "paper.people.com.cn"),
    ),
)


def contains_expected_date(text: object, case: SmokeCase) -> bool:
    body = str(text or "")
    if not body.strip():
        return False
    return any(re.search(pattern, body) for pattern in case.expected_patterns)


def contains_expected_source(text: object, case: SmokeCase) -> bool:
    body = str(text or "")
    if not body.strip():
        return False
    urls = re.findall(r"https?://[^\s\"'<>]+", body)
    hosts = {
        (urlparse(url).hostname or "").lower()
        for url in urls
    }
    for expected_host in case.expected_source_hosts:
        host = expected_host.lower()
        if any(actual == host or actual.endswith(f".{host}") for actual in hosts):
            return True
    return False


def _trim(text: object, *, limit: int = 500) -> str:
    body = " ".join(str(text or "").split())
    if len(body) <= limit:
        return body
    return f"{body[: limit - 3].rstrip()}..."


def _json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {_trim(detail)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc

    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"{method} {url} returned non-object JSON")
    return data


def _wait_http(url: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers={"Accept": "*/*"}, method="GET")
            with urllib.request.urlopen(request, timeout=3) as response:
                if 200 <= int(response.status) < 500:
                    return
        except Exception as exc:  # noqa: BLE001 - this is a smoke probe.
            last_error = str(exc)
            time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}: {_trim(last_error, limit=160)}")


def _assistant_text(chat_payload: dict[str, Any]) -> str:
    assistant = chat_payload.get("assistant_message")
    if isinstance(assistant, dict):
        return str(assistant.get("assistant_text") or assistant.get("content") or "")
    return str(chat_payload.get("assistant_text") or "")


def _tooling_summary(chat_payload: dict[str, Any]) -> dict[str, Any]:
    trace = chat_payload.get("trace_summary")
    if not isinstance(trace, dict):
        return {}
    tooling = trace.get("tooling")
    return tooling if isinstance(tooling, dict) else {}


def diagnose_failure(
    case: SmokeCase,
    *,
    provider_text: str,
    provider_error: str | None,
    chat_payload: dict[str, Any],
) -> Diagnosis:
    if provider_error:
        return Diagnosis("provider", f"direct provider probe errored: {provider_error}")
    if not contains_expected_date(provider_text, case):
        return Diagnosis("provider", f"direct provider probe did not contain expected date {case.expected_date}")
    if not contains_expected_source(provider_text, case):
        return Diagnosis(
            "provider",
            "direct provider probe did not include a trusted direct source "
            f"({', '.join(case.expected_source_hosts)})",
        )

    tooling = _tooling_summary(chat_payload)
    tool_names = [str(name) for name in tooling.get("tool_names", [])] if isinstance(tooling.get("tool_names"), list) else []
    status_counts = tooling.get("status_counts")
    if not isinstance(status_counts, dict):
        status_counts = {}
    completed_count = int(status_counts.get("completed") or 0)
    if "web_search" not in tool_names or completed_count < 1:
        return Diagnosis(
            "prefetch",
            f"provider had {case.expected_date}, but chat trace did not show completed web_search prefetch",
        )

    assistant_text = _assistant_text(chat_payload)
    if not contains_expected_date(assistant_text, case):
        return Diagnosis(
            "fallback",
            f"prefetch completed and provider had {case.expected_date}, but assistant answer missed expected date",
        )
    return Diagnosis("fallback", "chat payload failed an outer smoke assertion after expected date was present")


def _provider_probe(case: SmokeCase, *, timeout_seconds: float) -> tuple[str, str, str | None]:
    try:
        from app.services.search_service import search_web
        from app.services.tooling import _prefetch_search_query

        query = _prefetch_search_query(case.question)
        results, error = search_web(query, max_results=5, timeout_seconds=timeout_seconds)
        provider_text = "\n".join(
            f"{result.title}\n{result.url}\n{result.snippet}"
            for result in results
        )
        return query, provider_text, error
    except Exception as exc:  # noqa: BLE001 - smoke should classify dependency failures.
        return case.question, "", str(exc)


def _chat_probe(case: SmokeCase, *, backend_url: str, token: str, timeout_seconds: float) -> dict[str, Any]:
    thread = _json_request(
        "POST",
        f"{backend_url.rstrip('/')}/api/v1/chat/threads",
        payload={"mode": "companion", "title": f"live smoke {case.id}"},
        token=token,
        timeout_seconds=timeout_seconds,
    )
    thread_id = str(thread.get("thread_id") or "")
    if not thread_id:
        raise RuntimeError(f"chat thread creation did not return thread_id: {_trim(thread)}")

    return _json_request(
        "POST",
        f"{backend_url.rstrip('/')}/api/v1/chat/threads/{thread_id}/messages",
        payload={
            "content": case.question,
            "client_message_id": f"live-smoke-{case.id}-{uuid4()}",
        },
        token=token,
        timeout_seconds=timeout_seconds,
    )


def run_live_smoke(args: argparse.Namespace) -> int:
    backend_url = str(args.backend_url).rstrip("/")
    frontend_url = str(args.frontend_url).rstrip("/")

    from app.core.config import load_settings

    settings = load_settings()
    print("[live-smoke] Search provider diagnostics")
    print(f"[live-smoke] provider={settings.search_provider}")
    print(f"[live-smoke] bing_key_configured={'yes' if settings.bing_search_api_key else 'no'}")
    print(f"[live-smoke] bing_endpoint={settings.bing_search_endpoint}")
    print("[live-smoke] fallback expectation=bing_web/sogou_web/baidu_mobile/ddg for Chinese time-sensitive queries")

    print("[live-smoke] Waiting for local services...")
    _wait_http(f"{backend_url}/health", timeout_seconds=args.timeout_seconds)
    _wait_http(frontend_url, timeout_seconds=args.timeout_seconds)
    _wait_http(str(args.milvus_health_url), timeout_seconds=args.timeout_seconds)
    print("[live-smoke] Health checks passed: backend, frontend, Milvus")

    session = _json_request(
        "POST",
        f"{backend_url}/api/v1/auth/dev-session",
        payload={},
        timeout_seconds=args.timeout_seconds,
    )
    token = str(session.get("access_token") or "")
    if not token:
        raise RuntimeError("dev-session did not return access_token")

    failures: list[tuple[SmokeCase, Diagnosis, str]] = []
    for case in CASES:
        print(f"[live-smoke] Case {case.id}: {case.question}")
        query, provider_text, provider_error = _provider_probe(case, timeout_seconds=args.provider_timeout_seconds)
        provider_has_date = contains_expected_date(provider_text, case)
        provider_has_source = contains_expected_source(provider_text, case)
        provider_status = "ok" if provider_has_date and provider_has_source and not provider_error else "missing_expected_date"
        if provider_has_date and not provider_has_source and not provider_error:
            provider_status = "missing_trusted_source"
        if provider_error:
            provider_status = f"error: {provider_error}"
        print(f"[live-smoke] Provider query: {query}")
        print(f"[live-smoke] Provider status: {provider_status}")

        chat_payload: dict[str, Any]
        try:
            chat_payload = _chat_probe(case, backend_url=backend_url, token=token, timeout_seconds=args.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - report as smoke failure with context.
            chat_payload = {"assistant_message": None, "trace_summary": {}, "request_error": str(exc)}

        answer = _assistant_text(chat_payload)
        print(f"[live-smoke] Answer: {_trim(answer, limit=360)}")
        if contains_expected_date(answer, case):
            tooling = _tooling_summary(chat_payload)
            print(f"[live-smoke] PASS {case.id}; tooling={json.dumps(tooling, ensure_ascii=False)}")
            continue

        diagnosis = diagnose_failure(
            case,
            provider_text=provider_text,
            provider_error=provider_error,
            chat_payload=chat_payload,
        )
        request_error = _trim(chat_payload.get("request_error"), limit=220)
        detail = diagnosis.reason if not request_error else f"{diagnosis.reason}; request_error={request_error}"
        print(f"[live-smoke] FAIL {case.id}; layer={diagnosis.layer}; reason={detail}")
        failures.append((case, diagnosis, detail))

    if failures:
        print("[live-smoke] Summary: failed")
        for case, diagnosis, detail in failures:
            print(f"- {case.id}: layer={diagnosis.layer}; expected={case.expected_date}; {detail}")
        return 1

    print("[live-smoke] Summary: passed")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live current-fact smoke checks against the local app.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5173")
    parser.add_argument("--milvus-health-url", default="http://127.0.0.1:9091/healthz")
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--provider-timeout-seconds", type=float, default=8)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run_live_smoke(args)
    except Exception as exc:  # noqa: BLE001 - top-level smoke failure.
        print(f"[live-smoke] ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
