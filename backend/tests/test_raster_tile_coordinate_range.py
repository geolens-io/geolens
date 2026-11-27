"""Raster tiles refuse an out-of-range z/x/y as vector tiles do."""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.parametrize(
    "path",
    ["30/0/0", "23/0/0", "2/9/9", "2/4/0", "2/0/4"],
)
async def test_an_out_of_range_tile_answers_400_before_any_dataset_lookup(client, path):
    resp = await client.get(f"/tiles/raster-proxy/{uuid.uuid4()}/{path}.png")
    assert resp.status_code == 400


async def test_an_in_range_tile_of_an_unknown_dataset_still_answers_404(client):
    resp = await client.get(f"/tiles/raster-proxy/{uuid.uuid4()}/2/3/3.png")
    assert resp.status_code == 404
