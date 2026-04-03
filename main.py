"""Finance OS — Local-first personal finance intelligence.

Usage:
    python main.py              # Start on port 3001
    python main.py --port 8080  # Custom port
"""
import sys
import argparse
import webbrowser
from pathlib import Path

# Load .env from app dir or parent dirs
try:
    from dotenv import load_dotenv
    load_dotenv()
    # Also check parent dir (personal-os/.env)
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Ensure app directory is on path for imports
sys.path.insert(0, str(Path(__file__).parent))

from database import init_db, STATIC_DIR
from contextlib import asynccontextmanager
from routers import dashboard, import_data, settings, ai, watchlist, xray, feed, finances, tax, rules


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="Finance OS", docs_url=None, redoc_url=None, lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routers
app.include_router(dashboard.router)
app.include_router(import_data.router)
app.include_router(settings.router)
app.include_router(ai.router)
app.include_router(watchlist.router)
app.include_router(xray.router)
app.include_router(feed.router)
app.include_router(finances.router)
app.include_router(tax.router)
app.include_router(rules.router)


def main():
    parser = argparse.ArgumentParser(description="Finance OS — Local-first finance app")
    parser.add_argument("--port", type=int, default=3001, help="Port to run on (default: 3001)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    parser.add_argument("--browser", action="store_true", help="Open in browser instead of native window")
    args = parser.parse_args()

    print(f"\n  Finance OS")
    print(f"  Local-first personal finance intelligence")
    print(f"  http://{args.host}:{args.port}")
    print(f"  Data: ~/.financeos/finance.db")
    print(f"  Press Ctrl+C to stop\n")

    # Default: native window. --browser flag falls back to browser.
    if not args.no_browser and not args.browser:
        try:
            import webview
            import threading

            # Set dock icon on macOS before creating window
            icon_path = str(STATIC_DIR / "icon_1024.png")
            if sys.platform == "darwin":
                try:
                    from AppKit import NSApplication, NSImage
                    ns_app = NSApplication.sharedApplication()
                    icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
                    if icon:
                        ns_app.setApplicationIconImage_(icon)
                except Exception:
                    pass

            def run_server():
                uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

            server = threading.Thread(target=run_server, daemon=True)
            server.start()

            # Wait for server
            import urllib.request
            for _ in range(30):
                try:
                    urllib.request.urlopen(f"http://{args.host}:{args.port}/")
                    break
                except Exception:
                    import time; time.sleep(0.2)

            window = webview.create_window(
                "Finance OS",
                f"http://{args.host}:{args.port}",
                width=1280, height=820,
                min_size=(900, 600),
                background_color="#111113",
                text_select=True,
            )
            webview.start()
            return
        except ImportError:
            pass  # pywebview not available, fall through to browser/server mode

    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
