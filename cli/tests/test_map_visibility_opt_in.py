# SPDX-License-Identifier: Apache-2.0
"""The CLI reads maps with their restricted visibility."""

import pytest

from geolens_cli._sdk_helpers import make_client


@pytest.mark.parametrize("credential", [{}, {"api_key": "key"}, {"bearer_token": "tok"}])
def test_every_client_sends_the_map_visibility_opt_in(credential):
    client = make_client("https://geolens.example.com/api", **credential)

    headers = client.client.get_httpx_client().headers

    assert headers["X-GeoLens-Map-Visibility"] == "restricted"
