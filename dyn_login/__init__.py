"""Configurable, server-rendered login forms backed by DynamoDB."""

import base64
import binascii
import hmac
import json
import math
import os
import re
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Response

from dyn_login.editor import TEMPLATES, configuration_link

FIELDS = {"username_id", "password_id", "login_id", "expected_username", "expected_password"}
ID_FIELDS = ("username_id", "password_id", "login_id")
FIELD_INFO = {
    "username": {"label": "Username", "type": "text", "autocomplete": "username"},
    "password": {"label": "Password", "type": "password", "autocomplete": "current-password"},
    "otp": {"label": "Verification code", "type": "text", "autocomplete": "one-time-code"},
}
PATH_SEGMENT = re.compile(r"[A-Za-z0-9_~-][A-Za-z0-9._~-]*\Z")
LIFETIME = 30 * 86400
COOKIE = "dyn_login"
CONFIG_ID = re.compile(r"[A-Za-z0-9_~-][A-Za-z0-9._~-]{0,127}\Z")


class PageError(Exception):
    def __init__(self, title: str, message: str, status: int = 400) -> None:
        self.title = title
        self.message = message
        self.status = status


def validate_id(config_id: str) -> None:
    if not CONFIG_ID.fullmatch(config_id):
        raise PageError(
            "Invalid configuration ID", "Use a URL-safe name or UUID, up to 128 characters."
        )


def validate_element_ids(ids: list[Any]) -> None:
    if any(
        not isinstance(value, str)
        or not value
        or re.search(r"[\t\n\f\r ]", value)
        or "\x00" in value
        for value in ids
    ):
        raise PageError(
            "Invalid element IDs", "Element IDs must be nonempty strings with no spaces."
        )
    if len(set(ids)) != len(ids):
        raise PageError("Invalid element IDs", "Use a different ID for each element on a page.")


def validate_configuration(configuration: Any) -> dict[str, Any]:
    if not isinstance(configuration, dict):
        raise PageError("Invalid configuration", "The configuration must be a JSON object.")
    if set(configuration) == FIELDS:
        if not all(isinstance(value, str) for value in configuration.values()):
            raise PageError("Invalid configuration", "Every configuration field must be a string.")
        validate_element_ids([configuration[field] for field in ID_FIELDS])
        return {field: configuration[field] for field in FIELDS}
    if set(configuration) != {"expected_credentials", "pages"}:
        raise PageError(
            "Invalid configuration", "Provide expected_credentials and an ordered pages array."
        )
    credentials = configuration["expected_credentials"]
    pages = configuration["pages"]
    if not isinstance(credentials, dict) or not all(
        isinstance(value, str) for value in credentials.values()
    ):
        raise PageError(
            "Invalid credentials", "Expected credentials must be an object of string values."
        )
    if not isinstance(pages, list) or not pages:
        raise PageError("Invalid pages", "Provide at least one login page.")
    paths: set[str] = set()
    fields_seen: set[str] = set()
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or set(page) != {"path", "fields", "submit_id"}:
            raise PageError("Invalid page", "Each page needs path, fields, and submit_id.")
        path = page["path"]
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or not all(PATH_SEGMENT.fullmatch(segment) for segment in path[1:].split("/"))
            or path in {"/profile", "/logout", "/configure"}
            or (path == "/login" and index != 0)
        ):
            raise PageError(
                "Invalid page path",
                "Use a URL-safe path without reserved routes or query parameters.",
            )
        if path in paths:
            raise PageError("Duplicate page path", "Each page must have its own path.")
        paths.add(path)
        fields = page["fields"]
        if not isinstance(fields, dict) or not fields or not set(fields) <= FIELD_INFO.keys():
            raise PageError("Invalid page fields", "Use username, password, or otp fields.")
        if fields_seen.intersection(fields):
            raise PageError("Repeated field", "Each credential may appear on only one page.")
        fields_seen.update(fields)
        validate_element_ids([*fields.values(), page["submit_id"]])
    if not {"username", "password"} <= fields_seen or set(credentials) != fields_seen:
        raise PageError(
            "Invalid credentials",
            "Include username and password, and expected values for all configured fields.",
        )
    return {"expected_credentials": credentials, "pages": pages}


