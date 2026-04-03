"""Build script for Finance OS — creates distributable packages.

Usage:
    python build.py             # Build for current platform
    python build.py --clean     # Clean build artifacts first
"""
import subprocess
import sys
import shutil
from pathlib import Path

APP_DIR = Path(__file__).parent
DIST_DIR = APP_DIR / "dist"
BUILD_DIR = APP_DIR / "build"


def clean():
    """Remove previous build artifacts."""
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  Cleaned {d}")


def build():
    """Build the app using PyInstaller."""
    print("\n  Finance OS — Build")
    print("  ==================\n")

    if "--clean" in sys.argv:
        clean()

    print("  Building with PyInstaller...")
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "financeos.spec",
            "--noconfirm",
        ],
        cwd=str(APP_DIR),
    )

    if result.returncode != 0:
        print("\n  Build FAILED. Check errors above.")
        sys.exit(1)

    # Check what was produced
    if sys.platform == "darwin":
        app_bundle = DIST_DIR / "Finance OS.app"
        if app_bundle.exists():
            size_mb = sum(f.stat().st_size for f in app_bundle.rglob("*") if f.is_file()) / 1024 / 1024
            print(f"\n  macOS app built: {app_bundle}")
            print(f"  Size: {size_mb:.0f} MB")
            print(f"\n  To run: open '{app_bundle}'")
            print(f"  To share: zip it and send the .zip file")
        else:
            folder = DIST_DIR / "FinanceOS"
            if folder.exists():
                print(f"\n  Built to: {folder}/")
                print(f"  Run with: {folder}/FinanceOS")
    else:
        exe = DIST_DIR / "FinanceOS" / "FinanceOS.exe"
        if exe.exists():
            print(f"\n  Windows exe built: {exe}")
            print(f"  To share: zip the FinanceOS/ folder")

    print()


if __name__ == "__main__":
    build()
