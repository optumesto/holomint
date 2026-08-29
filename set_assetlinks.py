#!/usr/bin/env python3
"""Write SHA-256 signing fingerprints into .well-known/assetlinks.json.

WHY THIS EXISTS RATHER THAN "just edit the JSON"
assetlinks.json is what tells Android that holomint.app and the Play app are the
same publisher. Get it wrong and the app still installs and still runs -- it
just runs with a Chrome address bar pinned across the top, which is the single
most common TWA mistake and looks exactly like a cheap web wrapper. The failure
is cosmetic, silent, and only visible on a real device after install.

There are TWO fingerprints, and missing the second is the usual reason a TWA
that worked in testing shows the address bar in production:

  UPLOAD KEY   the keystore on your machine, used for local builds
  PLAY APP SIGNING KEY   Google re-signs the app with its own key on upload,
                         so the shipped binary carries a DIFFERENT fingerprint.
                         Found in Play Console > Test and release > Setup >
                         App signing.

Both must be listed. Order does not matter.

USAGE
  # from your keystore (the upload key)
  python3 set_assetlinks.py --from-keystore android-keystore.jks holomint

  # or paste either fingerprint directly, repeatable
  python3 set_assetlinks.py --sha256 AA:BB:...:FF --sha256 11:22:...:99

  # check what is currently live on the site
  python3 set_assetlinks.py --check
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, ".well-known", "assetlinks.json")
LIVE = "https://holomint.app/.well-known/assetlinks.json"
FP = re.compile(r"^(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$")


def normalise(fp):
    fp = fp.strip().upper().replace(" ", "")
    if not FP.match(fp):
        raise SystemExit(
            f"Not a SHA-256 fingerprint: {fp[:40]}...\n"
            "Expected 32 hex pairs separated by colons, e.g. AA:BB:CC:...")
    return fp


def from_keystore(path, alias):
    if not os.path.exists(path):
        raise SystemExit(f"No keystore at {path}. Create one first (see the email).")
    pw = os.environ.get("HOLOMINT_KEYSTORE_PASSWORD")
    cmd = ["keytool", "-list", "-v", "-keystore", path, "-alias", alias]
    if pw:
        cmd += ["-storepass", pw]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    except FileNotFoundError:
        raise SystemExit("keytool not found. Install a JDK (see the email).")
    m = re.search(r"SHA256:\s*((?:[0-9A-F]{2}:){31}[0-9A-F]{2})", out, re.I)
    if not m:
        raise SystemExit("Could not read a SHA-256 fingerprint from keytool output. "
                         "Wrong alias, or wrong keystore password.")
    return normalise(m.group(1))


def check():
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(LIVE, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=25)
        data = json.load(r)
    except Exception as e:
        print(f"  live assetlinks.json unreachable: {str(e)[:70]}")
        return 1
    fps = data[0]["target"]["sha256_cert_fingerprints"]
    pkg = data[0]["target"]["package_name"]
    print(f"  live package_name : {pkg}")
    bad = [f for f in fps if not FP.match(f.upper())]
    for f in fps:
        print(f"  fingerprint       : {f[:20]}...  {'PLACEHOLDER' if not FP.match(f.upper()) else 'ok'}")
    if bad:
        print("\n  Android will NOT verify this. The app will show a browser address bar.")
        return 1
    print("\n  Looks valid. Android verifies on install, so reinstall to re-check.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha256", action="append", default=[],
                    help="a fingerprint; repeat for the upload key and the Play key")
    ap.add_argument("--from-keystore", nargs=2, metavar=("KEYSTORE", "ALIAS"))
    ap.add_argument("--package", default=None, help="override the package id")
    ap.add_argument("--check", action="store_true", help="inspect the live file")
    a = ap.parse_args()

    if a.check:
        sys.exit(check())

    fps = [normalise(f) for f in a.sha256]
    if a.from_keystore:
        fps.append(from_keystore(*a.from_keystore))
    if not fps:
        raise SystemExit("Give --sha256 or --from-keystore. See --help.")

    doc = json.load(open(PATH))
    tgt = doc[0]["target"]
    if a.package:
        tgt["package_name"] = a.package
    # Keep any real fingerprint already there; drop only the placeholders.
    keep = [f for f in tgt["sha256_cert_fingerprints"] if FP.match(f.upper())]
    tgt["sha256_cert_fingerprints"] = sorted(set(keep + fps))
    open(PATH, "w").write(json.dumps(doc, indent=2) + "\n")
    print(f"  wrote {len(tgt['sha256_cert_fingerprints'])} fingerprint(s) to {PATH}")
    for f in tgt["sha256_cert_fingerprints"]:
        print(f"    {f}")
    print("\n  Commit and push, then confirm it is live:")
    print("    python3 set_assetlinks.py --check")


if __name__ == "__main__":
    main()
