"""Dead branches in the build guides, judged by the guide engine itself.

Drives openforge-catalog's own engine (openforge.guides.resolve) with
in-memory finders over the blueprint fixtures, so it needs no database and
agrees with the live site by construction: the same predicate composition,
the same `under`/`match` inheritance, the same prefer-dropping search.

Two passes per guide:

  roles     For each role, walk every reachable combination of the answers
            that narrow it (or the piece it sits under), pruning the moment
            the role's predicate comes back empty. A base is checked against
            the actual recommendation of the piece above it. Each dead
            branch is shrunk to its minimal answers.
  textures  For each texture and method: is there any complete build at all,
            and is the texture offered? Also whether a same-texture floor
            completes it.

Run:  python3 tools/sweep.py > sweep.json
"""

import collections
import functools
import itertools
import json
import pathlib
import sys

import yaml

CATALOG = pathlib.Path("/home/devon/MasterworkTools/openforge-catalog")
sys.path.insert(0, str(CATALOG))
from openforge.guides import resolve as E  # noqa: E402

GUIDES = ("floor", "wall", "corner")


# ---------------------------------------------------------------- catalog


def load_records():
    """The blueprints as the fixture loader leaves them in the database."""
    recs, by_md5 = [], {}
    for p in sorted((CATALOG / "openforge/db/fixtures/blueprints").iterdir()):
        if p.suffix == ".json":
            data = json.loads(p.read_text())
        elif p.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(p.read_text()) or []
        else:
            continue
        for d in data:
            fm = d.get("file_metadata") or {}
            # A rename leaves the old-name row behind, deprecated, with the
            # same md5; merged by md5 it would give the live file both hands
            # or make it deprecated. The search never returns deprecated rows.
            if d.get("deprecated"):
                continue
            tags = {t if isinstance(t, str) else "|".join(t) for t in d.get("tags", [])}
            md5 = fm.get("md5")
            # insert_blueprint(rescue_md5_conflict=True): the first row wins
            # and the duplicate's tags are added to it.
            if md5 and md5 in by_md5:
                by_md5[md5]["tags"] |= tags
                continue
            r = {
                "id": len(recs),
                "blueprint_name": d.get("name") or fm.get("file") or "",
                "type": d["type"],
                "full_name": fm.get("full_name"),
                "tags": tags,
            }
            recs.append(r)
            if md5:
                by_md5[md5] = r
    # The search runs with models=True, blueprints=False.
    return [r for r in recs if r["type"] == "model"]


class Catalog:
    """The four finders the route builds from SQL, over records in memory."""

    def __init__(self, recs):
        self.byid = {r["id"]: r for r in recs}
        self.all = frozenset(self.byid)
        self.exact = collections.defaultdict(set)
        self.prefix = collections.defaultdict(set)
        self.below = collections.defaultdict(set)
        for r in recs:
            for t in r["tags"]:
                self.exact[t].add(r["id"])
                parts = t.split("|")
                for i in range(1, len(parts) + 1):
                    self.prefix["|".join(parts[:i])].add(r["id"])
                for i in range(1, len(parts)):
                    self.below["|".join(parts[:i])].add(t)
        self.memo = {}
        self.best = {}

    def match(self, pred):
        key = E._predicate_key(pred)
        if key in self.memo:
            return self.memo[key]
        s = set(self.all)
        for t in pred.get("require", []):
            s &= self.exact.get(t, set())
        for t in pred.get("accept", []):
            s &= self.prefix.get(t, set())
        for t in pred.get("deny", []):
            s -= self.exact.get(t, set())
        exempt = set(pred.get("require", [])) | set(pred.get("allow", []))
        for parent in pred.get("deny_children", []):
            for t in self.below.get(parent, ()):
                if t not in exempt:
                    s -= self.exact[t]
        self.memo[key] = s = frozenset(s)
        return s

    def find_candidates(self, pred):
        # ponytail: ties on blueprint_name break by load order here and by
        # uuid in Postgres, so a tied recommendation can differ from the site.
        s = self.match(pred)
        if not s:
            return []
        r = min((self.byid[i] for i in s), key=lambda r: (r["blueprint_name"], r["id"]))
        return [{"id": r["id"], "blueprint_name": r["blueprint_name"],
                 "full_name": r["full_name"], "tags": sorted(r["tags"])}]

    def exists(self, pred):
        return bool(self.match(pred))

    def facets(self, pred, namespace):
        ns = namespace.split("|")
        counts = collections.Counter(
            t for i in self.match(pred) for t in self.byid[i]["tags"]
            if len(t.split("|")) == len(ns) + 1 and t.split("|")[: len(ns)] == ns
        )
        return [{"tag": t, "count": n} for t, n in sorted(counts.items())]

    def combinations(self, pred, namespace, exclude):
        ns = namespace.split("|")
        ex = [e.split("|") for e in exclude or []]
        counts = collections.Counter()
        for i in self.match(pred):
            combo = tuple(sorted(
                t for t in self.byid[i]["tags"]
                if len(t.split("|")) > len(ns) and t.split("|")[: len(ns)] == ns
                and not any(t.split("|")[: len(e)] == e for e in ex)
            ))
            if combo:
                counts[combo] += 1
        return [{"tags": list(c), "count": n} for c, n in sorted(counts.items())]

    def recommend(self, pred, role):
        key = (E._predicate_key(pred), tuple(role.get("prefer", [])), tuple(role.get("avoid", [])))
        if key not in self.best:
            self.best[key] = E._recommend(pred, role.get("prefer", []), self.find_candidates, role.get("avoid", []))
        return self.best[key]


