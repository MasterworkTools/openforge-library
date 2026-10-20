# openforge-library

Facts about the OpenForge model library (the STLs under Dropbox `objects/OpenForge/tiles`),
as opposed to any one repo: coverage gaps, missing variants, naming problems.
Tracked with beads (`bd list`, prefix `openforge`).

## Guide coverage

`coverage-report.md` says, for every build guide in openforge-catalog, which textures each
method can complete and the shortest answer combinations that cannot be built, grouped by
the piece that would fix them. Regenerate after a rescan:

    python3 tools/sweep.py floor corner > /tmp/cf.json
    python3 tools/sweep.py wall > /tmp/wall.json      # a few minutes
    python3 tools/report.py /tmp/cf.json /tmp/wall.json > coverage-report.md
    python3 tools/page.py /tmp/cf.json /tmp/wall.json > coverage.html   # then republish the artifact
    python3 tools/test_sweep.py

`sweep.py` drives openforge-catalog's own guide engine (`openforge.guides.resolve`) with
in-memory finders over the fixture files, so it needs no database. Known limits: ties on
`blueprint_name` break by load order here and by uuid in Postgres; pins are ignored; the
floor texture is treated as its own question, as the guides ask it.

Two traps for anyone changing the sweep: never prune on an empty partial predicate
(`require` is exempt from `deny_children`, so a later answer can widen the match), and widen
dead answers to `*` jointly, not one key at a time (per-key widening over-claims).
