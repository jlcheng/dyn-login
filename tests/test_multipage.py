import base64
import copy
import json

import pytest
from conftest import configure_url


def configure(client, flow_config, config_id="multi"):
    return client.get(configure_url(config_id, flow_config))


def post(client, step, data, config_id="multi"):
    return client.post(f"/{config_id}/login-step{step}", data=data)


def finish(client, config_id="multi"):
    post(client, 1, {"username": "test-user"}, config_id)
    post(client, 2, {"password": "test-password"}, config_id)
    return post(client, 3, {"otp": "123456"}, config_id)


def record(app):
    return app.test_table.get_item(Key={"config_id": "multi"}, ConsistentRead=True)["Item"]


def test_ordered_pages_and_profile(client, flow_config):
    response = configure(client, flow_config)
    assert response.location == "/multi/login-step1"
    assert client.get("/multi/login").location == "/multi/login-step1"
    html = client.get(response.location).get_data(as_text=True)
    assert 'id="un"' in html and 'id="p"' not in html and 'id="o"' not in html
    assert "Step 1 of 3" in html
    for expected in flow_config["expected_credentials"].values():
        assert expected not in html
    assert post(client, 1, {"username": "test-user"}).location == "/multi/login-step2"
    assert client.get("/multi/login").location == "/multi/login-step2"
    assert client.get("/multi/profile").location == "/multi/login-step2"
    assert post(client, 2, {"password": "test-password"}).location == "/multi/login-step3"
    assert post(client, 3, {"otp": "123456"}).location == "/multi/profile"
    assert b"test-user" in client.get("/multi/profile").data
    for path in ["login", "login-step1", "login-step2", "login-step3"]:
        assert client.get(f"/multi/{path}").location == "/multi/profile"
    assert client.get("/multi/logout").location == "/multi/login-step1"
    assert client.get("/multi/profile").location == "/multi/login-step1"


@pytest.mark.parametrize("step", [2, 3])
def test_cannot_skip_a_page_by_get_or_post(client, flow_config, step):
    configure(client, flow_config)
    assert client.get(f"/multi/login-step{step}").location == "/multi/login-step1"
    response = post(client, step, {"password": "test-password", "otp": "123456"})
    assert response.location == "/multi/login-step1"
    assert client.get("/multi/profile").location == "/multi/login-step1"


def test_each_page_checks_exact_value_and_allows_retry(client, flow_config):
    configure(client, flow_config)
    assert post(client, 1, {"username": "Test-user"}).status_code == 401
    assert client.get("/multi/login-step2").location == "/multi/login-step1"
    post(client, 1, {"username": "test-user"})
    assert post(client, 2, {}).status_code == 401
    assert post(client, 2, {"password": "test-password "}).status_code == 401
    assert client.get("/multi/login-step3").location == "/multi/login-step2"
    post(client, 2, {"password": "test-password"})
    response = post(client, 3, {"otp": "0123456"})
    assert response.status_code == 401
    assert b'id="o"' in response.data and b'value="' not in response.data
    assert client.get("/multi/profile").location == "/multi/login-step3"
    assert post(client, 3, {"otp": "123456"}).location == "/multi/profile"


def test_progress_cookie_contains_no_credentials(client, flow_config):
    configure(client, flow_config)
    post(client, 1, {"username": "test-user"})
    cookie = client.get_cookie("dyn_login", path="/multi/")
    state = json.loads(base64.urlsafe_b64decode(cookie.value.split(".")[0] + "=="))
    assert state["config_id"] == "multi" and state["step"] == 1
    for value in flow_config["expected_credentials"].values():
        assert value not in json.dumps(state)
    client.set_cookie("dyn_login", cookie.value + "bad", path="/multi/")
    assert client.get("/multi/login-step2").location == "/multi/login-step1"


def test_partial_and_complete_sessions_are_independent(client, flow_config):
    configure(client, flow_config)
    configure(client, flow_config, "other")
    post(client, 1, {"username": "test-user"})
    partial = client.get_cookie("dyn_login", path="/multi/").value
    client.set_cookie("dyn_login", partial, path="/other/")
    assert client.get("/other/login-step2").location == "/other/login-step1"
    finish(client, "other")
    assert client.get("/other/profile").status_code == 200
    assert client.get("/multi/login").location == "/multi/login-step2"
    client.get("/multi/logout")
    assert client.get("/other/profile").status_code == 200


def test_replacement_invalidates_in_progress_flow(client, flow_config, app):
    configure(client, flow_config)
    post(client, 1, {"username": "test-user"})
    token = client.get_cookie("dyn_login", path="/multi/").value
    other = app.test_client()
    configure(other, flow_config)
    assert client.get_cookie("dyn_login", path="/multi/").value == token
    assert client.get("/multi/login-step2").location == "/multi/login-step1"
    finish(client)
    configure(other, flow_config)
    assert client.get("/multi/profile").location == "/multi/login-step1"


def test_expiration_during_flow(client, flow_config, app):
    configure(client, flow_config)
    post(client, 1, {"username": "test-user"})
    app.test_clock[0] += 30 * 86400
    assert client.get("/multi/login-step2").status_code == 410
    assert post(client, 2, {"password": "test-password"}).status_code == 410