# ---------------------------------------------------------------- guide


def universe(cat, doc, ref, roles):
    """Every answer a refinement could be given, not only the ones offered:
    what any piece of the kind these roles ask for carries, in any texture."""
    if "on_tags" in ref:
        return ["on", "off"]
    ns = ref.get("from_namespace") or ref.get("from_combination")
    vals = {c["tag"] for c in ref.get("choices", [])}
    for name in roles:
        if not E._reaches(ref, name):
            continue
        q = doc["roles"][name]["query"]
        if "from_combination" in ref:
            vals |= {",".join(sorted(a["tags"])) for a in cat.combinations(q, ns, ref.get("exclude", []))}
        else:
            vals |= {a["tag"] for a in cat.facets(q, ns)}
    return sorted(vals)


def open_choices(cat, doc):
    """The document with every closed list widened to its universe, so the
    engine will judge textures it does not offer. Returns what was offered."""
    offered = {}
    for ref in doc.get("refinements", []):
        everything = universe(cat, doc, ref, doc["roles"])
        if ref.get("choices"):
            offered[ref["key"]] = [c["tag"] for c in ref["choices"]]
            ref["choices"] = [{"tag": t, "title": t} for t in everything]
        else:
            # Derived: the guide offers whatever the parts carry.
            # ponytail: counts every texture any part carries as offered; the
            # engine intersects per role, so a texture only one role has is
            # shown offered here and hidden on the site.
            offered[ref["key"]] = everything
    return offered


class State:
    def __init__(self, doc, sel):
        self.steps, self.answered = E._available_steps(doc, sel)
        self.chosen = E._chosen_options(self.steps, self.answered)
        self.in_play = E._roles_in_play(self.chosen)
        self.steps_done = all(s["key"] in self.answered for s in self.steps)
        self.refs = E._available_refinements(doc, self.answered, self.in_play) if self.steps_done else []
        self.doc, self.sel = doc, sel

    def pred(self, name):
        return E._compose(self.doc["roles"][name]["query"], self.chosen, self.refs, self.sel, name)

    def next_question(self, wanted):
        if not self.steps_done:
            return self.steps[-1]
        return next((r for r in self.refs if r["key"] not in self.sel and wanted(r)), None)


def answers(cat, doc, st, q):
    if "options" in q:
        return [o["key"] for o in q["options"]]
    return universe(cat, doc, q, st.in_play)


