"""Local preview with a temporary DynamoDB emulator. Never connects to AWS."""

import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager

import boto3
import click
from flask import Flask
from werkzeug.serving import WSGIRequestHandler, run_simple

from dyn_login import create_app


@contextmanager
def preview_app() -> Iterator[Flask]:
    from moto import mock_aws

    with mock_aws():
        table = boto3.resource("dynamodb", region_name="us-west-2").create_table(
            TableName="dyn-login-configs",
            KeySchema=[{"AttributeName": "config_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "config_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        app = create_app({"SECRET_KEY": secrets.token_urlsafe(32), "PREVIEW": True}, table=table)
        configuration = {
            "username_id": "user-field",
            "password_id": "password-field",
            "login_id": "submit-button",
            "expected_username": "test-user",
            "expected_password": "test-password",
        }
        configurations = {
            "demo": configuration,
            "multi-demo": {
                "expected_credentials": {
                    "username": "test-user",
                    "password": "test-password",
                    "otp": "123456",
                },
                "pages": [
                    {
                        "path": "/login-step1",
                        "fields": {"username": "un"},
                        "submit_id": "next-username",
                    },
                    {
                        "path": "/login-step2",
                        "fields": {"password": "p"},
                        "submit_id": "next-password",
                    },
                    {"path": "/login-step3", "fields": {"otp": "o"}, "submit_id": "sign-in"},
                ],
            },
        }
        for config_id, config in configurations.items():
            app.test_client().post(f"/{config_id}/configure", json=config)
        yield app


class PathOnlyRequestHandler(WSGIRequestHandler):
    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        self.log("info", "%s %s %s", self.command, self.path.split("?", 1)[0], code)


@click.command()
@click.option("--port", default=5057, type=int, show_default=True)
def main(port: int) -> None:
    """Open a local test site; configurations reset when this process stops."""
    logging.getLogger("botocore").setLevel(logging.WARNING)
    with preview_app() as app:
        click.echo(f"Preview: http://localhost:{port}/multi-demo/login")
        click.echo("Demo credentials: test-user / test-password; verification code: 123456")
        run_simple("localhost", port, app, threaded=True, request_handler=PathOnlyRequestHandler)


if __name__ == "__main__":
    main()
