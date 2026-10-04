"""The stored names of a source file's fields, as the replacement preview reads them."""

import pytest

from app.platform.column_names import stored_column_names


@pytest.mark.parametrize(
    ("source", "stored"),
    [
        (["name", "Road-Name"], ["name", "road_name"]),
        (["geom"], ["src_geom"]),
        (["geom", "src_geom"], ["src_geom_2", "src_geom"]),
        (["src_geom", "geom"], ["src_geom", "src_geom_2"]),
        (["geom", "src_geom", "src_geom_2"], ["src_geom_3", "src_geom", "src_geom_2"]),
        ([":geom", "geom", "src_geom"], ["src_geom_2", "src_geom_3", "src_geom"]),
        ([], []),
    ],
)
def test_a_rename_that_collides_takes_the_next_free_suffix(source, stored):
    assert stored_column_names(source) == stored
