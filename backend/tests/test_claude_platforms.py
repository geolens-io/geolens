"""Claude through Anthropic's API, a gateway, Foundry, Bedrock and Vertex.

No live cloud account is used: the client factory is checked for the class,
endpoint and credentials it builds, and requests go to an httpx mock.
"""

import json
import logging
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.core.ai_credentials import anthropic_configured
from app.core.config import settings
from app.core.config_ai import DEFAULT_LLM_MODEL
from app.core.persistent_config import LLM_PROVIDER, llm_model_default
from app.modules.admin import router as admin_router
from app.platform.extensions.defaults import DefaultAnthropicProvider
from app.processing.ai import llm_loop, probe
from app.processing.ai import router as ai_router
from app.processing.ai.llm_loop import _LLM_TIMEOUT, get_anthropic_client
from tests._logging_state import configured_logging

_PLATFORM_FIELDS = (
    "anthropic_api_key",
    "llm_model",
    "anthropic_base_url",
    "anthropic_foundry_api_key",
    "anthropic_foundry_resource",
    "anthropic_bedrock_api_key",
    "anthropic_bedrock_aws_region",
    "anthropic_bedrock_aws_access_key_id",
    "anthropic_bedrock_aws_secret_access_key",
    "cloud_ml_region",
    "anthropic_vertex_project_id",
    "openai_api_key",
)

_ANTHROPIC_KEY = "fake-anthropic-key-for-tests"
_FOUNDRY_KEY = "fake-foundry-key-for-tests"
_BEDROCK_API_KEY = "fake-bedrock-api-key-for-tests"
_BEDROCK_KEY_ID = "FAKEBEDROCKKEYID"
_BEDROCK_SECRET = "fake-bedrock-secret-for-tests"
_STORAGE_KEY_ID = "FAKESTORAGEKEYID"
_SECRETS = (_ANTHROPIC_KEY, _FOUNDRY_KEY, _BEDROCK_API_KEY, _BEDROCK_SECRET)


@pytest.fixture(autouse=True)
def _fresh_client(monkeypatch):
    """Start every test on the anthropic platform with no credentials."""
    for name in _PLATFORM_FIELDS:
        monkeypatch.setattr(settings, name, None)
    monkeypatch.setattr(settings, "anthropic_platform", "anthropic")
    monkeypatch.setattr(settings, "storage_provider", "local")
    monkeypatch.setattr(settings, "s3_access_key_id", None)
    for name in (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_FOUNDRY_BASE_URL",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "ANTHROPIC_VERTEX_BASE_URL",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(DefaultAnthropicProvider, "_client", None)


def _use(monkeypatch, platform: str, **values: object) -> None:
    monkeypatch.setattr(settings, "anthropic_platform", platform)
    if platform in ("bedrock", "vertex"):
        values = {"llm_model": f"{platform}-claude-model-id", **values}
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def _foundry(monkeypatch) -> None:
    _use(
        monkeypatch,
        "foundry",
        anthropic_foundry_api_key=SecretStr(_FOUNDRY_KEY),
        anthropic_foundry_resource="example-resource",
    )


def _bedrock_keys(monkeypatch) -> None:
    _use(
        monkeypatch,
        "bedrock",
        anthropic_bedrock_aws_region="eu-west-1",
        anthropic_bedrock_aws_access_key_id=_BEDROCK_KEY_ID,
        anthropic_bedrock_aws_secret_access_key=SecretStr(_BEDROCK_SECRET),
    )


def _vertex(monkeypatch) -> None:
    _use(
        monkeypatch,
        "vertex",
        cloud_ml_region="us-east5",
        anthropic_vertex_project_id="example-project",
    )


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def _message_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "test-model",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )


