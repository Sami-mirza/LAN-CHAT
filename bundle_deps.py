#!/usr/bin/env python3
"""Bundle Flask into ./deps for fully-offline use of LAN Chat.

Run this once *with* internet, then distribute the whole folder (USB stick,
Bluetooth, LAN share). Everyone on the network can then run `python main.py`
with zero internet connection.

    $ python bundle_deps.py
"""

import os
import shutil
import subprocess
import sys

FLASK_VERSION = "3.1.3"


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    deps_dir = os.path.join(here, "deps")

    print("=" * 56)
    print("  🧳  LAN CHAT — OFFLINE DEPENDENCY BUNDLER")
    print("=" * 56)

    if os.path.exists(deps_dir):
        print(f"  🧹  Clearing existing {deps_dir}")
        shutil.rmtree(deps_dir)
    os.makedirs(deps_dir, exist_ok=True)

    print(f"  ⬇️   Downloading Flask {FLASK_VERSION} + dependencies (requires internet)…")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            f"flask=={FLASK_VERSION}", "--target", deps_dir, "--no-cache-dir",
        ])
    except subprocess.CalledProcessError as exc:
        sys.exit(f"  ❌  Bundling failed: {exc}\n     Make sure pip is installed and online.")

    print("  ✅  Done. Flask is vendored in ./deps/")
    print("  👉  Anyone can now run:  python main.py   (no internet needed)")
    print("=" * 56)


if __name__ == "__main__":
    main()