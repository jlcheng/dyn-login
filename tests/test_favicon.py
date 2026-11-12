import base64
import struct
import zlib

import pytest
from conftest import configure_url

from dyn_login.editor import REQUEST_LINE_LIMIT, configuration_link

PREFIX = "data:image/png;base64,"


def png(width, height, padding=0):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + (chunk(b"tEXt", b"Comment\x00" + b"x" * (padding - 20)) if padding else b"")
        + chunk(b"IEND", b"")
    )


def favicon(width=32, height=32, padding=0):
    return PREFIX + base64.b64encode(png(width, height, padding)).decode()


def record(app, config_id):
    return app.test_table.get_item(Key={"config_id": config_id}, ConsistentRead=True)["Item"]


def test_five_field_config_shows_favicon_on_login_and_profile(client, config):
    icon = favicon()
    client.get(configure_url("alpha", {**config, "favicon": icon}))
    login = client.get("/alpha/login")
    html = login.get_data(as_text=True)
    assert f'<link rel="icon" href="{icon}" type="image/png">' in html
    assert "favicon.svg" not in html
    assert "img-src 'self' data:;" in login.headers["Content-Security-Policy"]
    client.post("/alpha/login", data={"username": "test-user", "password": "test-password"})
    assert icon in client.get("/alpha/profile").get_data(as_text=True)


def test_multi_page_config_shows_favicon_on_every_page(client, flow_config):
    icon = favicon(128, 128)
    assert client.post("/multi/configure", json={**flow_config, "favicon": icon}).status_code == 303
    assert icon in client.get("/multi/login-step1").get_data(as_text=True)
    client.post("/multi/login-step1", data={"username": "test-user"})
    assert icon in client.get("/multi/login-step2").get_data(as_text=True)


def test_config_without_favicon_keeps_default_icon(configured):
    html = configured.get("/alpha/login").get_data(as_text=True)
    assert "favicon.svg" in html and PREFIX not in html


def test_largest_favicon_fits_in_get_link(flow_config):
    icon = favicon(padding=1439)
    assert len(icon) == 2046
    link = configuration_link(
        "00000000-0000-0000-0000-000000000000", {**flow_config, "favicon": icon}
    )
    assert link["request_line_bytes"] <= REQUEST_LINE_LIMIT


@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        "",
        favicon().replace("image/png", "image/jpeg"),
        favicon(padding=1440),
        PREFIX + "not base64!",
        PREFIX + base64.b64encode(b"GIF89a" + b"\x00" * 30).decode(),
        favicon(129, 16),
        favicon(16, 129),
        favicon(0, 16),
    ],
    ids=[
        "null",
        "number",
        "empty",
        "jpeg",
        "too_long",
        "bad_base64",
        "not_png",
        "too_wide",
        "too_tall",
        "zero_width",
    ],
)
def test_invalid_favicon_preserves_configuration(configured, app, config, value):
    before = record(app, "alpha")
    response = configured.get(configure_url("alpha", {**config, "favicon": value}))
    assert response.status_code == 400
    assert b"Invalid favicon" in response.data
    assert record(app, "alpha") == before


def test_editor_accepts_favicon(client, config):
    response = client.post(
        "/editor", json={"config_id": "alpha", "configuration": {**config, "favicon": favicon()}}
    )
    assert response.get_json()["valid"] is True