def _with_mock_transport(client, requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _message_response(request)

    return client.with_options(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


# --- The client factory -----------------------------------------------------


def test_anthropic_default_client_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(_ANTHROPIC_KEY))
    # Compose passes the unset variable through as a blank string.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "")

    client = get_anthropic_client()

    assert type(client) is anthropic.AsyncAnthropic
    assert client.api_key == _ANTHROPIC_KEY
    assert str(client.base_url) == "https://api.anthropic.com"
    assert client.timeout is _LLM_TIMEOUT
    assert client.max_retries == 2
    assert get_anthropic_client() is client


def test_anthropic_gateway_base_url(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(_ANTHROPIC_KEY))
    monkeypatch.setattr(settings, "anthropic_base_url", "https://llm-gw.internal/")

    client = get_anthropic_client()

    assert type(client) is anthropic.AsyncAnthropic
    assert str(client.base_url) == "https://llm-gw.internal/"


def test_foundry_client(monkeypatch):
    _foundry(monkeypatch)

    client = get_anthropic_client()

    assert type(client) is anthropic.AsyncAnthropicFoundry
    assert client.api_key == _FOUNDRY_KEY
    assert (
        str(client.base_url)
        == "https://example-resource.services.ai.azure.com/anthropic/"
    )
    assert client.max_retries == 2


def test_bedrock_client_uses_its_own_region_not_the_storage_region(monkeypatch):
    _bedrock_keys(monkeypatch)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")

    client = get_anthropic_client()

    assert type(client) is anthropic.AsyncAnthropicBedrock
    assert client.aws_region == "eu-west-1"
    assert str(client.base_url) == "https://bedrock-runtime.eu-west-1.amazonaws.com"
    assert client.aws_access_key == _BEDROCK_KEY_ID
    assert client.aws_secret_key == _BEDROCK_SECRET
    assert client.api_key is None
    assert client.max_retries == 2


def test_bedrock_api_key(monkeypatch):
    _use(
        monkeypatch,
        "bedrock",
        anthropic_bedrock_aws_region="us-west-2",
        anthropic_bedrock_api_key=SecretStr(_BEDROCK_API_KEY),
    )

    client = get_anthropic_client()

    assert client.api_key == _BEDROCK_API_KEY
    assert client.aws_access_key is None


def test_bedrock_default_chain_without_static_storage_key(monkeypatch):
    _use(monkeypatch, "bedrock", anthropic_bedrock_aws_region="us-west-2")

    client = get_anthropic_client()

    assert client.api_key is None
    assert client.aws_access_key is None
    assert client.aws_secret_key is None


def test_bedrock_default_chain_refused_while_storage_exports_a_static_key(
    monkeypatch,
):
    _use(monkeypatch, "bedrock", anthropic_bedrock_aws_region="us-west-2")
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(settings, "s3_access_key_id", _STORAGE_KEY_ID)

    with pytest.raises(ValueError, match="S3 storage key") as exc_info:
        get_anthropic_client()

    assert _STORAGE_KEY_ID not in str(exc_info.value)
    assert DefaultAnthropicProvider._client is None
    # Readiness agrees, so chat isn't admitted only to fail on every request.
    assert anthropic_configured() is False
    assert admin_router._ai_status(True, "anthropic").configured is False


def test_bedrock_api_key_wins_over_a_stale_key_pair_field(monkeypatch):
    _use(
        monkeypatch,
        "bedrock",
        anthropic_bedrock_aws_region="us-west-2",
        anthropic_bedrock_api_key=SecretStr(_BEDROCK_API_KEY),
        anthropic_bedrock_aws_access_key_id=_BEDROCK_KEY_ID,
    )

    assert anthropic_configured() is True
    client = get_anthropic_client()
    assert client.api_key == _BEDROCK_API_KEY
    assert client.aws_access_key is None


def test_bedrock_half_key_pair_names_the_missing_half(monkeypatch):
    _use(
        monkeypatch,
        "bedrock",
        anthropic_bedrock_aws_region="us-west-2",
        anthropic_bedrock_aws_access_key_id=_BEDROCK_KEY_ID,
    )

    assert anthropic_configured() is False
    with pytest.raises(ValueError, match="needs both") as exc_info:
        get_anthropic_client()
    assert _BEDROCK_KEY_ID not in str(exc_info.value)


@pytest.mark.anyio
async def test_bedrock_signs_with_its_own_keys_not_the_storage_keys(monkeypatch):
    _bedrock_keys(monkeypatch)
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(settings, "s3_access_key_id", _STORAGE_KEY_ID)
    # What configure_gdal_s3_env exports at API and worker start.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", _STORAGE_KEY_ID)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-storage-secret-for-tests")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    requests: list[httpx.Request] = []
    DefaultAnthropicProvider._client = _with_mock_transport(
        get_anthropic_client(), requests
    )

    await DefaultAnthropicProvider().complete(
        model="us.anthropic.claude-test",
        system_prompt="system",
        user_message="ping",
        tools=[{"name": "t", "description": "d", "input_schema": {"type": "object"}}],
        tool_executor=AsyncMock(),
        max_rounds=1,
    )

    (request,) = requests
    assert request.url.host == "bedrock-runtime.eu-west-1.amazonaws.com"
    assert request.url.path == "/model/us.anthropic.claude-test/invoke"
    auth = request.headers["authorization"]
    assert f"Credential={_BEDROCK_KEY_ID}/" in auth
    assert "/eu-west-1/bedrock/" in auth
    assert _STORAGE_KEY_ID not in auth
    # Prompt caching survives the Bedrock request translation.
    body = json.loads(request.content)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_vertex_client(monkeypatch):
    _vertex(monkeypatch)

    client = get_anthropic_client()

    assert type(client) is anthropic.AsyncAnthropicVertex
    assert client.region == "us-east5"
    assert client.project_id == "example-project"
    assert str(client.base_url) == "https://us-east5-aiplatform.googleapis.com/v1/"
    assert client.max_retries == 2


def test_blank_adc_path_from_compose_leaves_keyless_vertex_auth_alone(monkeypatch):
    # Compose passes an unset GOOGLE_APPLICATION_CREDENTIALS as "". google-auth
    # must skip the explicit-file step then, so the attached service account
    # (metadata server) is still reached.
    from google.auth import _default

    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")

    assert _default._get_explicit_environ_credentials() == (None, None)


@pytest.mark.parametrize(
    "configure",
    [
        lambda mp: mp.setattr(settings, "anthropic_api_key", SecretStr(_ANTHROPIC_KEY)),
        _foundry,
        _bedrock_keys,
        _vertex,
    ],
    ids=["anthropic", "foundry", "bedrock", "vertex"],
)
def test_clients_do_not_follow_redirects(monkeypatch, configure):
    configure(monkeypatch)

    assert get_anthropic_client()._client.follow_redirects is False


@pytest.mark.anyio
async def test_gateway_redirect_does_not_carry_the_key_elsewhere(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(_ANTHROPIC_KEY))
    monkeypatch.setattr(settings, "anthropic_base_url", "https://llm-gw.internal")
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(
            307, headers={"location": "https://elsewhere.example/v1/messages"}
        )

    client = get_anthropic_client().with_options(max_retries=0)
    client._client._transport = httpx.MockTransport(handler)

    with pytest.raises(anthropic.APIStatusError):
        await client.messages.create(
            model="test-model",
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    assert hosts == ["llm-gw.internal"]


def test_llm_loop_is_the_only_claude_client_construction_site():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    construction = re.compile(r"\bAsyncAnthropic\w*\(")
    sites = [
        path.relative_to(app_dir).as_posix()
        for path in sorted(app_dir.rglob("*.py"))
        if construction.search(path.read_text())
    ]
    assert sites == ["processing/ai/llm_loop.py"]


@pytest.mark.parametrize(
    ("platform", "message"),
    [
        ("anthropic", "Anthropic API key not configured"),
        ("foundry", "Claude on foundry not configured"),
        ("bedrock", "Claude on bedrock not configured"),
        ("vertex", "Claude on vertex not configured"),
    ],
)
def test_unconfigured_platform_raises(monkeypatch, platform, message):
    _use(monkeypatch, platform)

    with pytest.raises(ValueError, match=message):
        get_anthropic_client()


def test_settings_reads_the_claude_environment(monkeypatch):
    from app.core.config import Settings

    for name, value in {
        "ANTHROPIC_PLATFORM": "bedrock",
        "ANTHROPIC_BEDROCK_AWS_REGION": "eu-west-1",
        "ANTHROPIC_BEDROCK_API_KEY": _BEDROCK_API_KEY,
        "LLM_MODEL": "us.anthropic.claude-test",
        # What Compose passes for an unset variable.
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_BASE_URL": "",
        "LLM_MODEL_LIGHT": " ",
    }.items():
        monkeypatch.setenv(name, value)

    built = Settings(
        postgres_password="testpass",
        jwt_secret_key="testsecret-padding-to-32-chars-min",
        geolens_admin_username="admin",
        geolens_admin_password="adminpass",
    )

    assert built.anthropic_platform == "bedrock"
    assert built.anthropic_bedrock_aws_region == "eu-west-1"
    assert built.anthropic_bedrock_api_key.get_secret_value() == _BEDROCK_API_KEY
    assert built.llm_model == "us.anthropic.claude-test"
    assert built.anthropic_api_key is None
    assert built.anthropic_base_url is None
    assert built.llm_model_light is None


# --- Credentials stay out of logs -------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "configure",
    [
        lambda mp: mp.setattr(settings, "anthropic_api_key", SecretStr(_ANTHROPIC_KEY)),
        _foundry,
        _bedrock_keys,
        lambda mp: _use(
            mp,
            "bedrock",
            anthropic_bedrock_aws_region="us-west-2",
            anthropic_bedrock_api_key=SecretStr(_BEDROCK_API_KEY),
        ),
    ],
    ids=["anthropic", "foundry", "bedrock-keys", "bedrock-api-key"],
)
async def test_credentials_are_never_logged(monkeypatch, configure):
    configure(monkeypatch)
    requests: list[httpx.Request] = []

    # The SDK logs request options, headers included, at DEBUG; the Foundry
    # key travels in an `api-key` header there.
    with configured_logging(log_level="DEBUG"):
        root = logging.getLogger()
        capture = _ListHandler()
        capture.setFormatter(root.handlers[0].formatter)
        root.addHandler(capture)
        try:
            client = _with_mock_transport(get_anthropic_client(), requests)
            await client.messages.create(
                model="test-model",
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
        finally:
            root.removeHandler(capture)

    assert requests
    assert any("Request options" in line for line in capture.lines)
    for secret in _SECRETS:
        assert not [line for line in capture.lines if secret in line]


# --- Provider resolution and the configured checks --------------------------


@pytest.mark.parametrize(
    "configure",
    [_foundry, _bedrock_keys, _vertex],
    ids=["foundry", "bedrock", "vertex"],
)
def test_cloud_platform_is_configured_without_an_anthropic_key(monkeypatch, configure):
    configure(monkeypatch)

    assert anthropic_configured() is True
    assert LLM_PROVIDER.env_default == "anthropic"
    status = admin_router._ai_status(True, "anthropic", model="m")
    assert status.configured is True
    assert status.provider == "anthropic"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "configure", [_bedrock_keys, _vertex], ids=["bedrock", "vertex"]
)
async def test_bedrock_and_vertex_need_a_model_from_env_or_admin(
    monkeypatch, configure
):
    from app.core import persistent_config

    configure(monkeypatch)
    monkeypatch.setattr(settings, "llm_model", None)
    _patch_runtime(monkeypatch, "anthropic")
    overrides = {"chat": "", "light": ""}
    monkeypatch.setattr(
        persistent_config.LLM_MODEL,
        "override",
        AsyncMock(side_effect=lambda db: overrides["chat"]),
    )
    monkeypatch.setattr(
        persistent_config.LLM_MODEL_LIGHT,
        "override",
        AsyncMock(side_effect=lambda db: overrides["light"]),
    )
    db = MagicMock()

    # Neither platform serves Anthropic's model names, so there's no default.
    assert llm_model_default("anthropic") == ""
    assert await ai_router._ai_availability(db) is False
    with pytest.raises(HTTPException) as exc_info:
        await ai_router._check_ai_available(db)
    assert exc_info.value.status_code == 503
    assert admin_router._ai_status(True, "anthropic", model="").configured is False

    # A model an admin set counts, and the light model follows it.
    overrides["chat"] = "admin-set-claude-model-id"

    assert await ai_router._ai_availability(db) is True
    await ai_router._check_ai_available(db)
    assert (
        await persistent_config.LLM_MODEL_LIGHT.for_provider(db, "anthropic")
        == "admin-set-claude-model-id"
    )


def test_foundry_can_use_the_default_model_name(monkeypatch):
    # A Foundry deployment may carry the model's own name.
    _foundry(monkeypatch)

    assert anthropic_configured() is True
    assert llm_model_default("anthropic") == DEFAULT_LLM_MODEL


def test_blank_llm_model_means_the_default(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("LLM_MODEL", "")
    built = Settings(
        postgres_password="testpass",
        jwt_secret_key="testsecret-padding-to-32-chars-min",
        geolens_admin_username="admin",
        geolens_admin_password="adminpass",
    )
    assert built.llm_model is None
    assert llm_model_default("anthropic") == DEFAULT_LLM_MODEL


def test_bedrock_default_chain_counts_as_configured(monkeypatch):
    _use(monkeypatch, "bedrock", anthropic_bedrock_aws_region="us-west-2")

    assert anthropic_configured() is True


@pytest.mark.parametrize(
    ("platform", "values"),
    [
        ("anthropic", {}),
        ("foundry", {"anthropic_foundry_api_key": SecretStr(_FOUNDRY_KEY)}),
        ("foundry", {"anthropic_foundry_resource": "example-resource"}),
        ("bedrock", {}),
        (
            "bedrock",
            {
                "anthropic_bedrock_aws_region": "us-west-2",
                "anthropic_bedrock_aws_access_key_id": _BEDROCK_KEY_ID,
            },
        ),
        ("vertex", {"cloud_ml_region": "us-east5"}),
        ("vertex", {"anthropic_vertex_project_id": "example-project"}),
    ],
)
def test_incomplete_platform_is_not_configured(monkeypatch, platform, values):
    # An Anthropic API key configures only the anthropic platform.
    monkeypatch.setattr(
        settings,
        "anthropic_api_key",
        None if platform == "anthropic" else SecretStr(_ANTHROPIC_KEY),
    )
    _use(monkeypatch, platform, **values)

    assert anthropic_configured() is False
    assert LLM_PROVIDER.env_default == "openai_compatible"
    assert admin_router._ai_status(True, "anthropic").configured is False


@pytest.mark.anyio
async def test_settings_key_status_reports_the_platform(monkeypatch):
    from app.modules.settings import router as settings_router

    _bedrock_keys(monkeypatch)

    status = await settings_router.get_api_key_status(_user=MagicMock())

    assert status.anthropic_configured is True
    assert status.anthropic_platform == "bedrock"
    assert _BEDROCK_SECRET not in status.model_dump_json()

    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(settings, "s3_access_key_id", _STORAGE_KEY_ID)
    monkeypatch.setattr(settings, "anthropic_bedrock_aws_access_key_id", None)
    monkeypatch.setattr(settings, "anthropic_bedrock_aws_secret_access_key", None)

    status = await settings_router.get_api_key_status(_user=MagicMock())

    assert status.anthropic_configured is False
    assert status.anthropic_platform == "bedrock"


def _patch_runtime(monkeypatch, provider: str) -> None:
    enabled = MagicMock()
    enabled.get = AsyncMock(return_value=True)
    selected = MagicMock()
    selected.get = AsyncMock(return_value=provider)
    monkeypatch.setattr(ai_router, "AI_ENABLED", enabled)
    monkeypatch.setattr(ai_router, "LLM_PROVIDER", selected)


@pytest.mark.anyio
async def test_chat_availability_follows_the_platform(monkeypatch):
    _patch_runtime(monkeypatch, "anthropic")

    assert await ai_router._ai_availability(MagicMock()) is False
    with pytest.raises(HTTPException) as exc_info:
        await ai_router._check_ai_available(MagicMock())
    assert exc_info.value.status_code == 503

    _vertex(monkeypatch)

    assert await ai_router._ai_availability(MagicMock()) is True
    await ai_router._check_ai_available(MagicMock())


@pytest.mark.anyio
async def test_probe_treats_a_configured_platform_as_configured(monkeypatch):
    calls: list[dict] = []

    class _Provider:
        async def complete(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        llm_loop,
        "resolve_provider",
        AsyncMock(return_value=("anthropic", "m", {"base_url": None})),
    )
    monkeypatch.setattr(
        "app.platform.extensions.get_ai_provider", lambda name: _Provider()
    )

    assert (await probe._probe_chat(MagicMock())).configured is False
    assert not calls

    _foundry(monkeypatch)
    probe_resolution = llm_loop.resolve_provider.return_value
    llm_loop.resolve_provider.return_value = ("anthropic", "", {"base_url": None})
    assert (await probe._probe_chat(MagicMock())).configured is False
    llm_loop.resolve_provider.return_value = probe_resolution
    result = await probe._probe_chat(MagicMock())

    assert result.configured is True
    assert result.ok is True
    assert len(calls) == 1