def hopeless(cat, pred):
    """Empty even with every child sweep removed.

    The only sound prune. A later answer can *widen* a predicate: what it
    requires is exempt from `deny_children`, so the wings with side clips
    appear only once the side-lock question is answered. Dropping the
    sweeps gives a superset of every extension, so if that is empty, no
    answer still to come can fill the role.
    """
    return not cat.exists({k: v for k, v in pred.items() if k not in ("deny_children", "allow")})


def role_dead(cat, doc, sel, name):
    """Why this role is empty under these answers, or None.

    'empty': its own predicate matches nothing.
    {'under': ...}: it exists, but not to fit the piece the guide picks above it.
    """
    st = State(doc, sel)
    if name not in st.in_play:
        return None
    if not cat.exists(st.pred(name)):
        return "empty"
    role = doc["roles"][name]
    above = role.get("under")
    if role.get("match") and above in st.in_play:
        bp = cat.recommend(st.pred(above), doc["roles"][above])
        if bp is None:
            return None  # the piece above is the gap, reported under its own role
        inherited = E._matched(role, {above: {"blueprint": bp}})
        if not cat.exists(E._union([st.pred(name), inherited])):
            return {"under": above, "requires": inherited.get("require", []), "above": bp["full_name"]}
    return None


def sweep_role(cat, doc, name, limit=2_000_000):
    role = doc["roles"][name]
    above = role.get("under") if role.get("match") else None

    def wanted(ref):
        return E._reaches(ref, name) or (above and E._reaches(ref, above))

    dead, seen, alive = [], [0], set()

    def walk(sel):
        seen[0] += 1
        if seen[0] > limit:
            raise RuntimeError(f"{doc['key']}:{name} passed {limit} states")
        st = State(doc, sel)
        if name in st.in_play and hopeless(cat, st.pred(name)):
            dead.append(dict(sel))
            return
        if above in st.in_play and hopeless(cat, st.pred(above)):
            return  # the piece above is the gap
        q = st.next_question(wanted)
        if q is None:
            if role_dead(cat, doc, sel, name):
                dead.append(dict(sel))
            elif name in st.in_play:
                alive.add(sel.get("floor-texture") if name == "floor" and "floor-texture" in sel else sel.get("texture"))
            return
        for a in answers(cat, doc, st, q):
            walk({**sel, q["key"]: a})

    walk({})
    return dead, seen[0], alive


def minimal(cat, doc, sel, name, dead_at, cap=20_000):
    """Widen a dead branch to '*' wherever it stays dead.

    Greedy, in question order, and joint: a key is starred only if every
    combination of it with the keys already starred is dead (or does not
    apply). Starring each key on its own would claim combinations nobody
    checked. Steps whose change reshapes the branch are left as they are.
    """
    shape = set(State(doc, sel).answered)
    starred = {}
    for key in list(sel):
        if key == "method":
            continue
        st = State(doc, {k: v for k, v in sel.items() if k != key})
        q = next((s for s in st.steps if s["key"] == key), None) or next(
            (r for r in st.refs if r["key"] == key), None)
        if q is None:
            continue
        alts = answers(cat, doc, st, q)
        if len(alts) < 2:
            continue
        trial_keys = {**starred, key: alts}
        size = 1
        for v in trial_keys.values():
            size *= len(v)
        if size > cap:
            continue
        ok = True
        for combo in itertools.product(*trial_keys.values()):
            trial = {**sel, **dict(zip(trial_keys, combo))}
            if set(State(doc, trial).answered) != shape:
                continue
            if dead_at(trial) is False:
                ok = False
                break
        if ok:
            starred[key] = alts
    return {**sel, **{k: "*" for k in starred}}


def covers(pattern, sel):
    return all(v == "*" or sel.get(k) == v for k, v in pattern.items())


