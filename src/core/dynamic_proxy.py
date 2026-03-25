"""动态代理基础设施。"""

from __future__ import annotations

import copy
import json
import logging
import re
import shlex
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    from curl_cffi import requests as cffi_requests
except Exception:  # pragma: no cover - 仅兜底，测试环境正常会安装依赖
    cffi_requests = None


logger = logging.getLogger(__name__)

AUTO_FIELD_KEYS = {
    "host": ("host", "ip", "server", "address"),
    "port": ("port",),
    "username": ("username", "user"),
    "password": ("password", "pass"),
    "type": ("type", "protocol", "scheme"),
    "proxy_url": ("proxy_url", "proxy", "url", "endpoint"),
}


@dataclass(slots=True)
class DynamicProxyCandidate:
    proxy_url: str
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    source_metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class DynamicProxyRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: Any | None = None
    body_mode: Literal["json", "form", "raw"] = "json"
    timeout_seconds: int = 10


@dataclass(slots=True)
class DynamicProxyProbeResult:
    ok: bool
    proxy_url: str
    egress_ip: str | None = None
    response_time_ms: int | None = None
    error_message: str | None = None


def _extract_path(payload: Any, path: str) -> Any:
    if not path:
        return payload

    current = payload
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _normalize_scheme(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("socks5"):
        return "socks5"
    return "http"


def _build_proxy_url(scheme: str, host: str, port: int, username: str | None = None, password: str | None = None) -> str:
    auth = ""
    if username:
        auth = username
        if password:
            auth = f"{auth}:{password}"
        auth = f"{auth}@"
    return f"{scheme}://{auth}{host}:{port}"


def _candidate_from_proxy_url(proxy_url: str, source_metadata: dict[str, Any] | None = None) -> DynamicProxyCandidate | None:
    text = str(proxy_url or "").strip()
    if not text:
        return None

    if not re.match(r"^(http|socks5)://", text, flags=re.IGNORECASE):
        text = f"http://{text}"

    parsed = urlparse(text)
    if not parsed.hostname:
        return None

    scheme = _normalize_scheme(parsed.scheme)
    port = parsed.port
    if port is None:
        port = 1080 if scheme == "socks5" else 80

    return DynamicProxyCandidate(
        proxy_url=text,
        scheme=scheme,
        host=parsed.hostname,
        port=port,
        username=parsed.username,
        password=parsed.password,
        source_metadata=source_metadata,
    )


def _lookup_object_field(item: dict[str, Any], field: str, mapping: dict[str, Any]) -> Any:
    mapped_key = mapping.get(field)
    if mapped_key:
        return _extract_path(item, str(mapped_key))

    for key in AUTO_FIELD_KEYS.get(field, (field,)):
        if key in item:
            return item[key]
    return None


def _replace_count_placeholder(value: Any, count: int) -> Any:
    if isinstance(value, dict):
        return {k: _replace_count_placeholder(v, count) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_count_placeholder(v, count) for v in value]
    if isinstance(value, str):
        raw = value.strip()
        if raw == "{{count}}":
            return count
        return value.replace("{{count}}", str(count))
    return value


def _extract_content_type(headers: dict[str, Any]) -> str:
    for key, value in headers.items():
        if str(key).lower() == "content-type":
            return str(value).split(";", 1)[0].strip().lower()
    return ""


def _infer_request_body_mode(
    headers: dict[str, Any],
    request_body_template: Any,
) -> Literal["json", "form", "raw"]:
    content_type = _extract_content_type(headers)
    if content_type == "application/x-www-form-urlencoded":
        return "form"
    if content_type == "application/json" or content_type.endswith("+json"):
        return "json"
    if isinstance(request_body_template, str):
        return "raw"
    if isinstance(request_body_template, dict) and set(request_body_template.keys()) == {"raw"}:
        return "raw"
    return "json"


def _parse_curl_body_template(
    raw_body: str,
    headers: dict[str, str],
) -> tuple[Literal["json", "form", "raw"], Any]:
    if not raw_body:
        return (_infer_request_body_mode(headers, None), {})

    inferred_mode = _infer_request_body_mode(headers, raw_body)
    if inferred_mode == "form":
        return ("form", dict(parse_qsl(raw_body, keep_blank_values=True)))

    if inferred_mode == "json":
        try:
            return ("json", json.loads(raw_body))
        except Exception:
            return ("raw", raw_body)

    try:
        return ("json", json.loads(raw_body))
    except Exception:
        pass

    pairs = dict(parse_qsl(raw_body, keep_blank_values=True))
    if pairs and "=" in raw_body:
        return ("form", pairs)

    return ("raw", raw_body)


def _normalize_raw_request_body(request_body_template: Any) -> str:
    if request_body_template is None:
        return ""
    if isinstance(request_body_template, str):
        return request_body_template
    if isinstance(request_body_template, dict) and set(request_body_template.keys()) == {"raw"}:
        return str(request_body_template["raw"])
    return str(request_body_template)


def parse_dynamic_proxy_curl(curl_command: str) -> dict[str, Any]:
    """从 curl 命令解析动态代理请求模板。"""
    tokens = shlex.split(curl_command)
    method = "GET"
    url = ""
    headers: dict[str, str] = {}
    data_chunks: list[str] = []
    force_get = False

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "curl":
            i += 1
            continue

        if token in {"-X", "--request"} and i + 1 < len(tokens):
            method = tokens[i + 1].upper()
            i += 2
            continue

        if token.startswith("-X") and len(token) > 2:
            method = token[2:].upper()
            i += 1
            continue

        if token in {"-G", "--get"}:
            force_get = True
            method = "GET"
            i += 1
            continue

        if token in {"-H", "--header"} and i + 1 < len(tokens):
            header_line = tokens[i + 1]
            if ":" in header_line:
                key, value = header_line.split(":", 1)
                headers[key.strip()] = value.strip()
            i += 2
            continue

        if token in {"-d", "--data", "--data-raw", "--data-binary"} and i + 1 < len(tokens):
            data_chunks.append(tokens[i + 1])
            if method == "GET" and not force_get:
                method = "POST"
            i += 2
            continue

        if token == "--url" and i + 1 < len(tokens):
            url = tokens[i + 1]
            i += 2
            continue

        if not token.startswith("-") and not url:
            url = token

        i += 1

    body_template: Any = {}
    body_mode: Literal["json", "form", "raw"] = _infer_request_body_mode(headers, None)
    if data_chunks:
        raw_body = "&".join(data_chunks)
        body_mode, body_template = _parse_curl_body_template(raw_body, headers)

    return {
        "request_method": method,
        "request_url": url,
        "request_headers_template": headers,
        "request_body_template": body_template,
        "request_body_mode": body_mode,
    }


def build_dynamic_proxy_request(
    request_method: str,
    request_url: str,
    request_headers_template: dict[str, Any] | None,
    request_body_template: Any,
    request_count_param_name: str,
    count: int,
    request_body_mode: Literal["auto", "json", "form", "raw"] | None = None,
    request_timeout_seconds: int = 10,
    api_key: str = "",
    api_key_header: str = "X-API-Key",
) -> DynamicProxyRequest:
    """构造动态代理请求对象，并注入 count。"""
    method = str(request_method or "GET").upper()
    if method not in {"GET", "POST"}:
        raise ValueError("request_method must be GET or POST")

    headers = {
        str(k): str(v)
        for k, v in (request_headers_template or {}).items()
        if v is not None
    }
    if api_key:
        headers[api_key_header] = api_key

    url = request_url
    body: Any | None = None
    body_mode = (
        _infer_request_body_mode(headers, request_body_template)
        if request_body_mode in (None, "", "auto")
        else request_body_mode
    )

    if method == "GET":
        parsed = urlparse(request_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query_template = _replace_count_placeholder(copy.deepcopy(request_body_template), count)
        if isinstance(query_template, dict):
            for key, value in query_template.items():
                query[str(key)] = str(value)
        elif isinstance(query_template, str):
            for key, value in parse_qsl(query_template, keep_blank_values=True):
                query[key] = value
        if request_count_param_name:
            query[request_count_param_name] = str(count)
        url = urlunparse(parsed._replace(query=urlencode(query)))
    else:
        request_body = _replace_count_placeholder(copy.deepcopy(request_body_template), count)
        if body_mode == "raw":
            body = _normalize_raw_request_body(request_body)
        else:
            body = request_body or {}
            if isinstance(body, dict) and request_count_param_name and request_count_param_name not in body:
                body[request_count_param_name] = count

    return DynamicProxyRequest(
        method=method,
        url=url,
        headers=headers,
        body=body,
        body_mode=body_mode,
        timeout_seconds=max(int(request_timeout_seconds or 10), 1),
    )


def parse_dynamic_proxy_candidates(
    payload: Any,
    response_root_field: str,
    response_item_mode: str,
    response_field_mapping: dict[str, Any] | None,
) -> list[DynamicProxyCandidate]:
    """解析动态代理响应，输出标准化候选列表。"""
    mapping = response_field_mapping or {}
    root = _extract_path(payload, response_root_field) if response_root_field else payload

    if root is None:
        return []

    mode = str(response_item_mode or "string_list")
    candidates: list[DynamicProxyCandidate] = []

    if mode == "string_list":
        if isinstance(root, str):
            rows: list[Any] = [root]
        elif isinstance(root, list):
            rows = root
        elif isinstance(root, dict):
            rows = []
            for key in ("data", "items", "list", "proxies", "results", "proxy", "url", "proxy_url", "ip"):
                value = root.get(key)
                if isinstance(value, list):
                    rows = value
                    break
                if isinstance(value, str):
                    rows = [value]
                    break
        else:
            rows = []

        for item in rows:
            if isinstance(item, str):
                candidate = _candidate_from_proxy_url(item)
                if candidate:
                    candidates.append(candidate)
        return candidates

    if mode != "object_list":
        return []

    if isinstance(root, dict):
        for key in ("items", "data", "list", "proxies", "results"):
            value = root.get(key)
            if isinstance(value, list):
                root = value
                break

    if not isinstance(root, list):
        return []

    for item in root:
        if not isinstance(item, dict):
            continue

        proxy_url = _lookup_object_field(item, "proxy_url", mapping)
        host = _lookup_object_field(item, "host", mapping)
        port = _lookup_object_field(item, "port", mapping)
        username = _lookup_object_field(item, "username", mapping)
        password = _lookup_object_field(item, "password", mapping)
        raw_scheme = _lookup_object_field(item, "type", mapping)
        scheme = _normalize_scheme(raw_scheme) if raw_scheme not in (None, "") else None

        candidate: DynamicProxyCandidate | None = None
        if proxy_url:
            candidate = _candidate_from_proxy_url(str(proxy_url), source_metadata=item)

        if candidate is None and host and port:
            try:
                port_int = int(port)
            except Exception:
                continue
            candidate = DynamicProxyCandidate(
                proxy_url=_build_proxy_url(
                    scheme=scheme or "http",
                    host=str(host),
                    port=port_int,
                    username=str(username) if username not in (None, "") else None,
                    password=str(password) if password not in (None, "") else None,
                ),
                scheme=scheme or "http",
                host=str(host),
                port=port_int,
                username=str(username) if username not in (None, "") else None,
                password=str(password) if password not in (None, "") else None,
                source_metadata=item,
            )

        if candidate:
            if host:
                candidate.host = str(host)
            if port:
                try:
                    candidate.port = int(port)
                except Exception:
                    pass
            if scheme:
                candidate.scheme = scheme
            if username not in (None, ""):
                candidate.username = str(username)
            if password not in (None, ""):
                candidate.password = str(password)
            candidate.proxy_url = _build_proxy_url(
                scheme=candidate.scheme,
                host=candidate.host,
                port=candidate.port,
                username=candidate.username,
                password=candidate.password,
            )
            candidate.source_metadata = item
            candidates.append(candidate)

    return candidates


def _decode_dynamic_proxy_payload(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            return ""
        try:
            return json.loads(text)
        except Exception:
            return text


def fetch_dynamic_proxy_candidates(
    request: DynamicProxyRequest,
    response_root_field: str = "",
    response_item_mode: str = "string_list",
    response_field_mapping: dict[str, Any] | None = None,
) -> list[DynamicProxyCandidate]:
    """根据请求模板拉取动态代理候选列表。"""
    if cffi_requests is None:
        return []

    try:
        kwargs = {
            "headers": request.headers,
            "timeout": request.timeout_seconds,
            "impersonate": "chrome110",
        }
        if request.method == "POST":
            if request.body_mode == "form":
                response = cffi_requests.post(request.url, data=request.body or {}, **kwargs)
            elif request.body_mode == "raw":
                response = cffi_requests.post(request.url, data=request.body or "", **kwargs)
            else:
                response = cffi_requests.post(request.url, json=request.body or {}, **kwargs)
        else:
            response = cffi_requests.get(request.url, **kwargs)

        if response.status_code != 200:
            logger.warning("动态代理 API 返回错误状态码: %s", response.status_code)
            return []

        payload = _decode_dynamic_proxy_payload(response)
        candidates = parse_dynamic_proxy_candidates(
            payload=payload,
            response_root_field=response_root_field,
            response_item_mode=response_item_mode,
            response_field_mapping=response_field_mapping,
        )
        if candidates:
            return candidates

        if isinstance(payload, str):
            one = _candidate_from_proxy_url(payload)
            return [one] if one else []

        return []
    except Exception as exc:  # pragma: no cover - 网络异常分支
        logger.error("获取动态代理候选失败: %s", exc)
        return []


def probe_proxy_candidate(
    candidate: DynamicProxyCandidate,
    probe_url: str = "https://api.ipify.org?format=json",
    timeout_seconds: int = 10,
    detect_egress_ip: bool = True,
) -> DynamicProxyProbeResult:
    """测试代理连通性，并可选解析出口 IP。"""
    if cffi_requests is None:
        return DynamicProxyProbeResult(
            ok=False,
            proxy_url=candidate.proxy_url,
            error_message="curl_cffi requests unavailable",
        )

    start = time.time()
    try:
        response = cffi_requests.get(
            probe_url,
            proxies={"http": candidate.proxy_url, "https": candidate.proxy_url},
            timeout=max(int(timeout_seconds or 10), 1),
            impersonate="chrome110",
        )
        elapsed = round((time.time() - start) * 1000)

        if response.status_code != 200:
            return DynamicProxyProbeResult(
                ok=False,
                proxy_url=candidate.proxy_url,
                response_time_ms=elapsed,
                error_message=f"HTTP {response.status_code}",
            )

        egress_ip = None
        if detect_egress_ip:
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    egress_ip = str(payload.get("ip") or payload.get("query") or payload.get("origin") or "") or None
            except Exception:
                egress_ip = None

        return DynamicProxyProbeResult(
            ok=True,
            proxy_url=candidate.proxy_url,
            egress_ip=egress_ip,
            response_time_ms=elapsed,
        )
    except Exception as exc:
        return DynamicProxyProbeResult(
            ok=False,
            proxy_url=candidate.proxy_url,
            response_time_ms=round((time.time() - start) * 1000),
            error_message=str(exc),
        )


def fetch_dynamic_proxy(
    api_url: str,
    api_key: str = "",
    api_key_header: str = "X-API-Key",
    result_field: str = "",
) -> Optional[str]:
    """兼容旧接口：返回单个代理 URL。"""
    if not api_url:
        return None

    try:
        request = build_dynamic_proxy_request(
            request_method="GET",
            request_url=api_url,
            request_headers_template={},
            request_body_template={},
            request_count_param_name="",
            count=1,
            request_timeout_seconds=10,
            api_key=api_key,
            api_key_header=api_key_header,
        )
        candidates = fetch_dynamic_proxy_candidates(
            request,
            response_root_field=result_field,
            response_item_mode="string_list",
            response_field_mapping={},
        )
        if candidates:
            return candidates[0].proxy_url
    except Exception as exc:  # pragma: no cover
        logger.error("获取动态代理失败: %s", exc)

    return None


def get_proxy_url_for_task() -> Optional[str]:
    """为注册任务获取代理 URL。优先使用动态代理。"""
    from ..config.settings import get_settings

    settings = get_settings()

    if settings.proxy_dynamic_enabled:
        api_key = settings.proxy_dynamic_api_key.get_secret_value() if settings.proxy_dynamic_api_key else ""
        request_url = settings.proxy_dynamic_request_url or settings.proxy_dynamic_api_url

        if request_url:
            request = build_dynamic_proxy_request(
                request_method=settings.proxy_dynamic_request_method,
                request_url=request_url,
                request_headers_template=settings.proxy_dynamic_request_headers_template,
                request_body_template=settings.proxy_dynamic_request_body_template,
                request_body_mode=settings.proxy_dynamic_request_body_mode,
                request_count_param_name=settings.proxy_dynamic_request_count_param_name,
                count=settings.proxy_dynamic_request_count_default,
                request_timeout_seconds=settings.proxy_dynamic_request_timeout_seconds,
                api_key=api_key,
                api_key_header=settings.proxy_dynamic_api_key_header,
            )
            candidates = fetch_dynamic_proxy_candidates(
                request,
                response_root_field=settings.proxy_dynamic_response_root_field or settings.proxy_dynamic_result_field,
                response_item_mode=settings.proxy_dynamic_response_item_mode,
                response_field_mapping=settings.proxy_dynamic_response_field_mapping,
            )
            if candidates:
                return candidates[0].proxy_url

        if settings.proxy_dynamic_api_url:
            proxy_url = fetch_dynamic_proxy(
                api_url=settings.proxy_dynamic_api_url,
                api_key=api_key,
                api_key_header=settings.proxy_dynamic_api_key_header,
                result_field=settings.proxy_dynamic_result_field,
            )
            if proxy_url:
                return proxy_url

        logger.warning("动态代理获取失败，回退到静态代理")

    return settings.proxy_url
