from dyn_login.preview import preview_app


def test_preview_is_seeded_and_isolated():
    with preview_app() as app:
        client = app.test_client()
        assert b"Open the demo login" in client.get("/").data
        assert client.get("/demo/login").status_code == 200
        assert (
            client.post(
                "/demo/login", data={"username": "test-user", "password": "test-password"}
            ).status_code
            == 302
        )
        assert b"test-user" in client.get("/demo/profile").data


def test_preview_includes_three_page_demo():
    with preview_app() as app:
        client = app.test_client()
        assert b"Open the multi-page demo" in client.get("/").data
        response = client.get("/multi-demo/login", follow_redirects=True)
        assert response.request.path == "/multi-demo/login-step1"
        assert b"Step 1 of 3" in response.data and b'id="un"' in response.data
        assert (
            client.post("/multi-demo/login-step1", data={"username": "test-user"}).location
            == "/multi-demo/login-step2"
        )
        assert (
            client.post("/multi-demo/login-step2", data={"password": "test-password"}).location
            == "/multi-demo/login-step3"
        )
        assert (
            client.post("/multi-demo/login-step3", data={"otp": "123456"}).location
            == "/multi-demo/profile"
        )