def decode_configuration(data: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
        configuration = json.loads(raw.decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeError):
        raise PageError(
            "Invalid configuration", "The data must be base64-encoded UTF-8 JSON."
        ) from None
    return validate_configuration(configuration)


def flow_pages(configuration: dict[str, Any]) -> list[dict[str, Any]]:
    if "pages" in configuration:
        pages: list[dict[str, Any]] = configuration["pages"]
        return pages
    return [
        {
            "path": "/login",
            "fields": {
                "username": configuration["username_id"],
                "password": configuration["password_id"],
            },
            "submit_id": configuration["login_id"],
        }
    ]


def expected_credentials(configuration: dict[str, Any]) -> dict[str, str]:
    if "expected_credentials" in configuration:
        credentials: dict[str, str] = configuration["expected_credentials"]
        return credentials
    return {
        "username": configuration["expected_username"],
        "password": configuration["expected_password"],
    }


def create_app(settings: dict[str, Any] | None = None, *, table: Any = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SESSION_SIGNING_KEY"),
        CLOCK=time.time,
        MAX_CONTENT_LENGTH=64 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        PREVIEW=False,
    )
    if settings:
        app.config.update(settings)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError(
            "SESSION_SIGNING_KEY is required; use fnox exec to start the application."
        )
    if table is None:
        table = boto3.resource(
            "dynamodb", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
        ).Table(os.environ.get("DYNAMODB_TABLE", "dyn-login-configs"))
    clock: Callable[[], float] = app.config["CLOCK"]
    signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="dyn-login-session-v1")

    def get_configuration(config_id: str) -> dict[str, Any]:
        validate_id(config_id)
        item: dict[str, Any] | None = table.get_item(
            Key={"config_id": config_id}, ConsistentRead=True
        ).get("Item")
        if item is None:
            raise PageError(
                "Configuration not found",
                "This login page has not been configured. Create a configuration to get started.",
                404,
            )
        if Decimal(str(clock())) >= item["expires_at"]:
            raise PageError(
                "Configuration expired",
                "This configuration expired after 30 days. Configure this ID again to continue.",
                410,
            )
        return item

    def progress(config_id: str, item: dict[str, Any]) -> int:
        token = request.cookies.get(COOKIE)
        if not token:
            return 0
        try:
            state = signer.loads(token)
        except BadSignature:
            return 0
        if (
            not isinstance(state, dict)
            or state.get("config_id") != config_id
            or state.get("version") != item["version"]
        ):
            return 0
        step = state.get("step")
        if type(step) is not int or not 0 <= step <= len(flow_pages(item["configuration"])):
            return 0
        return step

    def page_url(config_id: str, page: dict[str, Any]) -> str:
        return f"/{config_id}{page['path']}"

    def set_progress(
        response: Response, config_id: str, item: dict[str, Any], step: int
    ) -> Response:
        response.set_cookie(
            COOKIE,
            signer.dumps({"config_id": config_id, "version": item["version"], "step": step}),
            path=f"/{config_id}/",
            secure=True,
            httponly=True,
            samesite="Lax",
        )
        return response

    def clear_cookie(response: Response, config_id: str) -> Response:
        response.delete_cookie(
            COOKIE, path=f"/{config_id}/", secure=True, httponly=True, samesite="Lax"
        )
        return response

    @app.after_request
    def response_headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        if request.endpoint == "editor":
            response.headers["Content-Security-Policy"] += "; script-src 'self'; connect-src 'self'"
        return response

    @app.errorhandler(PageError)
    def page_error(error: PageError) -> tuple[str, int]:
        return render_template("error.html", title=error.title, message=error.message), error.status

    @app.errorhandler(ClientError)
    @app.errorhandler(BotoCoreError)
    def storage_error(error: Exception) -> tuple[str, int]:
        # SDK exception text can contain request data, so deliberately omit it.
        app.logger.error("Configuration storage is unavailable (%s)", type(error).__name__)
        return render_template(
            "error.html", title="Temporarily unavailable", message="Please try your request again."
        ), 503

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> tuple[str, int]:
        return render_template(
            "error.html", title=error.name, message=error.description
        ), error.code or 500

    @app.get("/")
    def home() -> str:
        return render_template("home.html", preview=app.config["PREVIEW"])

    @app.route("/editor", methods=["GET", "POST"])
    def editor() -> str | dict[str, Any] | tuple[dict[str, Any], int]:
        if request.method == "GET":
            return render_template(
                "editor.html",
                templates=TEMPLATES,
                config_id=str(uuid4()),
                initial_json=json.dumps(
                    TEMPLATES["single"]["configuration"], indent=2, ensure_ascii=False
                ),
            )
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or not isinstance(payload.get("config_id"), str):
                raise PageError(
                    "Invalid request", "Provide a configuration ID and configuration JSON."
                )
            validate_id(payload["config_id"])
            configuration = validate_configuration(payload.get("configuration"))
            return configuration_link(payload["config_id"], configuration)
        except PageError as error:
            return {"valid": False, "error": f"{error.title}: {error.message}"}, error.status
        except HTTPException as error:
            return {"valid": False, "error": error.description}, error.code or 400

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.route("/<config_id>/configure", methods=["GET", "POST"])
    def configure(config_id: str) -> Response:
        validate_id(config_id)
        if len(request.query_string) > 64 * 1024:
            raise PageError(
                "Request too large", "The configuration URL exceeds the request limit.", 413
            )
        configuration = (
            validate_configuration(request.get_json())
            if request.method == "POST"
            else decode_configuration(request.args.get("data", ""))
        )
        expiration = Decimal(str(clock())) + LIFETIME
        # A single PutItem atomically replaces the entire configuration and its version.
        table.put_item(
            Item={
                "config_id": config_id,
                "configuration": configuration,
                "version": str(uuid4()),
                "expires_at": expiration,
                "ttl": math.ceil(expiration),
            }
        )
        response = redirect(
            page_url(config_id, flow_pages(configuration)[0]),
            code=303 if request.method == "POST" else 302,
        )
        return clear_cookie(response, config_id)

    def render_page(config_id: str, path: str, item: dict[str, Any]) -> Response | str:
        configuration = item["configuration"]
        pages = flow_pages(configuration)
        index = next((i for i, page in enumerate(pages) if page["path"] == path), None)
        if index is None:
            raise PageError(
                "Page not found", "This path is not part of the configured login flow.", 404
            )
        completed = progress(config_id, item)
        if request.method == "GET" and completed == len(pages):
            return redirect(url_for("profile", config_id=config_id))
        if index > completed:
            return redirect(page_url(config_id, pages[completed]))
        page = pages[index]
        fields = [
            {"name": name, "element_id": page["fields"][name], **info}
            for name, info in FIELD_INFO.items()
            if name in page["fields"]
        ]
        error = None
        if request.method == "POST":
            expected = expected_credentials(configuration)
            matches = [
                name in request.form
                and hmac.compare_digest(
                    request.form[name].encode("utf-8"), expected[name].encode("utf-8")
                )
                for name in page["fields"]
            ]
            if all(matches):
                next_step = index + 1
                destination = (
                    url_for("profile", config_id=config_id)
                    if next_step == len(pages)
                    else page_url(config_id, pages[next_step])
                )
                return set_progress(redirect(destination), config_id, item, next_step)
            label = (
                fields[0]["label"]
                if len(fields) == 1
                else "Username or password"
                if set(page["fields"]) == {"username", "password"}
                else "One or more credentials"
            )
            error = f"{label} is incorrect. Please try again."
        html = render_template(
            "login.html",
            config_id=config_id,
            page=page,
            fields=fields,
            page_index=index,
            page_count=len(pages),
            action=page_url(config_id, page),
            error=error,
        )
        if error:
            return set_progress(app.make_response((html, 401)), config_id, item, index)
        return html

    @app.route("/<config_id>/login", methods=["GET", "POST"])
    def login(config_id: str) -> Response | str:
        item = get_configuration(config_id)
        pages = flow_pages(item["configuration"])
        if pages[0]["path"] == "/login":
            return render_page(config_id, "/login", item)
        completed = progress(config_id, item)
        if completed == len(pages):
            return redirect(url_for("profile", config_id=config_id))
        return redirect(page_url(config_id, pages[completed]))

    @app.route("/<config_id>/<path:page_path>", methods=["GET", "POST"])
    def login_page(config_id: str, page_path: str) -> Response | str:
        return render_page(config_id, f"/{page_path}", get_configuration(config_id))

    @app.get("/<config_id>/profile")
    def profile(config_id: str) -> Response | str:
        item = get_configuration(config_id)
        pages = flow_pages(item["configuration"])
        completed = progress(config_id, item)
        if completed != len(pages):
            return redirect(page_url(config_id, pages[completed]))
        return render_template(
            "profile.html",
            config_id=config_id,
            username=expected_credentials(item["configuration"])["username"],
        )

    @app.get("/<config_id>/logout")
    def logout(config_id: str) -> Response:
        item = get_configuration(config_id)
        return clear_cookie(
            redirect(page_url(config_id, flow_pages(item["configuration"])[0])), config_id
        )

    return app
