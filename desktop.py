"""Finance OS — Native desktop window (no browser chrome).

Opens as a real app window using pywebview. No URL bar, no browser tabs.
Falls back to browser if pywebview is not available.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from main import app
from database import init_db


PORT = 3001


def start_server():
    """Run FastAPI in a background thread."""
    init_db()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def main():
    # Start server in background
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/")
            break
        except Exception:
            time.sleep(0.2)

    try:
        import webview
        window = webview.create_window(
            "Finance OS",
            f"http://127.0.0.1:{PORT}",
            width=1280,
            height=820,
            min_size=(900, 600),
            background_color="#111113",
            text_select=True,
        )
        webview.start()
    except ImportError:
        print("pywebview not installed — opening in browser instead")
        print(f"Install with: pip install pywebview")
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        server_thread.join()


if __name__ == "__main__":
    main()
