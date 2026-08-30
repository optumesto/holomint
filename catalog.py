#!/usr/bin/env python3
"""Decode products.json, whichever shape it is in.

products.json is columnar on the wire (10.7 MB -> 2.2 MB raw, 805 KB -> 435 KB
gzipped) because it is fetched BEFORE the load event: those bytes are time a
booth visitor spends looking at a splash screen on mobile data.

Three things go, none of them data:
  * `img` -- all 60,168 rows were exactly product/{id}_200w.jpg, zero
    exceptions, so it was 60k copies of a 50-character prefix rebuildable from
    the id already on the row.
  * `set` (658 distinct), `type` (2) and `status` (3) interned to table indices.
  * columnar, so key names appear once each rather than 60,168 times.

WHY THIS FILE EXISTS RATHER THAN AN INLINE json.load
Three separate things read products.json: the app (JS), make_hashes.py, and
test_scan_accuracy.py. The last two iterate rows looking for `type == "single"`
and an `img` URL. Changing the format without them would have left the card-hash
builder -- which runs on a schedule and pushes to this repo -- iterating an
object and silently producing zero singles, then committing a hashes.json built
from nothing. One decoder, so the seam is pinned in one place.

The bare-array form is still accepted: a GitHub Action rewrites products.json
daily and a Service Worker can serve a cached copy for as long as a tab stays
open, so both shapes are live at once during a rollout.
"""
import json
import os

IMG_BASE = "https://tcgplayer-cdn.tcgplayer.com/product/"


def decode(data):
    """Columnar or bare-array -> list of row dicts, `img` rebuilt."""
    if isinstance(data, list):
        return data                       # previous format, already rows
    if not isinstance(data, dict) or not isinstance(data.get("id"), list):
        raise ValueError("products.json is neither a row array nor columnar")
    sets = data.get("sets") or []
    types = data.get("types") or []
    statuses = data.get("statuses") or []
    ids = data["id"]
    names = data["name"]
    si, ti, ui = data["set"], data["type"], data["status"]
    out = []
    for i, pid in enumerate(ids):
        out.append({
            "id": pid,
            "name": names[i],
            "set": sets[si[i]],
            "type": types[ti[i]],
            "status": statuses[ui[i]],
            "img": f"{IMG_BASE}{pid}_200w.jpg",
            **({"jp": True} if (data.get("jp") and data["jp"][i]) else {}),
        })
    return out


def load(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "products.json")
    with open(path) as f:
        return decode(json.load(f))
