import base64
import json
from http.cookies import SimpleCookie
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from conftest import configure_url


def login(client, config_id="alpha", username="test-user", password="test-password"):
    return client.post(f"/{config_id}/login", data={"username": username, "password": password})


def record(app, config_id="alpha"):
    return app.test_table.get_item(Key={"config_id": config_id}, ConsistentRead=True).get("Item")


def test_configure_creates_and_redirects(client, app, config):
    response = client.get(configure_url("550e8400-e29b-41d4-a716-446655440000", config))
    assert response.status_code == 302
    assert response.location == "/550e8400-e29b-41d4-a716-446655440000/login"
    item = record(app, "550e8400-e29b-41d4-a716-446655440000")
    assert item["configuration"] == config
    assert float(item["expires_at"]) == app.test_clock[0] + 30 * 86400
    assert item["version"]


def test_replacement_is_complete_and_renews_lifetime(configured, app, config):
    before = record(app)
    app.test_clock[0] += 100
    changed = {**config, "expected_username": "other-user", "username_id": "new-user"}
    response = configured.get(configure_url("alpha", changed), follow_redirects=True)
    after = record(app)
    assert after["configuration"] == changed
    assert after["version"] != before["version"]
    assert after["expires_at"] == before["expires_at"] + 100
    assert b'id="new-user"' in response.data
    assert b'id="user-field"' not in response.data


@pytest.mark.parametrize(
    "changes",
    [
        {"username_id": ""},
        {"username_id": "has space"},
        {"password_id": "line\nbreak"},
        {"login_id": "user-field"},
        {"expected_password": 123},
        {"expected_username": None},
    ],
)
def test_invalid_config_preserves_everything(configured, app, config, changes):
    before = record(app)
    app.test_clock[0] += 200
    response = configured.get(configure_url("alpha", {**config, **changes}))
    assert response.status_code == 400
    assert record(app) == before


@pytest.mark.parametrize("data", ["not base64!", "e30=", "W10=", "null", "_w=="])
def test_invalid_payload_preserves_existing(configured, app, data):
    before = record(app)
    assert configured.get(f"/alpha/configure?data={data}").status_code == 400
    assert record(app) == before


def test_missing_data_and_fields(client, config):
    assert client.get("/alpha/configure").status_code == 400
    del config["login_id"]
    assert client.get(configure_url("alpha", config)).status_code == 400


@pytest.mark.parametrize("config_id", ["with space", "..", ".", "café", "bad%name"])
def test_invalid_config_ids(client, config, config_id):
    assert client.get(configure_url(config_id, config)).status_code == 400


def test_unpadded_base64_and_unicode_credentials(client, config):
    config["expected_username"] = "你好"
    config["expected_password"] = "U0001f511"
    url = configure_url("unicode", config).rstrip("=")
    assert client.get(url).status_code == 302
    assert login(client, "unicode", "你好", "U0001f511").status_code == 302


def test_no_arbitrary_four_kib_limit(client, config):
    config["expected_password"] = "x" * 5000
    assert client.get(configure_url("long", config)).status_code == 302


def test_form_ids_empty_fields_and_no_expected_credentials(configured):
    html = configured.get("/alpha/login").get_data(as_text=True)
    for element_id in ("user-field", "password-field", "submit-button"):
        assert f'id="{element_id}"' in html
    assert 'type="password"' in html
    assert "test-password" not in html
    assert "test-user" not in html
    assert 'value="' not in html


def test_configuration_is_escaped(client, config):
    config["username_id"] = '"><img/src=x/onerror=alert(1)>'
    config["expected_username"] = "<script>alert(1)</script>"
    assert client.get(configure_url("escaping", config)).status_code == 302
    html = client.get("/escaping/login").get_data(as_text=True)
    assert "<img/src=x/onerror=alert(1)>" not in html
    login(client, "escaping", config["expected_username"])
    profile = client.get("/escaping/profile").get_data(as_text=True)
    assert "<script>" not in profile
    assert "&lt;script&gt;" in profile


def test_login_profile_logout_flow(configured):
    assert configured.get("/alpha/profile").location == "/alpha/login"
    response = login(configured)
    assert response.location == "/alpha/profile"
    profile = configured.get(response.location)
    assert b"test-user" in profile.data
    assert b"Logout" in profile.data
    assert configured.get("/alpha/login").location == "/alpha/profile"
    assert b"test-user" in configured.get("/alpha/profile").data
    assert configured.get("/alpha/logout").location == "/alpha/login"
    assert configured.get("/alpha/profile").location == "/alpha/login"


@pytest.mark.parametrize(
    "username,password",
    [
        ("Test-user", "test-password"),
        ("test-user", "wrong"),
        ("test-user ", "test-password"),
        ("", ""),
        ("test-user", "test-password "),
    ],
)
def test_exact_matching_and_retry(configured, username, password):
    response = login(configured, username=username, password=password)
    assert response.status_code == 401
    assert b"Username or password is incorrect" in response.data
    assert b'id="submit-button"' in response.data
    assert configured.get("/alpha/profile").location == "/alpha/login"
    assert login(configured).status_code == 302


