"""The vendored schemas must still match the catalog's.

Two repos now share the fixture format. The scanner here writes
fixtures; the loader in openforge-catalog validates them against its own
copy of the same schemas. If the copies drift, the scanner writes
something the loader rejects, and nothing notices until a deploy.

This fails rather than skips when the catalog is not found. A check that
quietly passes when it cannot see what it is checking is worse than no
check: it reports green for the one state it was written to catch.
"""

import os
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
OURS = HERE / "openforge_library/openapi/schemas"

# A sibling checkout by default, because that is how these two sit on
# disk. The variable is for anywhere they do not.
CATALOG = Path(
    os.environ.get("OPENFORGE_CATALOG", HERE.parent / "openforge-catalog")
)
THEIRS = CATALOG / "openforge/openapi/schemas"

# The fixture format, owned by the catalog while the loader lives there.
# The others under OURS describe the model library's own folder metadata
# and have no counterpart to drift from.
SHARED = ("blueprint.fixture.json", "config.yaml")


def test_the_catalog_is_somewhere_this_can_see_it():
    assert CATALOG.is_dir(), (
        f"no catalog checkout at {CATALOG}. Set OPENFORGE_CATALOG to where it "
        "is. This refuses to skip: the drift it guards against is invisible "
        "until a deploy fails."
    )


@pytest.mark.parametrize("name", SHARED)
def test_a_shared_schema_matches_the_catalogs(name):
    theirs = THEIRS / name
    assert theirs.is_file(), f"{name} is gone from the catalog"
    assert (OURS / name).read_text() == theirs.read_text(), (
        f"{name} differs from the catalog's. The scanner would write fixtures "
        "the loader does not accept. Copy the catalog's version over this one, "
        "or move the format here if the catalog is no longer its owner."
    )


def test_every_schema_the_scanner_validates_against_is_vendored():
    """A new validate_schema call must bring its schema with it."""
    asked = set()
    for source in (HERE / "openforge_library").rglob("*.py"):
        asked |= set(re.findall(r'validate_schema\(\s*"([^"]+)"', source.read_text()))

    assert asked, "found no validate_schema calls at all — has it been renamed?"
    missing = sorted(n for n in asked if not (OURS / n).is_file())
    assert not missing, f"validated against but not vendored: {missing}"
