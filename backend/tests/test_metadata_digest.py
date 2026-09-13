"""Staged-table identity used by one-time refresh acceptance."""

from sqlalchemy import text

from app.processing.ingest.metadata import compute_table_content_digest


async def test_content_digest_ignores_row_order_and_generated_ids_but_not_data(
    test_db_session,
) -> None:
    for table_name in ("digest_a", "digest_b", "digest_attribute", "digest_geometry"):
        await test_db_session.execute(
            text(
                f"""
                CREATE TEMP TABLE {table_name} (
                    gid bigint PRIMARY KEY,
                    name text,
                    geom geometry(Point, 4326),
                    geom_4326 geometry(Point, 4326)
                )
                """
            )
        )

    statements = (
        """
        INSERT INTO digest_a VALUES
            (1, 'alpha', ST_Point(1, 2, 4326), ST_Point(1, 2, 4326)),
            (2, 'beta', ST_Point(3, 4, 4326), ST_Point(3, 4, 4326))
        """,
        """
        INSERT INTO digest_b VALUES
            (20, 'beta', ST_Point(3, 4, 4326), ST_Point(3, 4, 4326)),
            (10, 'alpha', ST_Point(1, 2, 4326), ST_Point(1, 2, 4326))
        """,
        "INSERT INTO digest_attribute SELECT * FROM digest_a",
        "UPDATE digest_attribute SET name = 'changed' WHERE name = 'alpha'",
        "INSERT INTO digest_geometry SELECT * FROM digest_a",
        """
        UPDATE digest_geometry
        SET geom = ST_Point(8, 9, 4326), geom_4326 = ST_Point(8, 9, 4326)
        WHERE name = 'alpha'
        """,
    )
    for statement in statements:
        await test_db_session.execute(text(statement))

    async def digest(table_name: str) -> str:
        return await compute_table_content_digest(
            test_db_session,
            table_name,
            schema="pg_temp",
            has_geometry=True,
        )

    baseline = await digest("digest_a")
    assert await digest("digest_b") == baseline
    assert await digest("digest_attribute") != baseline
    assert await digest("digest_geometry") != baseline
