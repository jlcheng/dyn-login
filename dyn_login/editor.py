"""Starting configurations and compact link generation for the browser editor."""

import base64
import json
from typing import Any
from urllib.parse import urlencode

REQUEST_LINE_LIMIT = 4094


def template(label: str, description: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    credentials = {"username": "test-user", "password": "test-password", "otp": "123456"}
    fields = {field for page in pages for field in page["fields"]}
    return {
        "label": label,
        "description": description,
        "configuration": {
            "expected_credentials": {
                name: value for name, value in credentials.items() if name in fields
            },
            "pages": pages,
        },
    }


TEMPLATES = {
    "single": template(
        "One page",
        "Username and password together.",
        [
            {
                "path": "/login",
                "fields": {"username": "un", "password": "p"},
                "submit_id": "sign-in",
            },
        ],
    ),
    "two": template(
        "Two pages",
        "Username first, then password.",
        [
            {"path": "/login-step1", "fields": {"username": "un"}, "submit_id": "next-username"},
            {"path": "/login-step2", "fields": {"password": "p"}, "submit_id": "sign-in"},
        ],
    ),
    "three": template(
        "Three pages",
        "Username, password, then a verification code.",
        [
            {"path": "/login-step1", "fields": {"username": "un"}, "submit_id": "next-username"},
            {"path": "/login-step2", "fields": {"password": "p"}, "submit_id": "next-password"},
            {"path": "/login-step3", "fields": {"otp": "o"}, "submit_id": "sign-in"},
        ],
    ),
    "grouped": template(
        "Credentials + code",
        "Username and password together, then a code.",
        [
            {
                "path": "/login-step1",
                "fields": {"username": "un", "password": "p"},
                "submit_id": "next-code",
            },
            {"path": "/login-step2", "fields": {"otp": "o"}, "submit_id": "sign-in"},
        ],
    ),
}


def configuration_link(config_id: str, configuration: dict[str, Any]) -> dict[str, Any]:
    compact = json.dumps(configuration, separators=(",", ":")).encode("utf-8")
    data = base64.urlsafe_b64encode(compact).decode("ascii")
    url = f"/{config_id}/configure?" + urlencode({"data": data})
    return {
        "valid": True,
        "url": url,
        "request_line_bytes": len(f"GET {url} HTTP/1.1\r\n".encode("ascii")),
        "max_request_line_bytes": REQUEST_LINE_LIMIT,
    }