def test_cookie_security_and_contents(configured):
    response = login(configured)
    header = response.headers["Set-Cookie"]
    cookie = SimpleCookie()
    cookie.load(header)
    morsel = cookie["dyn_login"]
    assert morsel["secure"] and morsel["httponly"]
    assert morsel["samesite"] == "Lax"
    assert morsel["path"] == "/alpha/"
    assert not morsel["domain"] and not morsel["expires"] and not morsel["max-age"]
    payload = json.loads(base64.urlsafe_b64decode(morsel.value.split(".")[0] + "=="))
    assert payload["config_id"] == "alpha"
    assert payload["version"]
    assert "password" not in json.dumps(payload)


def test_sessions_are_independent(configured, config):
    configured.get(configure_url("beta", config))
    login(configured)
    assert configured.get("/beta/profile").location == "/beta/login"
    login(configured, "beta")
    assert configured.get("/alpha/profile").status_code == 200
    assert configured.get("/beta/profile").status_code == 200
    configured.get("/alpha/logout")
    assert configured.get("/alpha/profile").status_code == 302
    assert configured.get("/beta/profile").status_code == 200


def test_replacement_invalidates_session_even_for_unchanged_values(configured, config):
    login(configured)
    configured.get(configure_url("alpha", config))
    assert configured.get("/alpha/profile").location == "/alpha/login"
    assert configured.get("/alpha/login").status_code == 200


def test_cross_config_cookie_and_tampered_cookie_are_rejected(configured, config):
    login(configured)
    original = configured.get_cookie("dyn_login", path="/alpha/").value
    configured.get(configure_url("beta", config))
    configured.set_cookie("dyn_login", original, path="/beta/")
    assert configured.get("/beta/profile").location == "/beta/login"
    configured.set_cookie("dyn_login", original + "tampered", path="/alpha/")
    assert configured.get("/alpha/profile").location == "/alpha/login"


def test_expiration_is_enforced_without_ttl_cleanup(configured, app):
    login(configured)
    expires = float(record(app)["expires_at"])
    app.test_clock[0] = expires - 0.01
    assert configured.get("/alpha/profile").status_code == 200
    app.test_clock[0] = expires
    for path in ("login", "profile", "logout"):
        response = configured.get(f"/alpha/{path}")
        assert response.status_code == 410
        assert b"expired" in response.data.lower()
    assert login(configured).status_code == 410
    assert record(app) is not None


def test_reads_and_logins_do_not_extend_expiration(configured, app):
    before = record(app)
    app.test_clock[0] += 300
    configured.get("/alpha/login")
    login(configured)
    configured.get("/alpha/profile")
    configured.get("/alpha/logout")
    assert record(app) == before


@pytest.mark.parametrize("path", ["login", "profile", "logout"])
def test_missing_configuration(client, path):
    response = client.get(f"/missing/{path}")
    assert response.status_code == 404
    assert b"Configuration not found" in response.data
    assert b"<input" not in response.data


def test_strong_reads_across_workers(configured, app):
    from dyn_login import create_app

    with patch.object(app.test_table, "get_item", wraps=app.test_table.get_item) as read:
        configured.get("/alpha/login")
    assert read.call_args.kwargs["ConsistentRead"] is True
    other_app = create_app(
        {"TESTING": True, "SECRET_KEY": "test-signing-key", "CLOCK": lambda: app.test_clock[0]},
        table=app.test_table,
    )
    other_client = other_app.test_client()
    login(configured)
    other_client.set_cookie(
        "dyn_login", configured.get_cookie("dyn_login", path="/alpha/").value, path="/alpha/"
    )
    assert other_client.get("/alpha/profile").status_code == 200


def test_failed_write_preserves_configuration(configured, app, config):
    before = record(app)
    error = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "unavailable"}}, "PutItem"
    )
    with patch.object(app.test_table, "put_item", side_effect=error):
        response = configured.get(configure_url("alpha", config))
    assert response.status_code == 503
    assert record(app) == before


def test_no_cache_or_secret_logging(configured, app, config, caplog):
    for response in [
        configured.get(configure_url("alpha", config)),
        configured.get("/alpha/login"),
        login(configured),
        configured.get("/alpha/profile"),
        configured.get("/alpha/logout"),
        configured.get("/missing/login"),
    ]:
        assert "no-store" in response.headers["Cache-Control"]
    assert "test-password" not in caplog.text
    assert "expected_password" not in caplog.text


def test_home_and_health(client):
    assert b"Dyn Login" in client.get("/").data
    assert client.get("/health").json == {"status": "ok"}


def test_home_example_uses_https_behind_load_balancer(client):
    response = client.get(
        "/", base_url="http://dyn-login.jcheng.org", headers={"X-Forwarded-Proto": "https"}
    )
    assert 'base = "https://dyn-login.jcheng.org"' in response.get_data(as_text=True)
