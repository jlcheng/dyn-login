"""Real form submissions using the CSS and XPath selectors an extension would use."""

import threading

import pytest
from conftest import configure_url
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server


@pytest.fixture
def website(app, client, config):
    client.get(configure_url("alpha", config))
    client.get(
        configure_url(
            "beta",
            {
                **config,
                "username_id": "account:user",
                "password_id": "account.password",
                "login_id": "go-now",
            },
        )
    )
    server = make_server("localhost", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.mark.browser
def test_css_xpath_login_session_and_logout(website, browser, app, client, config):
    context = browser.new_context()
    alpha = context.new_page()
    alpha.goto(f"{website}/alpha/login")
    assert alpha.locator("#user-field").input_value() == ""
    assert alpha.locator("#password-field").input_value() == ""
    assert "test-password" not in alpha.content()
    alpha.locator("#user-field").fill("test-user")
    alpha.locator("#password-field").fill("test-password")
    alpha.locator("xpath=//*[@id='submit-button']").click()
    assert alpha.url == f"{website}/alpha/profile"
    assert alpha.get_by_text("test-user", exact=True).is_visible()
    alpha.reload()
    assert alpha.url.endswith("/profile")

    beta = context.new_page()
    beta.goto(f"{website}/beta/profile")
    assert beta.url.endswith("/beta/login")
    beta.locator("xpath=//*[@id='account:user']").fill("test-user")
    beta.locator(r"#account\.password").fill("test-password")
    beta.locator("#go-now").click()
    assert beta.url.endswith("/beta/profile")
    alpha.get_by_role("link", name="Logout").click()
    beta.reload()
    assert beta.url.endswith("/beta/profile")
    assert alpha.url.endswith("/alpha/login")
    for cookie in context.cookies():
        assert cookie["secure"] and cookie["httpOnly"]
        assert cookie["sameSite"] == "Lax" and cookie["expires"] == -1
        assert cookie["path"] == "/beta/"

    client.get(configure_url("beta", config))
    beta.reload()
    assert beta.url.endswith("/beta/login")
    beta.locator("#user-field").fill("test-user")
    beta.locator("#password-field").fill("wrong-password")
    beta.locator("#submit-button").click()
    assert beta.get_by_role("alert").is_visible()
    assert beta.locator("#password-field").input_value() == ""
    app.test_clock[0] += 30 * 86400
    beta.reload()
    assert beta.get_by_role("heading", name="Configuration expired.").is_visible()
    assert beta.locator("input").count() == 0
    context.close()


@pytest.mark.browser
def test_mobile_layout_and_accessible_labels(website, browser):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(f"{website}/alpha/login")
    assert page.get_by_label("Username", exact=True).is_visible()
    assert page.get_by_label("Password", exact=True).is_visible()
    assert page.get_by_role("button", name="Sign in", exact=True).is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_text("Form details", exact=False).click()
    assert page.get_by_text("user-field", exact=True).is_visible()
    page.close()


@pytest.mark.browser
def test_multi_page_css_xpath_and_otp(website, browser, client, flow_config):
    client.post("/multi/configure", json=flow_config)
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(f"{website}/multi/login")
    assert page.url.endswith("/multi/login-step1")
    assert page.get_by_text("Step 1 of 3", exact=True).is_visible()
    assert page.locator("#un").input_value() == ""
    assert page.locator("#p").count() == 0
    page.locator("#un").fill("test-user")
    page.locator("xpath=//*[@id='next-username']").click()
    assert page.url.endswith("/multi/login-step2")
    assert page.get_by_text("Step 2 of 3", exact=True).is_visible()
    assert page.locator("#un").count() == 0
    assert "test-password" not in page.content()
    page.locator("xpath=//*[@id='p']").fill("test-password")
    page.locator("#next-password").click()
    assert page.url.endswith("/multi/login-step3")
    assert "123456" not in page.content()
    page.locator("#o").fill("000000")
    page.locator("#sign-in").click()
    assert page.get_by_role("alert").is_visible()
    assert page.locator("#o").input_value() == ""
    page.reload()
    assert page.url.endswith("/multi/login-step3")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("xpath=//*[@id='o']").fill("123456")
    page.locator("#sign-in").click()
    assert page.url.endswith("/multi/profile")
    assert page.get_by_text("test-user", exact=True).is_visible()
    page.get_by_role("link", name="Logout", exact=True).click()
    assert page.url.endswith("/multi/login-step1")
    context.close()


@pytest.mark.browser
def test_editor_templates_validation_copy_and_real_login(website, browser):
    context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
    page = context.new_page()
    page.goto(f"{website}/editor")
    page.get_by_label("Configuration ID", exact=True).fill("editor-test")
    page.get_by_label("Start from a template", exact=True).select_option("three")
    editor = page.get_by_label("Configuration JSON", exact=True)
    assert '"otp"' in editor.input_value()
    assert page.get_by_role("button", name="Copy link", exact=True).is_disabled()
    page.get_by_role("button", name="Validate & generate link", exact=True).click()
    from playwright.sync_api import expect

    expect(page.get_by_role("status")).to_contain_text("Valid configuration")
    link = page.get_by_label("Configure URL", exact=True).input_value()
    assert link.startswith(f"{website}/editor-test/configure?data=")
    page.get_by_role("button", name="Copy link", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Link copied")
    assert page.evaluate("navigator.clipboard.readText()") == link
    page.goto(link)
    assert page.url.endswith("/editor-test/login-step1")
    page.locator("#un").fill("test-user")
    page.locator("#next-username").click()
    page.locator("#p").fill("test-password")
    page.locator("#next-password").click()
    page.locator("#o").fill("123456")
    page.locator("#sign-in").click()
    assert page.url.endswith("/editor-test/profile")
    context.close()


@pytest.mark.browser
def test_editor_errors_stale_links_and_mobile_layout(website, browser):
    import json

    from playwright.sync_api import expect

    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(f"{website}/editor")
    editor = page.get_by_label("Configuration JSON", exact=True)
    validate = page.get_by_role("button", name="Validate & generate link", exact=True)
    copy = page.get_by_role("button", name="Copy link", exact=True)
    editor.fill("{")
    validate.click()
    expect(page.get_by_role("status")).to_contain_text("Invalid JSON")
    assert copy.is_disabled()
    page.get_by_label("Start from a template", exact=True).select_option("two")
    config = json.loads(editor.input_value())
    config["pages"][0]["submit_id"] = config["pages"][0]["fields"]["username"]
    editor.fill(json.dumps(config))
    validate.click()
    expect(page.get_by_role("status")).to_contain_text("different ID")
    page.get_by_label("Start from a template", exact=True).select_option("grouped")
    validate.click()
    expect(copy).to_be_enabled()
    page.get_by_label("Configuration ID", exact=True).fill("changed-id")
    expect(copy).to_be_disabled()
    assert page.get_by_label("Configure URL", exact=True).input_value() == ""
    page.get_by_role("button", name="New ID", exact=True).click()
    assert page.get_by_label("Configuration ID", exact=True).input_value() != "changed-id"
    config = json.loads(editor.input_value())
    config["expected_credentials"]["password"] = "x" * 5000
    editor.fill(json.dumps(config))
    page.get_by_role("button", name="Format JSON", exact=True).click()
    assert '\n  "expected_credentials"' in editor.input_value()
    validate.click()
    expect(page.get_by_role("status")).to_contain_text("too long")
    assert copy.is_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.close()
