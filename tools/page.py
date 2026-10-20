"""Render the sweep as one HTML page: per guide, which textures build and what is missing.

Run:  python3 tools/page.py sweep-*.json > coverage.html
"""

import collections
import json
import pathlib
import sys

import report

# Which issue covers a group (8lx children unless named). Unlisted groups show none.
TEX_ISSUE = {
    "corner": {"dungeon_stone": "wp6", "nova_trail": "g71", "cave": "11", "cavern": "12", "mortar_and_stone": "13", "necro": "14",
               "rough_stone": "15", "sewer": "16"},
    "wall": {"aztlan": "18", "mortar_and_stone": "19", "necro": "20", "nova_trail": "21",
             "rough_stone": "22", "stone_brick": "23"},
}


def issue(guide, key):
    role, piece, size = key
    tex = dict(piece).get("texture", "*").replace("texture|", "")
    if role == "floor-base":
        return "4" if guide == "corner" else "9"
    if role == "wall-base":
        return "8"
    if role == "floor":
        return "5" if (guide, tex) == ("corner", "*") else "10"
    if tex == "*":
        return {"corner": "17", "wall": "24"}.get(guide)
    return TEX_ISSUE.get(guide, {}).get(tex)


def issue_id(guide, key):
    n = issue(guide, key)
    return n and "openforge-" + ("8lx." + n if n.isdigit() else n)


def build(data):
    out = {}
    per_guide = collections.defaultdict(list)
    for key, ctxs in report.groups(data).items():
        for guide, ctx in ctxs:
            per_guide[(guide, key)].append(ctx)
    for guide, g in data.items():
        absent = report.absent_textures(g)
        offered = set(g["offered"].get("texture", []))
        rows = []
        for row in g["textures"]:
            if row["texture"] in absent and row["texture"] not in offered:
                continue
            cells = {}
            for m, v in row["methods"].items():
                if v["complete"] is not True:
                    cells[m] = "no"
                elif guide != "floor" and "floor" in g["roles"] and v["same_texture_floor"] is not True:
                    cells[m] = "other-floor"
                else:
                    cells[m] = "yes"
            rows.append({"texture": report.short(row["texture"]),
                         "offered": row["texture"] in offered, "cells": cells})
        groups = []
        for (gd, key), ctxs in sorted(per_guide.items(), key=lambda kv: (kv[0][1][0], report.describe(kv[0][1]))):
            if gd != guide:
                continue
            lines = sorted({tuple(sorted((k, report.short(v)) for k, v in c.items())) for c in ctxs})
            groups.append({"title": report.describe(key).split(": ", 1)[1], "role": key[0],
                           "issue": issue_id(guide, key), "lines": [dict(l) for l in lines]})
        out[guide] = {"methods": report.methods(g), "rows": rows, "groups": groups,
                      "absent": sorted(report.short(t) for t in absent)}
    return out


def main():
    data = {}
    for path in sys.argv[1:]:
        data.update(json.load(open(path)))
    page = (pathlib.Path(__file__).with_name("page.html")).read_text()
    print(page.replace("/*DATA*/null", json.dumps(build(data))))


if __name__ == "__main__":
    main()
