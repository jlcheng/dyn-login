# Multi-page login configuration

[multi-page.json](multi-page.json) is a complete username → password → verification-code example. The code is a fixed test value, not a generated or delivered one-time password.

- `expected_credentials` contains the exact strings the form submissions must match.
- `pages` is the login sequence, in array order.
- Each page has a `path`, `fields`, and `submit_id`.
- `fields` maps credential names (`username`, `password`, `otp`) to HTML element IDs.
- Each credential appears once in the flow. Username and password are required; OTP is optional.
- Put multiple entries in one `fields` object to show them on the same page. IDs must be distinct on a page but may repeat across different pages.
- Paths are relative to the configuration ID. `/login-step1` becomes `/<config_id>/login-step1`. `/login` is also the entry/resume URL; it can be the first configured page. `/configure`, `/profile`, and `/logout` are reserved.

Each page validates its submitted fields before advancing. Incorrect values show an error on the same page with empty fields. Progress survives refreshes, is independent for each config ID, and expires with the configuration. All configured pages must pass before the profile is available. Visiting a later page directly redirects to the next required page.

## Try the preview

```sh
uv run python -m dyn_login.preview
```

Open <http://localhost:5057/multi-demo/login>. Enter `test-user`, then `test-password`, then `123456`. The original one-page demo remains at <http://localhost:5057/demo/login>.

## Configure using a URL

```python
import base64
import json
import uuid
from pathlib import Path
from urllib.parse import urlencode

config = json.loads(Path("examples/multi-page.json").read_text())
data = base64.urlsafe_b64encode(json.dumps(config, separators=(",", ":")).encode("utf-8")).decode(
    "ascii"
)
base = "http://localhost:5057"
config_id = str(uuid.uuid4())
print(f"{base}/{config_id}/configure?" + urlencode({"data": data}))
```

For this example, compact JSON is 325 bytes, the base64 value is 436 characters, and the full production HTTPS URL with a UUID is 524 characters. Existing configurations using `username_id`, `password_id`, `login_id`, `expected_username`, and `expected_password` continue to work.

## Configure using JSON POST

Larger configurations can avoid the URL payload entirely:

```sh
curl --json @examples/multi-page.json \
  --dump-header - \
  http://localhost:5057/my-test/configure
```

A successful POST returns `303 See Other` with `Location: /my-test/login-step1`. Open that URL in your browser. Use `https://dyn-login.jcheng.org` as the base after production deployment. This endpoint accepts the same configuration object as GET, validates it completely before replacing existing data, and renews the same 30-day expiration.

## Size limits

There is no universal size limit for an individual query parameter. The browser and each server along the route constrain the complete URL or request line.

- The current Gunicorn configuration uses its default **4,094-byte request-line limit**, including the path and query string. [Gunicorn documentation](https://docs.gunicorn.org/en/stable/settings.html#limit-request-line)
- The AWS Application Load Balancer has a **16 KiB request-line limit**. [AWS documentation](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-limits.html)
- The application accepts query strings or POST bodies up to **64 KiB**, but the smaller server limit applies to URLs before the application receives them. JSON POST avoids those URL limits.

The local Werkzeug preview accepts longer URLs than production Gunicorn, so use JSON POST for larger payloads. A local check against the actual Gunicorn configuration accepted a 3,829-byte request line and rejected a 4,229-byte request line with HTTP 400. A 12,000-character expected password was successfully configured and submitted in the POST tests.
