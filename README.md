# Dyn Login

A configurable, server-rendered login site for testing browser extensions with CSS and XPath selectors. Python, Flask, and plain HTML; DynamoDB in production.

## See it locally

```sh
uv sync --locked --python 3.12
uv run python -m dyn_login.preview
```

Open <http://localhost:5057/demo/login>. Sign in with `test-user` / `test-password`.
The preview emulates DynamoDB locally with Moto. It makes no AWS requests, and its configurations disappear when the process stops. Use `localhost` so browsers accept the session's Secure cookie during local testing.

## Configure your own page

Run this Python 3 example and open the URL it prints. Change `base` to `http://localhost:5057` to use the local preview.

```python
import base64
import json
import uuid
from urllib.parse import urlencode

config = {
    "username_id": "user-field",
    "password_id": "password-field",
    "login_id": "submit-button",
    "expected_username": "test-user",
    "expected_password": "test-password",
}
data = base64.urlsafe_b64encode(json.dumps(config).encode("utf-8")).decode("ascii")
config_id = str(uuid.uuid4())
base = "https://dyn-login.jcheng.org"
print(f"{base}/{config_id}/configure?" + urlencode({"data": data}))
```

`GET /<config_id>/configure?data=...` atomically creates or replaces a configuration and redirects to its login page. Reusing the ID keeps the same URLs, renews the 30-day lifetime, and invalidates old sessions. Invalid requests leave existing data untouched. Anyone with the ID can replace it, so use a fresh UUID for an isolated test.

The five fields are required strings. Element IDs must be nonempty, distinct, and contain no ASCII whitespace or null characters. Config IDs contain URL-safe ASCII letters, digits, `_`, `-`, `.`, `~`, with no leading `.`, and have at most 128 characters. The application accepts configuration query strings and form bodies up to 64 KiB; proxies and browsers may impose smaller URL limits.

## Test a flow

| Route | Behavior |
| --- | --- |
| `GET /<config_id>/login` | Empty form using the configured element IDs |
| `POST /<config_id>/login` | Match `username` and `password` exactly; redirect to profile |
| `GET /<config_id>/profile` | Show the authenticated username or redirect to login |
| `GET /<config_id>/logout` | Clear only this configuration's session |

For the example IDs, CSS selectors are `#user-field`, `#password-field`, and `#submit-button`. An equivalent XPath selector is `//*[@id='user-field']`. IDs containing CSS punctuation require escaping, for example `#account\:user`.

Expected credentials are never put in the login HTML. Sessions use signed, host-only, Secure, HttpOnly, SameSite=Lax cookies scoped to `/<config_id>/`, with no persistent expiration. Each request checks the current configuration version and expiration using a strongly consistent DynamoDB read. TTL cleanup is separate from immediate expiration enforcement. Responses are not cached; access logs omit query strings and request bodies.

## Validate

```sh
uv sync --locked --python 3.12
uv run playwright install chromium
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Browser tests launch Chromium and submit the real forms through CSS and XPath selectors. They cover separate tabs, replacement, failure/retry, expiration, and mobile layout. Application tests use Moto against the same DynamoDB calls used in production.

## Production

Terraform is managed in the existing infrastructure repository, in `piles/dyn-login/`. It provisions DynamoDB, ECR, ECS Fargate, IAM, logs, routing, and DNS while looking up the shared VPC and ALB. See [deployment.md](deployment.md) for bootstrap and deployment instructions.

`fnox.toml` maps `SESSION_SIGNING_KEY` to the Secrets Manager secret `dyn-login/session-signing-key`. Production tasks resolve it through fnox using their AWS task role. All workers and deployments use the same key. The secret value is outside Terraform state and this repository.

GitHub Actions validates pull requests without AWS deployment permissions. On `main`, it publishes a uniquely tagged ECR image, deploys a task revision, waits for stability, verifies the active revision and running task count, and exercises the full HTTPS login flow. Set repository variable `AWS_DEPLOY_ROLE_ARN` to the Terraform output before enabling deployment. Smoke-test configurations expire normally after 30 days.