def test_reentering_earlier_page_discards_later_progress(client, flow_config):
    configure(client, flow_config)
    post(client, 1, {"username": "test-user"})
    post(client, 2, {"password": "test-password"})
    post(client, 1, {"username": "wrong"})
    assert client.get("/multi/login-step3").location == "/multi/login-step1"
    post(client, 1, {"username": "test-user"})
    assert client.get("/multi/login-step3").location == "/multi/login-step2"


def test_grouped_fields_without_otp_and_with_nested_path(client):
    config = {
        "expected_credentials": {"username": "test-user", "password": "test-password"},
        "pages": [
            {
                "path": "/sign-in/account",
                "fields": {"username": "un", "password": "p"},
                "submit_id": "go",
            }
        ],
    }
    assert configure(client, config).location == "/multi/sign-in/account"
    html = client.get("/multi/sign-in/account").data
    assert b'id="un"' in html and b'id="p"' in html
    assert b"Step 1 of 1" not in html
    assert (
        client.post(
            "/multi/sign-in/account", data={"username": "test-user", "password": "test-password"}
        ).location
        == "/multi/profile"
    )


def test_login_path_can_be_first_page_and_ids_can_repeat_on_different_pages(client, flow_config):
    flow_config["pages"][0]["path"] = "/login"
    for page in flow_config["pages"]:
        page["submit_id"] = "submit"
    configure(client, flow_config)
    assert client.get("/multi/login").status_code == 200
    assert (
        client.post("/multi/login", data={"username": "test-user"}).location == "/multi/login-step2"
    )


def test_array_order_defines_progress(client, flow_config):
    flow_config["pages"][0], flow_config["pages"][1] = (
        flow_config["pages"][1],
        flow_config["pages"][0],
    )
    assert configure(client, flow_config).location == "/multi/login-step2"
    assert post(client, 2, {"password": "test-password"}).location == "/multi/login-step1"
    assert post(client, 1, {"username": "test-user"}).location == "/multi/login-step3"


def test_unknown_page_is_explicit_error(client, flow_config):
    configure(client, flow_config)
    response = client.get("/multi/not-configured")
    assert response.status_code == 404
    assert b"Page not found" in response.data


@pytest.mark.parametrize(
    "bad_path",
    [
        "login-step1",
        "/profile",
        "/logout",
        "/configure",
        "/a?next=foo",
        "/a#b",
        "//other",
        "/a/../b",
        "/a/",
        "/a b",
    ],
)
def test_invalid_paths_preserve_configuration(client, flow_config, app, bad_path):
    configure(client, flow_config)
    before = record(app)
    flow_config["pages"][0]["path"] = bad_path
    assert configure(client, flow_config).status_code == 400
    assert record(app) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "empty_pages",
        "not_list",
        "duplicate_path",
        "empty_fields",
        "unknown_field",
        "repeated_field",
        "missing_password",
        "wrong_type",
        "duplicate_id",
        "invalid_id",
        "missing_submit",
        "reserved_login",
        "extra_credentials",
        "wrong_fields_type",
    ],
)
def test_invalid_flow_preserves_configuration(client, flow_config, app, mutation):
    configure(client, flow_config)
    before = record(app)
    bad = copy.deepcopy(flow_config)
    if mutation == "empty_pages":
        bad["pages"] = []
    elif mutation == "not_list":
        bad["pages"] = "pages"
    elif mutation == "duplicate_path":
        bad["pages"][1]["path"] = bad["pages"][0]["path"]
    elif mutation == "empty_fields":
        bad["pages"][0]["fields"] = {}
    elif mutation == "unknown_field":
        bad["pages"][0]["fields"] = {"email": "un"}
    elif mutation == "repeated_field":
        bad["pages"][1]["fields"]["username"] = "another-user"
    elif mutation == "missing_password":
        del bad["expected_credentials"]["password"]
    elif mutation == "wrong_type":
        bad["expected_credentials"]["otp"] = 123456
    elif mutation == "duplicate_id":
        bad["pages"][0]["submit_id"] = "un"
    elif mutation == "invalid_id":
        bad["pages"][0]["fields"]["username"] = "has space"
    elif mutation == "missing_submit":
        del bad["pages"][1]["submit_id"]
    elif mutation == "reserved_login":
        bad["pages"][1]["path"] = "/login"
    elif mutation == "extra_credentials":
        bad["expected_credentials"]["other"] = "value"
    elif mutation == "wrong_fields_type":
        bad["pages"][0]["fields"] = ["username"]
    assert configure(client, bad).status_code == 400
    assert record(app) == before


def test_json_post_creates_large_config_without_url_payload(client, flow_config):
    flow_config["expected_credentials"]["password"] = "p" * 12_000
    response = client.post("/multi/configure", json=flow_config)
    assert response.status_code == 303 and response.location == "/multi/login-step1"
    post(client, 1, {"username": "test-user"})
    assert post(client, 2, {"password": "p" * 12_000}).location == "/multi/login-step3"


def test_invalid_and_oversized_json_post_preserve_configuration(client, flow_config, app):
    configure(client, flow_config)
    before = record(app)
    assert client.post("/multi/configure", json={"pages": []}).status_code == 400
    assert (
        client.post("/multi/configure", data="{", content_type="application/json").status_code
        == 400
    )
    flow_config["expected_credentials"]["password"] = "x" * 70_000
    assert client.post("/multi/configure", json=flow_config).status_code == 413
    assert record(app) == before
