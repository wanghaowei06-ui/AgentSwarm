#!/usr/bin/env python3
"""Thin, secret-safe setup for one isolated Higress Bailian AI route.

Only the provider and dedicated path route are owned here. Worker consumer
authorization is intentionally omitted: Controller reconciliation fills it
from the Worker CR's modelProvider through the native path.
"""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import stat
import sys
import time
from typing import Any
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.parse import urlsplit

PROVIDER = "testweaver-bailian"
ROUTE = "testweaver-bailian-route"
PATH = "/testweaver-bailian/v1"
SOURCE_MODEL = "deepseek-v4-flash"

class Failure(RuntimeError):
    def __init__(self, kind: str, status: int | None = None):
        self.kind, self.status = kind, status
        super().__init__(kind)

def parse_protected_env_text(text: str) -> dict[str, str]:
    """Parse KEY=value without evaluating shell syntax."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            continue
        try:
            values = shlex.split(raw.strip(), comments=False, posix=True)
        except ValueError as exc:
            raise Failure("protected_env_parse") from exc
        if len(values) != 1:
            raise Failure("protected_env_parse")
        result[key] = values[0]
    return result

def read_protected_env(path: str, names: tuple[str, ...]) -> tuple[dict[str, str], dict[str, Any]]:
    p = Path(path)
    try:
        st = p.stat()
        mode = stat.S_IMODE(st.st_mode)
        if st.st_uid != 0 or mode & 0o077:
            raise Failure("protected_env_permissions")
        values = parse_protected_env_text(p.read_text(encoding="utf-8"))
    except Failure:
        raise
    except (OSError, UnicodeError) as exc:
        raise Failure("protected_env_unavailable") from exc
    if any(not values.get(name) for name in names):
        raise Failure("protected_env_missing_names")
    return values, {"path": path, "owner_uid": st.st_uid, "mode": f"{mode:04o}"}

def classify_bailian_endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise Failure("bailian_endpoint_invalid")
    return "qwen" if "dashscope.aliyuncs.com" in host and "compatible-mode" in parsed.path.lower() else "openai"

def build_provider_payload(name: str, base_url: str, api_key: str, model: str) -> dict[str, Any]:
    provider_type = classify_bailian_endpoint(base_url)
    if not name or not api_key or not model:
        raise Failure("provider_input_missing")
    raw = (
        {"qwenEnableSearch": False, "qwenEnableCompatible": True, "qwenFileIds": [], "agentteamsMode": True}
        if provider_type == "qwen"
        else {"apiUrl": base_url, "agentteamsMode": True}
    )
    return {
        "type": provider_type,
        "name": name,
        "tokens": [api_key],
        "modelMapping": {},
        "protocol": "openai/v1",
        "tokenFailoverConfig": {"enabled": False},
        "rawConfigs": raw,
    }


def build_route_payload(
    route_name: str,
    domain: str,
    provider_name: str,
    source_model: str,
    target_model: str,
    path: str = PATH,
) -> dict[str, Any]:
    if not all((route_name, domain, provider_name, source_model, target_model)):
        raise Failure("route_input_missing")
    if not path.startswith("/") or path == "/":
        raise Failure("route_path_invalid")
    return {
        "name": route_name,
        "domains": [domain],
        "pathPredicate": {"matchType": "PRE", "matchValue": path, "caseSensitive": False},
        "upstreams": [{
            "provider": provider_name,
            "weight": 100,
            "modelMapping": {source_model: target_model},
        }],
        "modelPredicates": [{"matchType": "EXACT", "matchValue": source_model, "caseSensitive": False}],
        "authConfig": {"enabled": True, "allowedCredentialTypes": ["key-auth"]},
    }


def _data(value: Any) -> Any:
    return value.get("data") if isinstance(value, dict) and "data" in value else value


def provider_readback(value: Any, expected_name: str, expected_type: str) -> dict[str, Any]:
    item = _data(value)
    if not isinstance(item, dict) or item.get("name") != expected_name or item.get("type") != expected_type:
        raise Failure("provider_readback_mismatch")
    tokens, raw = item.get("tokens"), item.get("rawConfigs")
    return {
        "name": item["name"],
        "type": item["type"],
        "protocol": item.get("protocol"),
        "token_present": isinstance(tokens, list) and bool(tokens),
        "token_count": len(tokens) if isinstance(tokens, list) else 0,
        "raw_config_keys": sorted(raw) if isinstance(raw, dict) else [],
    }


def route_readback(value: Any, expected: dict[str, Any]) -> dict[str, Any]:
    item = _data(value)
    try:
        upstream, auth = item["upstreams"][0], item["authConfig"]
        predicate = {"matchType": "EXACT", "matchValue": expected["source_model"], "caseSensitive": False}
        good = (
            isinstance(item, dict)
            and item["name"] == expected["name"]
            and item["pathPredicate"]["matchValue"] == expected["path"]
            and upstream["provider"] == expected["provider"]
            and upstream["modelMapping"][expected["source_model"]] == expected["target_model"]
            and predicate in item["modelPredicates"]
            and auth["enabled"] is True
            and auth["allowedCredentialTypes"] == ["key-auth"]
        )
    except (KeyError, IndexError, TypeError):
        good = False
    if not good:
        raise Failure("route_readback_mismatch")
    return {"name": item["name"], "path": expected["path"], "provider": expected["provider"],
            "model_mapping_keys": [expected["source_model"]], "auth_scope": "controller_managed"}


def probe(url: str, host: str, path: str, key: str, provider: str, model: str, stage: str, timeout: float) -> dict[str, Any]:
    request_body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with one token: ok"}],
        "max_tokens": 1, "temperature": 0, "stream": False,
    }, separators=(",", ":")).encode()
    request = Request(url.rstrip("/") + path + "/chat/completions", data=request_body, method="POST", headers={
        "Accept": "application/json", "Content-Type": "application/json",
        "Authorization": f"Bearer {key}", "Host": host,
    })
    started, raw, status, error = time.monotonic(), b"", None, None
    try:
        with build_opener().open(request, timeout=timeout) as response:
            status, raw = int(response.status), response.read()
    except HTTPError as exc:
        status, raw, error = int(exc.code), exc.read(), "http_error"
    except (TimeoutError, URLError, OSError) as exc:
        error = type(exc).__name__.lower()
    try:
        parsed = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = {}
    usage = parsed.get("usage", {}) if isinstance(parsed, dict) else {}
    return {
        "stage": stage, "provider": provider, "model": model, "http_status": status,
        "usage": {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(usage.get(k), int)},
        "latency_ms": int((time.monotonic() - started) * 1000),
        "response_sha256": hashlib.sha256(raw).hexdigest(), "error_class": error,
    }


def console(opener, base: str, method: str, path: str, payload: Any = None, timeout: float = 15, allow_404: bool = False) -> Any:
    data = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        with opener.open(Request(base.rstrip("/") + path, data=data, headers=headers, method=method), timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode()) if raw else {}
    except HTTPError as exc:
        exc.read()
        if allow_404 and exc.code == 404:
            return None
        raise Failure(f"console_{method.lower()}", int(exc.code)) from None
    except (TimeoutError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Failure(f"console_{method.lower()}_{type(exc).__name__.lower()}") from None


def main(args: argparse.Namespace) -> int:
    receipt: dict[str, Any] = {"schema": "testweaver.higress-route/v1", "run_id": args.run_id, "status": "BLOCKED",
                               "provider": PROVIDER, "route": ROUTE, "path": PATH, "created": [], "probes": []}
    created: list[tuple[str, str]] = []
    try:
        providers, pmeta = read_protected_env(args.providers_env, ("AGENTTEAMS_BAILIAN_BASE_URL", "AGENTTEAMS_BAILIAN_API_KEY", "AGENTTEAMS_BAILIAN_MODEL"))
        admin, ameta = read_protected_env(args.agentteams_env, ("AGENTTEAMS_ADMIN_USER", "AGENTTEAMS_ADMIN_PASSWORD", "AGENTTEAMS_MANAGER_GATEWAY_KEY"))
        receipt["protected_files"] = [pmeta, ameta]
        provider_type = classify_bailian_endpoint(providers["AGENTTEAMS_BAILIAN_BASE_URL"])
        receipt["provider_type"] = provider_type
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        console(opener, args.console_url, "POST", "/session/login", {"username": admin["AGENTTEAMS_ADMIN_USER"], "password": admin["AGENTTEAMS_ADMIN_PASSWORD"]})
        provider_current = console(opener, args.console_url, "GET", f"/v1/ai/providers/{PROVIDER}", allow_404=True)
        route_current = console(opener, args.console_url, "GET", f"/v1/ai/routes/{ROUTE}", allow_404=True)
        if provider_current is not None:
            receipt["provider_readback"] = provider_readback(provider_current, PROVIDER, provider_type)
        if route_current is not None:
            expected = {"name": ROUTE, "path": PATH, "provider": PROVIDER, "source_model": SOURCE_MODEL, "target_model": providers["AGENTTEAMS_BAILIAN_MODEL"]}
            receipt["route_readback"] = route_readback(route_current, expected)
        if provider_current is None:
            created.append(("provider", PROVIDER))
            console(opener, args.console_url, "POST", "/v1/ai/providers", build_provider_payload(PROVIDER, providers["AGENTTEAMS_BAILIAN_BASE_URL"], providers["AGENTTEAMS_BAILIAN_API_KEY"], providers["AGENTTEAMS_BAILIAN_MODEL"]))
            receipt["created"].append("provider")
            receipt["provider_readback"] = provider_readback(console(opener, args.console_url, "GET", f"/v1/ai/providers/{PROVIDER}"), PROVIDER, provider_type)
        if route_current is None:
            created.append(("route", ROUTE))
            console(opener, args.console_url, "POST", "/v1/ai/routes", build_route_payload(ROUTE, args.domain, PROVIDER, SOURCE_MODEL, providers["AGENTTEAMS_BAILIAN_MODEL"]))
            receipt["created"].append("route")
            expected = {"name": ROUTE, "path": PATH, "provider": PROVIDER, "source_model": SOURCE_MODEL, "target_model": providers["AGENTTEAMS_BAILIAN_MODEL"]}
            receipt["route_readback"] = route_readback(console(opener, args.console_url, "GET", f"/v1/ai/routes/{ROUTE}"), expected)
        old = probe(args.gateway_url, args.gateway_host, "/v1", admin["AGENTTEAMS_MANAGER_GATEWAY_KEY"], "deepseek-existing", SOURCE_MODEL, "deepseek_unchanged", args.probe_timeout)
        receipt["probes"].append(old)
        if old["http_status"] is None or not 200 <= old["http_status"] < 300:
            raise Failure("deepseek_probe", old["http_status"])
        receipt["status"] = "APPLIED"
        print(f"APPLIED provider={PROVIDER} type={provider_type} route={ROUTE} path={PATH} bailian_path_probe=DEFERRED deepseek_http={old['http_status']}")
        return 0
    except Failure as exc:
        receipt["error"] = {"kind": exc.kind, "http_status": exc.status}
        for kind, name in reversed(created):
            try:
                console(opener, args.console_url, "DELETE", f"/v1/ai/{'providers' if kind == 'provider' else 'routes'}/{name}")
                receipt.setdefault("cleanup", []).append({"resource": kind, "status": "deleted"})
            except Failure as cleanup:
                receipt.setdefault("cleanup", []).append({"resource": kind, "status": "failed", "kind": cleanup.kind, "http_status": cleanup.status})
        print(f"BLOCKED kind={exc.kind} http_status={exc.status}")
        return 1
    finally:
        Path(args.receipt).parent.mkdir(parents=True, exist_ok=True)
        Path(args.receipt).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--providers-env", default="/etc/agentteams/providers.env")
    p.add_argument("--agentteams-env", default="/etc/agentteams/agentteams.env")
    p.add_argument("--console-url", default="http://127.0.0.1:28001")
    p.add_argument("--gateway-url", default="http://127.0.0.1:28080")
    p.add_argument("--gateway-host", required=True)
    p.add_argument("--domain", required=True)
    p.add_argument("--probe-timeout", type=float, default=20)
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main(parse_args(sys.argv[1:])))
