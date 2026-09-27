from __future__ import annotations

import os
import threading
import webbrowser

import uvicorn

from app.main import app

PORT = int(os.environ.get("YT_NEWS_PORT", "8787"))
URL = f"http://127.0.0.1:{PORT}"


def open_browser() -> None:
    webbrowser.open(URL)


if __name__ == "__main__":
    if os.environ.get("YT_NEWS_NO_BROWSER") != "1":
        threading.Timer(1.0, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, reload=False)
