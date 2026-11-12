import re
from pathlib import Path

import pytest
from conftest import configure_url

from dyn_login.themes import THEMES

THEME_DIR = Path(__file__).parent.parent / "dyn_login" / "static" / "themes"


def record(app, config_id):
    return app.test_table.get_item(Key={"config_id": config_id}, ConsistentRead=True)["Item"]


@pytest.mark.parametrize("theme", THEMES)
def test_theme_loads_on_login_and_profile(client, config, theme):
    client.get(configure_url("alpha", {**config, "theme": theme}))
    login = client.get("/alpha/login").get_data(as_text=True)
    assert "/static/themes/base.css" in login
    assert f"/static/themes/{theme}.css" in login
    client.post("/alpha/login", data={"username": "test-user", "password": "test-password"})
    assert f"/static/themes/{theme}.css" in client.get("/alpha/profile").get_data(as_text=True)


def test_multi_page_config_can_name_a_theme(client, flow_config):
    response = client.post("/multi/configure", json={**flow_config, "theme": "canvas"})
    assert response.status_code == 303
    assert "/static/themes/canvas.css" in client.get("/multi/login-step1").get_data(as_text=True)


def test_no_theme_keeps_default_look(configured):
    response = configured.get("/alpha/login")
    assert "/static/themes/" not in response.get_data(as_text=True)
    assert "font-src 'self';" in response.headers["Content-Security-Policy"]


@pytest.mark.parametrize("theme", ["", "Cloud", "base", "../style", None, 1, ["cloud"]])
def test_unknown_theme_preserves_configuration(configured, app, config, theme):
    before = record(app, "alpha")
    response = configured.get(configure_url("alpha", {**config, "theme": theme}))
    assert response.status_code == 400
    assert b"Unknown theme" in response.data
    assert record(app, "alpha") == before


def test_every_theme_has_a_stylesheet_and_no_stray_ones():
    assert {path.stem for path in THEME_DIR.glob("*.css")} == {"base", *THEMES}


@pytest.mark.parametrize("theme", THEMES)
def test_theme_sets_every_variable_the_shared_rules_use(theme):
    used = set(re.findall(r"var\((--[\w-]+)\)", (THEME_DIR / "base.css").read_text()))
    defined = set(re.findall(r"(--[\w-]+)\s*:", (THEME_DIR / f"{theme}.css").read_text()))
    assert used - defined == set()


@pytest.mark.parametrize("name", ["base", *THEMES])
def test_theme_only_changes_looks(name):
    css = re.sub(r"/\*.*?\*/", "", (THEME_DIR / f"{name}.css").read_text(), flags=re.S)
    # No new text, no hidden text, no rewritten text.
    for pattern in [
        r"(?<![\w-])content\s*:",
        r"display\s*:\s*none",
        r"visibility\s*:",
        r"text-transform",
    ]:
        assert not re.search(pattern, css), pattern
    # The only files a theme may load are the bundled fonts.
    for url in re.findall(r"url\(([^)]*)\)", css):
        assert re.fullmatch(r"""["']?\.\./fonts/[\w.-]+\.woff2["']?""", url), url


def test_bundled_font_is_served(client):
    response = client.get("/static/fonts/InterVariable-latin.woff2")
    assert response.status_code == 200 and response.data[:4] == b"wOF2"


def test_editor_lists_themes(client):
    html = client.get("/editor").get_data(as_text=True)
    for key, theme in THEMES.items():
        assert f'<option value="{key}"' in html and theme["label"] in html


@pytest.mark.parametrize("theme", [None, *THEMES])
def test_theme_preview_needs_no_configuration(client, app, theme):
    url = f"/theme-preview?theme={theme}" if theme else "/theme-preview"
    page = client.get(url)
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'id="un"' in html and 'id="p"' in html and 'id="sign-in"' in html
    assert ("/static/themes/" in html) == bool(theme)
    if theme:
        assert f"/static/themes/{theme}.css" in html
    attempt = client.post(url, data={"username": "test-user", "password": "test-password"})
    assert b"is incorrect" in attempt.data and b"is incorrect" not in page.data
    assert app.test_table.scan()["Items"] == []


def test_theme_preview_rejects_unknown_theme(client):
    response = client.get("/theme-preview?theme=base")
    assert response.status_code == 404 and b"Theme not found" in response.data
