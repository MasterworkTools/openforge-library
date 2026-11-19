"""Smallest check that the in-memory finders and the engine still agree on
facts we know. Run: python3 tools/test_sweep.py"""
import yaml

import sweep as W
from sweep import E

cat = W.Catalog(W.load_records())
doc = yaml.safe_load((W.CATALOG / "openforge/db/fixtures/guides/wall.yaml").read_text())
ref = {r["key"]: r for r in doc["refinements"]}
clips = "connection|openlock,connection|openlock|unsupported"


def wall_base(texture):
    return E._union([
        doc["roles"]["wall-base"]["query"],
        E._refinement_predicate(ref["texture"], texture, "wall-base"),
        E._refinement_predicate(ref["base-clips"], clips, "wall-base"),
        {"require": ["shape|base|wall"]},  # what "walls plus bases" adds
    ])


# Devon's example: straight unsupported wall bases exist in aztlan, not in
# dungeon stone (whose unsupported bases are all curved).
assert cat.exists(wall_base("texture|aztlan"))
assert not cat.exists(wall_base("texture|dungeon_stone"))
# A later answer can widen a predicate (require is exempt from deny_children),
# which is why the sweep only prunes on the sweep-free superset.
p = {"require": ["shape|base"], "deny_children": ["connection"]}
assert len(cat.match({**p, "require": p["require"] + ["connection|openlock"]})) > 0
print("ok")

# A renamed file's deprecated old-name row shares its md5; it must not leak
# the old hand into the live record.
_wing = next(r for r in W.load_records() if r["blueprint_name"] == "dungeon_stone#corner+left,wall.2x.openforge,side.stl")
assert "shape|corner|right" not in _wing["tags"], _wing["tags"]
print("ok")
