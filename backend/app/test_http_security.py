from __future__ import annotations

import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings
from app.http_security import RequestSizeLimitMiddleware, safe_upload_filename
from karpy_platform.core.media.settings import validate_media_settings
from karpy_platform.core.support.security import SecurityService


def security_test_app(max_body_size: int = 512) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://console.example.test"],
        allow_credentials=True,
        allow_methods=["POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["testserver"])
    app.add_middleware(RequestSizeLimitMiddleware, max_body_size=max_body_size)

    @app.post("/form")
    async def parse_form(request: Request):
        form = await request.form(max_files=2, max_fields=2, max_part_size=32)
        return {"items": list(form.multi_items())}

    return app


class HTTPInputSecurityTests(unittest.TestCase):
    def test_oversized_declared_body_is_rejected_before_parsing(self) -> None:
        with TestClient(security_test_app(max_body_size=64)) as client:
            response = client.post("/form", content=b"x" * 65, headers={"content-type": "application/octet-stream"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["code"], "request_body_too_large")

    def test_malformed_multipart_is_rejected(self) -> None:
        with TestClient(security_test_app()) as client:
            response = client.post("/form", content=b"not-a-multipart-body", headers={"content-type": "multipart/form-data"})
        self.assertEqual(response.status_code, 400)

    def test_multipart_field_count_and_part_size_are_bounded(self) -> None:
        with TestClient(security_test_app()) as client:
            too_many = client.post("/form", files=[("a", (None, "1")), ("b", (None, "2")), ("c", (None, "3"))])
            too_large = client.post("/form", files=[("a", (None, "x" * 33))])
        self.assertEqual(too_many.status_code, 400)
        self.assertEqual(too_large.status_code, 400)

    def test_urlencoded_semicolon_is_not_a_field_separator(self) -> None:
        with TestClient(security_test_app()) as client:
            response = client.post(
                "/form",
                content="role=user&x=;role=admin",
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [["role", "user"], ["x", ";role=admin"]])

    def test_filenames_are_reduced_to_cross_platform_basenames(self) -> None:
        self.assertEqual(safe_upload_filename("../../etc/passwd"), "passwd")
        self.assertEqual(safe_upload_filename(r"..\..\windows\payload.zip"), "payload.zip")
        self.assertEqual(safe_upload_filename("/absolute/image.png"), "image.png")
        self.assertEqual(safe_upload_filename("../.."), "file")
        self.assertEqual(safe_upload_filename("bad\x00name.png"), "badname.png")

    def test_media_setting_cannot_exceed_server_upload_limit(self) -> None:
        errors = validate_media_settings({"max_upload_filesize": str(Settings(_env_file=None).MAX_UPLOAD_SIZE_MB + 1)})
        self.assertIn("max_upload_filesize", errors)

    def test_cors_and_trusted_hosts_fail_closed(self) -> None:
        with TestClient(security_test_app()) as client:
            blocked_host = client.post("http://evil.example/form", content="a=1", headers={"content-type": "application/x-www-form-urlencoded"})
            preflight = client.options(
                "/form",
                headers={
                    "origin": "https://evil.example",
                    "access-control-request-method": "POST",
                },
            )
        self.assertEqual(blocked_host.status_code, 400)
        self.assertEqual(preflight.status_code, 400)
        self.assertNotEqual(preflight.headers.get("access-control-allow-origin"), "https://evil.example")

    def test_forwarded_header_is_not_trusted_at_application_level(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(b"x-forwarded-for", b"203.0.113.99")],
                "client": ("10.0.0.5", 1234),
            }
        )
        self.assertEqual(SecurityService().client_ip(request), "10.0.0.5")

    def test_internal_api_origin_hostname_is_trusted_for_container_calls(self) -> None:
        settings = Settings(_env_file=None, INTERNAL_API_ORIGIN="http://my-backend:9000")
        hosts = settings.trusted_host_list
        # The container service hostname is trusted so server-side calls stop failing host checks.
        self.assertIn("my-backend", hosts)
        self.assertIn("127.0.0.1", hosts)
        # Fail-closed: a wildcard is never introduced, and manual hosts keep working.
        self.assertNotIn("*", hosts)
        manual = Settings(_env_file=None, INTERNAL_TRUSTED_HOSTS="api.internal, other-host")
        self.assertIn("api.internal", manual.trusted_host_list)
        self.assertIn("other-host", manual.trusted_host_list)

    def test_internal_api_origin_unset_adds_no_hosts(self) -> None:
        baseline = Settings(_env_file=None).trusted_host_list
        self.assertNotIn("*", baseline)
        # An empty internal origin must not widen the trusted set beyond the known defaults.
        self.assertEqual(baseline, Settings(_env_file=None, INTERNAL_API_ORIGIN="").trusted_host_list)

    def test_security_bounds_and_algorithm_validation(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, MAX_REQUEST_SIZE_MB=0)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, MAX_UPLOAD_SIZE_MB=129)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, JWT_ALGORITHM="none")


class StreamingRequestLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_without_content_length_is_still_bounded(self) -> None:
        chunks = iter(
            [
                {"type": "http.request", "body": b"a" * 40, "more_body": True},
                {"type": "http.request", "body": b"b" * 40, "more_body": False},
            ]
        )
        sent = []

        async def receive():
            return next(chunks)

        async def send(message):
            sent.append(message)

        async def consume_body(scope, receive, send):
            while True:
                message = await receive()
                if not message.get("more_body"):
                    break

        middleware = RequestSizeLimitMiddleware(consume_body, max_body_size=64)
        await middleware(
            {"type": "http", "method": "POST", "path": "/upload", "headers": []},
            receive,
            send,
        )
        start = next(message for message in sent if message["type"] == "http.response.start")
        self.assertEqual(start["status"], 413)


if __name__ == "__main__":
    unittest.main()
