# SPDX-License-Identifier: Apache-2.0
"""`geolens login` reports a dropped connection like every other command."""

from __future__ import annotations

import httpx
import pytest

from geolens_cli.main import app


@pytest.mark.parametrize(
    "error",
    [
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        httpx.ConnectError("connection refused"),
    ],
)
def test_login_maps_a_dropped_connection_to_exit_4(
    runner, tmp_xdg_home, mock_keyring, monkeypatch, error
):
    def fail(**_kwargs):
        raise error

    monkeypatch.setattr(
        "geolens.api.auth.login_auth_login_post.sync_detailed", fail
    )
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "pw")

    result = runner.invoke(
        app,
        ["login", "https://geolens.example.org/api", "--no-keyring"],
        input="user\n",
    )

    assert result.exit_code == 4, result.output
    assert "Network error" in result.output
    assert "Traceback" not in result.output
