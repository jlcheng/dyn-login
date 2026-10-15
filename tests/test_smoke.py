import ssl
import threading

from werkzeug.serving import make_server

from scripts.smoke import verify_site


def test_deployment_smoke_exercises_real_site(app):
    server = make_server("localhost", 0, app, threaded=True, ssl_context="adhoc")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        verify_site(
            f"https://localhost:{server.server_port}", context=ssl._create_unverified_context()
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
