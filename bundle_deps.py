#!/usr/bin/env python3
"""
Bundle Flask into your project folder for offline sharing.
Run this ONCE with internet, then share the entire folder.
"""

import subprocess
import sys
import os
import shutil

def main():
    deps_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deps')

    print("=" * 55)
    print("     📦  OFFLINE BUNDLER FOR LAN CHAT  📦")
    print("=" * 55)
    print()

    # Clean old deps
    if os.path.exists(deps_dir):
        print("🧹 Cleaning old deps folder...")
        shutil.rmtree(deps_dir)

    os.makedirs(deps_dir, exist_ok=True)

    print("⬇️  Downloading Flask and dependencies...")
    print("   (This requires internet - do it ONCE)")
    print()

    try:
        subprocess.check_call([
            sys.executable, '-m', 'pip', 'install',
            'flask', '-t', deps_dir, '--no-cache-dir'
        ])
        print()
        print("=" * 55)
        print("  ✅ DONE! Flask is now bundled in ./deps/")
        print("=" * 55)
        print()
        print("  📁 Your folder now looks like:")
        print("     chat_folder/")
        print("     ├── lan_chat_offline.py")
        print("     ├── bundle_deps.py")
        print("     ├── README.txt")
        print("     └── deps/          ← Flask lives here")
        print("         ├── flask/")
        print("         ├── werkzeug/")
        print("         └── ...")
        print()
        print("  🔌 Share this ENTIRE folder via USB cable,")
        print("     Bluetooth, or local network transfer.")
        print("  👥 Receiver just runs: python lan_chat_offline.py")
        print("     (No internet needed!)")
        print()

    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        print("Make sure you have internet and pip is installed.")
        sys.exit(1)

if __name__ == "__main__":
    main()