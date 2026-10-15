import base64
import json
from urllib.parse import urlencode

import boto3
import pytest
from moto import mock_aws

from dyn_login import create_app


@pytest.fixture
def config():
    return {
        "username_id": "user-field",
        "password_id": "password-field",
        "login_id": "submit-button",
        "expected_username": "test-user",
        "expected_password": "test-password",
    }


def configure_url(config_id, config):
    encoded = base64.urlsafe_b64encode(json.dumps(config).encode()).decode()
    return f"/{config_id}/configure?{urlencode({'data': encoded})}"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="us-west-2").create_table(
            TableName="dyn-login-configs",
            KeySchema=[{"AttributeName": "config_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "config_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        clock = [1_800_000_000.25]
        application = create_app(
            {"TESTING": True, "SECRET_KEY": "test-signing-key", "CLOCK": lambda: clock[0]},
            table=table,
        )
        application.test_table = table
        application.test_clock = clock
        yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def configured(client, config):
    client.get(configure_url("alpha", config))
    return client


@pytest.fixture
def flow_config():
    return {
        "expected_credentials": {
            "username": "test-user",
            "password": "test-password",
            "otp": "123456",
        },
        "pages": [
            {"path": "/login-step1", "fields": {"username": "un"}, "submit_id": "next-username"},
            {"path": "/login-step2", "fields": {"password": "p"}, "submit_id": "next-password"},
            {"path": "/login-step3", "fields": {"otp": "o"}, "submit_id": "sign-in"},
        ],
    }
