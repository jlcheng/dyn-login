import base64
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest


def test_editor_page_and_home_link(client):
    response = client.get("/editor")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Configuration JSON" in html
    assert "Configuration ID" in html
    assert "One page" in html and "Three pages" in html
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
    assert b'href="/editor"' in client.get("/").data


def test_all_templates_are_valid_and_cover_useful_flows(client):
    from dyn_login.editor import TEMPLATES

    assert len(TEMPLATES) == 4
    for template in TEMPLATES.values():
        response = client.post(
            "/editor",
            json={"config_id": "template-test", "configuration": template["configuration"]},
        )
        assert response.status_code == 200 and response.json["valid"]
    assert sorted(len(t["configuration"]["pages"]) for t in TEMPLATES.values()) == [1, 2, 2, 3]


@pytest.mark.parametrize("fixture_name", ["config", "flow_config"])
def test_editor_validates_and_encodes_without_saving(client, app, request, fixture_name):
    config = request.getfixturevalue(fixture_name)
    with (
        patch.object(app.test_table, "put_item", wraps=app.test_table.put_item) as write,
        patch.object(app.test_table, "get_item", wraps=app.test_table.get_item) as read,
    ):
        response = client.post("/editor", json={"config_id": "my-test", "configuration": config})
    assert response.status_code == 200
    write.assert_not_called()
    read.assert_not_called()
    result = response.json
    assert result["valid"] is True
    url = urlsplit(result["url"])
    assert url.path == "/my-test/configure"
    decoded = json.loads(base64.urlsafe_b64decode(parse_qs(url.query)["data"][0]))
    assert decoded == config
    assert result["request_line_bytes"] == len(f"GET {result['url']} HTTP/1.1\r\n".encode())
    assert result["max_request_line_bytes"] == 4094
    assert "no-store" in response.headers["Cache-Control"]
    assert client.get(result["url"], follow_redirects=True).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"config_id": "bad id", "configuration": {}},
        {"config_id": 123, "configuration": {}},
        {"config_id": "valid", "configuration": {}},
    ],
)
def test_invalid_editor_requests_return_json_errors(client, payload):
    response = client.post("/editor", json=payload)
    assert response.status_code == 400
    assert response.json["valid"] is False
    assert response.json["error"]
    assert "url" not in response.json


def test_editor_uses_same_semantic_validation(client, flow_config):
    flow_config["pages"][0]["submit_id"] = "un"
    response = client.post("/editor", json={"config_id": "test", "configuration": flow_config})
    assert response.status_code == 400
    assert "different ID" in response.json["error"]


def test_editor_unicode_round_trip_and_long_url_feedback(client, flow_config):
    flow_config["expected_credentials"]["username"] = "你好 👋"
    response = client.post("/editor", json={"config_id": "unicode", "configuration": flow_config})
    encoded = parse_qs(urlsplit(response.json["url"]).query)["data"][0]
    assert json.loads(base64.urlsafe_b64decode(encoded)) == flow_config
    flow_config["expected_credentials"]["password"] = "x" * 5000
    response = client.post("/editor", json={"config_id": "large", "configuration": flow_config})
    assert response.status_code == 200
    assert response.json["request_line_bytes"] > response.json["max_request_line_bytes"]


def test_editor_oversized_payload_returns_json_error(client):
    response = client.post("/editor", json={"config_id": "test", "configuration": "x" * 70000})
    assert response.status_code == 413
    assert response.json["valid"] is False


def test_template_values_are_escaped_in_html(client, monkeypatch):
    from dyn_login.editor import TEMPLATES

    value = '</textarea><script>alert("x")</script>'
    monkeypatch.setitem(
        TEMPLATES["single"]["configuration"]["expected_credentials"], "username", value
    )
    html = client.get("/editor").get_data(as_text=True)
    assert value not in html
    assert "&lt;/textarea&gt;" in html
