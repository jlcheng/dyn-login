"""Verify a deployed login flow without logging configuration or credentials."""

import base64
import http.cookiejar
import json
import secrets
import sys
import uuid
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener


class FormElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        if tag in {"input", "button"}:
            self.ids.add(dict(attrs).get("id"))


def verify_site(base_url, *, context=None):
    base_url = base_url.rstrip("/")
    opener = build_opener(
        HTTPCookieProcessor(http.cookiejar.CookieJar()), HTTPSHandler(context=context)
    )

    def fetch(path, form=None):
        data = urlencode(form).encode() if form is not None else None
        with opener.open(Request(base_url + path, data=data), timeout=30) as response:
            if "no-store" not in response.headers.get("Cache-Control", ""):
                raise RuntimeError("Site response is unexpectedly cacheable")
            return response.geturl(), response.read().decode("utf-8")

    _, health = fetch("/health")
    if json.loads(health) != {"status": "ok"}:
        raise RuntimeError("Health endpoint failed")
    config_id = str(uuid.uuid4())
    username = "smoke-" + secrets.token_hex(8)
    password = secrets.token_urlsafe(24)
    config = {
        "username_id": "smoke-user",
        "password_id": "smoke-password",
        "login_id": "smoke-submit",
        "expected_username": username,
        "expected_password": password,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(config).encode()).decode()
    url, html = fetch(f"/{config_id}/configure?" + urlencode({"data": encoded}))
    parser = FormElements()
    parser.feed(html)
    if not url.endswith(f"/{config_id}/login") or not {
        "smoke-user",
        "smoke-password",
        "smoke-submit",
    }.issubset(parser.ids):
        raise RuntimeError("Configured login form failed")
    if username in html or password in html:
        raise RuntimeError("Expected credentials appeared in the login page")
    url, html = fetch(f"/{config_id}/login", {"username": username, "password": password})
    if not url.endswith(f"/{config_id}/profile") or username not in html:
        raise RuntimeError("Login or authenticated profile failed")
    url, _ = fetch(f"/{config_id}/logout")
    if not url.endswith(f"/{config_id}/login"):
        raise RuntimeError("Logout failed")
    url, _ = fetch(f"/{config_id}/profile")
    if not url.endswith(f"/{config_id}/login"):
        raise RuntimeError("Profile remained authenticated after logout")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        raise SystemExit("Usage: python scripts/smoke.py https://dyn-login.jcheng.org")
    verify_site(sys.argv[1])
    print("Deployment verified: health, configure, login, profile, and logout.")
