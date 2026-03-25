from types import SimpleNamespace

from src.core import dynamic_proxy
from src.core.dynamic_proxy import (
    DynamicProxyCandidate,
    DynamicProxyProbeResult,
    build_dynamic_proxy_request,
    fetch_dynamic_proxy_candidates,
    parse_dynamic_proxy_candidates,
    parse_dynamic_proxy_curl,
    get_proxy_url_for_task,
    probe_proxy_candidate,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_parse_dynamic_proxy_curl_extracts_method_url_headers_and_body():
    parsed = parse_dynamic_proxy_curl(
        "curl 'https://proxy.example.com/pool' -X POST "
        "-H 'Authorization: Bearer abc' "
        "-H 'Content-Type: application/json' "
        "--data '{\"count\": 5}'"
    )

    assert parsed["request_method"] == "POST"
    assert parsed["request_url"] == "https://proxy.example.com/pool"
    assert parsed["request_headers_template"]["Authorization"] == "Bearer abc"
    assert parsed["request_body_template"]["count"] == 5


def test_parse_dynamic_proxy_curl_preserves_get_when_using_dash_g_with_data():
    parsed = parse_dynamic_proxy_curl(
        "curl -G 'https://proxy.example.com/pool' "
        "--data 'count=3&region=us'"
    )
    request = build_dynamic_proxy_request(
        request_method=parsed["request_method"],
        request_url=parsed["request_url"],
        request_headers_template=parsed["request_headers_template"],
        request_body_template=parsed["request_body_template"],
        request_body_mode=parsed["request_body_mode"],
        request_count_param_name="count",
        count=3,
    )

    assert parsed["request_method"] == "GET"
    assert parsed["request_body_mode"] == "form"
    assert parsed["request_body_template"] == {"count": "3", "region": "us"}
    assert request.method == "GET"
    assert request.body is None
    assert "count=3" in request.url
    assert "region=us" in request.url


def test_build_dynamic_proxy_request_injects_count_into_query_or_body():
    get_request = build_dynamic_proxy_request(
        request_method="GET",
        request_url="https://proxy.example.com/pool?region=us",
        request_headers_template={"Authorization": "Bearer abc"},
        request_body_template={},
        request_count_param_name="count",
        count=4,
    )
    post_request = build_dynamic_proxy_request(
        request_method="POST",
        request_url="https://proxy.example.com/pool",
        request_headers_template={"Authorization": "Bearer abc"},
        request_body_template={"count": "{{count}}", "region": "us"},
        request_count_param_name="count",
        count=7,
    )

    assert get_request.method == "GET"
    assert "count=4" in get_request.url
    assert post_request.method == "POST"
    assert post_request.body["count"] == 7


def test_fetch_dynamic_proxy_candidates_sends_form_post_body_without_json(monkeypatch):
    parsed = parse_dynamic_proxy_curl(
        "curl 'https://proxy.example.com/pool' -X POST "
        "-H 'Content-Type: application/x-www-form-urlencoded' "
        "--data 'count=3&region=us'"
    )
    request = build_dynamic_proxy_request(
        request_method=parsed["request_method"],
        request_url=parsed["request_url"],
        request_headers_template=parsed["request_headers_template"],
        request_body_template=parsed["request_body_template"],
        request_body_mode=parsed["request_body_mode"],
        request_count_param_name="count",
        count=3,
    )
    captured: dict[str, object] = {}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse(status_code=200, payload={"data": ["http://1.1.1.1:8000"]})

    monkeypatch.setattr(dynamic_proxy.cffi_requests, "post", _fake_post)

    rows = fetch_dynamic_proxy_candidates(
        request,
        response_root_field="data",
        response_item_mode="string_list",
        response_field_mapping={},
    )

    assert rows[0].proxy_url == "http://1.1.1.1:8000"
    assert request.body_mode == "form"
    assert captured["data"] == {"count": "3", "region": "us"}
    assert "json" not in captured


def test_get_proxy_url_for_task_uses_persisted_request_body_mode_for_form_post(monkeypatch):
    settings = SimpleNamespace(
        proxy_dynamic_enabled=True,
        proxy_dynamic_api_key=None,
        proxy_dynamic_api_key_header="X-Token",
        proxy_dynamic_request_method="POST",
        proxy_dynamic_request_url="https://proxy.example.com/pool",
        proxy_dynamic_request_headers_template={},
        proxy_dynamic_request_body_mode="form",
        proxy_dynamic_request_body_template={"region": "us"},
        proxy_dynamic_request_count_param_name="count",
        proxy_dynamic_request_count_default=3,
        proxy_dynamic_request_timeout_seconds=10,
        proxy_dynamic_response_root_field="data",
        proxy_dynamic_response_item_mode="string_list",
        proxy_dynamic_response_field_mapping={},
        proxy_dynamic_result_field="",
        proxy_dynamic_api_url="",
        proxy_url="http://static.example.com:8080",
    )
    captured: dict[str, object] = {}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse(status_code=200, payload={"data": ["http://1.1.1.1:8000"]})

    monkeypatch.setattr(dynamic_proxy.cffi_requests, "post", _fake_post)
    monkeypatch.setattr("src.config.settings.get_settings", lambda: settings)

    proxy_url = get_proxy_url_for_task()

    assert proxy_url == "http://1.1.1.1:8000"
    assert captured["data"] == {"region": "us", "count": 3}
    assert "json" not in captured


def test_get_proxy_url_for_task_uses_auto_body_mode_for_legacy_form_config(monkeypatch):
    settings = SimpleNamespace(
        proxy_dynamic_enabled=True,
        proxy_dynamic_api_key=None,
        proxy_dynamic_api_key_header="X-Token",
        proxy_dynamic_request_method="POST",
        proxy_dynamic_request_url="https://proxy.example.com/pool",
        proxy_dynamic_request_headers_template={"Content-Type": "application/x-www-form-urlencoded"},
        proxy_dynamic_request_body_mode="auto",
        proxy_dynamic_request_body_template={"region": "legacy-us"},
        proxy_dynamic_request_count_param_name="count",
        proxy_dynamic_request_count_default=2,
        proxy_dynamic_request_timeout_seconds=10,
        proxy_dynamic_response_root_field="data",
        proxy_dynamic_response_item_mode="string_list",
        proxy_dynamic_response_field_mapping={},
        proxy_dynamic_result_field="",
        proxy_dynamic_api_url="",
        proxy_url="http://static.example.com:8080",
    )
    captured: dict[str, object] = {}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse(status_code=200, payload={"data": ["http://2.2.2.2:9000"]})

    monkeypatch.setattr(dynamic_proxy.cffi_requests, "post", _fake_post)
    monkeypatch.setattr("src.config.settings.get_settings", lambda: settings)

    proxy_url = get_proxy_url_for_task()

    assert proxy_url == "http://2.2.2.2:9000"
    assert captured["data"] == {"region": "legacy-us", "count": 2}
    assert "json" not in captured


def test_fetch_dynamic_proxy_candidates_sends_explicit_raw_post_body_without_json(monkeypatch):
    request = build_dynamic_proxy_request(
        request_method="POST",
        request_url="https://proxy.example.com/pool",
        request_headers_template={"Content-Type": "text/plain"},
        request_body_template={"raw": "count=3&region=raw-us"},
        request_count_param_name="",
        count=3,
        request_body_mode="raw",
    )
    captured: dict[str, object] = {}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse(status_code=200, payload={"data": ["http://3.3.3.3:7000"]})

    monkeypatch.setattr(dynamic_proxy.cffi_requests, "post", _fake_post)

    rows = fetch_dynamic_proxy_candidates(
        request,
        response_root_field="data",
        response_item_mode="string_list",
        response_field_mapping={},
    )

    assert rows[0].proxy_url == "http://3.3.3.3:7000"
    assert captured["data"] == "count=3&region=raw-us"
    assert "json" not in captured


def test_parse_dynamic_proxy_candidates_supports_string_and_object_lists():
    string_rows = parse_dynamic_proxy_candidates(
        payload={"data": ["http://1.1.1.1:8000", "socks5://2.2.2.2:9000"]},
        response_root_field="data",
        response_item_mode="string_list",
        response_field_mapping={},
    )
    object_rows = parse_dynamic_proxy_candidates(
        payload={"data": {"items": [{"server": "3.3.3.3", "port": 8080, "protocol": "http"}]}},
        response_root_field="data.items",
        response_item_mode="object_list",
        response_field_mapping={"host": "server", "type": "protocol"},
    )

    assert string_rows[0].proxy_url == "http://1.1.1.1:8000"
    assert object_rows[0].host == "3.3.3.3"
    assert object_rows[0].scheme == "http"


def test_parse_dynamic_proxy_candidates_keeps_socks5_scheme_from_proxy_url_without_type():
    rows = parse_dynamic_proxy_candidates(
        payload={"data": {"items": [{"proxy_url": "socks5://user:pass@4.4.4.4:1080"}]}},
        response_root_field="data.items",
        response_item_mode="object_list",
        response_field_mapping={},
    )

    assert rows[0].scheme == "socks5"
    assert rows[0].proxy_url == "socks5://user:pass@4.4.4.4:1080"


def test_probe_proxy_candidate_returns_connectivity_and_optional_egress_ip(monkeypatch):
    candidate = DynamicProxyCandidate(
        proxy_url="http://1.1.1.1:8080",
        scheme="http",
        host="1.1.1.1",
        port=8080,
    )

    def _fake_get(url, **kwargs):
        return _FakeResponse(status_code=200, payload={"ip": "8.8.8.8"})

    monkeypatch.setattr(dynamic_proxy.cffi_requests, "get", _fake_get)

    result = probe_proxy_candidate(
        candidate,
        probe_url="https://probe.example.com/ip",
        timeout_seconds=2,
        detect_egress_ip=False,
    )

    assert isinstance(result, DynamicProxyProbeResult)
    assert result.ok is True
    assert result.egress_ip is None