def complete(cat, doc, fixed, limit=200_000):
    """Is there any full set of answers, starting from `fixed`, under which
    every role in play resolves to a piece? Returns that set or None."""
    seen = [0]

    def walk(sel):
        seen[0] += 1
        if seen[0] > limit:
            raise RuntimeError("limit")
        st = State(doc, sel)
        if any(hopeless(cat, st.pred(n)) for n in st.in_play):
            return None
        q = st.next_question(lambda r: True)
        if q is None:
            parts = E._parts(doc, st.chosen, st.refs, sel, cat.find_candidates)
            return sel if all(p["blueprint"] for p in parts) else None
        for a in answers(cat, doc, st, q):
            if q["key"] in fixed and a != fixed[q["key"]]:
                continue
            found = walk({**sel, q["key"]: a})
            if found:
                return found
        return None

    try:
        return walk({k: v for k, v in fixed.items() if k == "method"})
    except RuntimeError:
        return "unknown"


def main():
    cat = Catalog(load_records())
    out = {}
    for key in sys.argv[1:] or GUIDES:
        doc = yaml.safe_load((CATALOG / f"openforge/db/fixtures/guides/{key}.yaml").read_text())
        offered = open_choices(cat, doc)
        tex = next(r for r in doc["refinements"] if r["key"] == "texture")
        methods = next((s for s in doc["steps"] if s["key"] == "method"), None)
        method_keys = [o["key"] for o in methods["options"]] if methods else [None]
        has_floor_tex = any(r["key"] == "floor-texture" for r in doc["refinements"])

        # A texture belongs to this guide if it has any piece for a role
        # that is not a base. The rest are absent, which is fine, and their
        # dead branches are noise.
        tex_roles = [n for n, r in doc["roles"].items() if E._reaches(tex, n) and not r.get("match")]
        relevant = sorted(
            t for t in ([c["tag"] for c in tex["choices"]] if tex.get("choices") else offered["texture"])
            if any(not hopeless(cat, E._union([doc["roles"][n]["query"],
                                                E._refinement_predicate(tex, t, n)]))
                   for n in tex_roles)
        )
        textures = []
        for t in relevant:
            row = {"texture": t, "offered": t in offered.get("texture", []), "methods": {}}
            for m in method_keys:
                fixed = {"texture": t, **({"method": m} if m else {})}
                any_floor = complete(cat, doc, fixed)
                same = complete(cat, doc, {**fixed, "floor-texture": t}) if has_floor_tex else any_floor
                row["methods"][m or "-"] = {
                    "complete": any_floor if any_floor in (None, "unknown") else True,
                    "same_texture_floor": same if same in (None, "unknown") else True,
                }
            textures.append(row)

        roles = {}
        for name in doc["roles"]:
            dead, states, alive = sweep_role(cat, doc, name)
            role = doc["roles"][name]
            above = role.get("under") if role.get("match") else None

            @functools.lru_cache(maxsize=None)
            def dead_frozen(items, name=name, above=above):
                return dead_at_(dict(items), name, above)

            def dead_at(sel):
                return dead_frozen(tuple(sorted(sel.items())))

            def dead_at_(sel, name, above):
                st = State(doc, sel)
                if name not in st.in_play:
                    return False
                if hopeless(cat, st.pred(name)):
                    return True
                wanted = lambda r: E._reaches(r, name) or (above and E._reaches(r, above))  # noqa: E731
                if st.next_question(wanted) is not None:
                    return False  # not a leaf: some completion may live
                if above in st.in_play and cat.recommend(st.pred(above), doc["roles"][above]) is None:
                    return None
                return bool(role_dead(cat, doc, sel, name))

            mins = {}
            for d in dead:
                if any(covers(json.loads(m), d) for m in mins):
                    continue
                why = "empty" if hopeless(cat, State(doc, d).pred(name)) else role_dead(cat, doc, d, name)
                mins.setdefault(json.dumps(minimal(cat, doc, d, name, dead_at), sort_keys=True), why)
            roles[name] = {
                "states": states,
                "filled_in": sorted(t for t in alive if t),
                "dead_leaves": len(dead),
                "branches": [{"answers": json.loads(m), "why": why} for m, why in sorted(mins.items())],
            }
            print(f"{key}:{name} states={states} dead={len(dead)} minimal={len(mins)}", file=sys.stderr)
        out[key] = {"offered": offered, "relevant": relevant, "textures": textures, "roles": roles}
    json.dump(out, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
