from types import SimpleNamespace

from src.services.temp_mail import TempMailService


class DummyResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def test_temp_mail_service_reads_messages_via_api_mails_with_bearer_token():
    service = TempMailService(
        {
            "base_url": "https://mail.example.test",
            "admin_password": "admin-secret",
            "domain": "example.test",
        }
    )
    service._email_cache["tester@example.test"] = {"jwt": "jwt-123"}

    calls: list[dict] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return DummyResponse(
            payload={
                "results": [
                    {
                        "id": "mail-1",
                        "from": "OpenAI <noreply@openai.com>",
                        "subject": "Your verification code",
                        "text": "验证码是 123456",
                    }
                ]
            }
        )

    service.http_client = SimpleNamespace(request=fake_request)

    code = service.get_verification_code(email="tester@example.test", timeout=1)

    assert code == "123456"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://mail.example.test/api/mails"
    assert calls[0]["kwargs"]["headers"]["Authorization"] == "Bearer jwt-123"
    assert "x-user-token" not in calls[0]["kwargs"]["headers"]
