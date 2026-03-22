"""Search scenario tasks for GeoLens load testing.

Exercises full-text search and hybrid (FTS + vector) search endpoints.
"""

import random

from common import AUTH_HEADERS, SEARCH_TERMS


def search_fts(client):
    """Full-text search with a random query term."""
    term = random.choice(SEARCH_TERMS)
    with client.get(
        f"/search/datasets?q={term}&limit=20&offset=0",
        headers=AUTH_HEADERS,
        name="/search/datasets?q=[term]",
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        else:
            resp.failure(f"FTS search returned {resp.status_code}")


def search_hybrid(client):
    """Hybrid RRF search (FTS + vector) with a random query term."""
    term = random.choice(SEARCH_TERMS)
    with client.get(
        f"/search/datasets?q={term}&limit=20&offset=0&search_mode=hybrid",
        headers=AUTH_HEADERS,
        name="/search/datasets?q=[term]&search_mode=hybrid",
        catch_response=True,
    ) as resp:
        if resp.status_code == 200:
            resp.success()
        else:
            resp.failure(f"Hybrid search returned {resp.status_code}")
