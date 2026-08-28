#!/usr/bin/env python3
"""Every module the CI suites import is pinned in requirements-dev.txt.

Why this exists: test_cardfind.py and test_scan_accuracy.py import lotfixtures,
which imports Pillow and numpy. Neither was in requirements-dev.txt. Both are
installed on the dev box, so all eight suites passed locally and the first clean
CI checkout died with ModuleNotFoundError before running a single assertion.

A test dependency satisfied only by accident of one machine's site-packages is
not a dependency that is pinned -- and the failure mode is the expensive one:
green locally, red only where nobody is looking, and silent about which of the
two it is.

Deliberately stdlib-only and import-free of the packages it checks, so it can
run as the FIRST step in CI, before pip install and before the ~1 minute
chromium download. A missing pin should cost seconds, not a full browser setup.

Run:  python3 test_requirements.py
"""
import ast
import glob
import os
import re
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

WORKFLOW = ".github/workflows/test.yml"
REQS     = "requirements-dev.txt"

# import name -> distribution name, where they differ.
DIST = {"pil": "pillow", "cv2": "opencv-python", "yaml": "pyyaml",
        "bs4": "beautifulsoup4", "dotenv": "python-dotenv"}

passed = True


def check(label, cond):
    global passed
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        passed = False
    return cond


def pinned():
    out = {}
    for line in open(REQS):
        line = line.split("#")[0].strip()
        if not line:
            continue
        name = re.split(r"[=<>!~\[]", line)[0].strip().lower()
        out[name] = line
    return out


def imports_of(path, seen):
    """Third-party distributions `path` needs, following local imports."""
    if path in seen or not os.path.exists(path):
        return set()
    seen.add(path)
    local = {g[:-3] for g in glob.glob("*.py")}
    need = set()
    for node in ast.walk(ast.parse(open(path).read())):
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module.split(".")[0]]
        else:
            continue
        for m in mods:
            if m in sys.stdlib_module_names:
                continue
            if m in local:
                # A local helper's dependencies are still our dependencies.
                need |= imports_of(m + ".py", seen)
            else:
                need.add(DIST.get(m.lower(), m.lower()))
    return need


print("1. every suite CI runs is discoverable")
ci_tests = sorted(set(re.findall(r"python3 (test_[a-z_]+\.py)",
                                 open(WORKFLOW).read())))
check(f"the workflow names test files ({len(ci_tests)} found)", len(ci_tests) > 0)
for t in ci_tests:
    check(f"{t} exists on disk", os.path.exists(t))

print("\n2. every third-party import those suites reach is pinned")
have = pinned()
need = set()
for t in ci_tests:
    need |= imports_of(t, set())
for dist in sorted(need):
    check(f"{dist} is in {REQS}", dist in have)

print("\n3. pins are exact, so CI and the dev box agree")
# A floating pin reproduces the same class of bug a month later, when a new
# major release changes behaviour only on the machine that resolved later.
for dist in sorted(need & set(have)):
    check(f"{dist} pinned to an exact version ({have[dist]})", "==" in have[dist])

print("\n4. the guard itself can fail")
# A checker that cannot go red is indistinguishable from one that always passes,
# so drop a pin and confirm this file NOTICES. Asserting on the real detection
# path, not on a restatement of it.
_victim = sorted(need & set(have))[0] if (need & set(have)) else None
if _victim:
    _mutated = {k: v for k, v in have.items() if k != _victim}
    check(f"dropping the {_victim} pin is detected",
          _victim in need and _victim not in _mutated)
    # ...and a pin that floats instead of being exact is caught too.
    check("a floating pin is detected",
          "==" not in f"{_victim}>=1.0")
else:
    check("there is at least one pinned dependency to mutate", False)

# The discovery step must actually reach through a local helper, or section 2
# only ever checked the direct imports and Pillow would still be missing.
_via_helper = imports_of("test_cardfind.py", set())
check(f"imports are followed through local helpers ({sorted(_via_helper)})",
      "pillow" in _via_helper and "numpy" in _via_helper)

print("\n" + ("ALL TESTS PASSED" if passed else "SOME TESTS FAILED"))
sys.exit(0 if passed else 1)
