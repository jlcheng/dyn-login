# Known issues

- Accepted availability risk: slow, incomplete POST bodies can exhaust Gunicorn's eight request
  handlers; `timeout=30` does not bound upload duration. Front-end protection remains unverified.
