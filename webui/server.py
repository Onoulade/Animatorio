#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_DIR))

from webui.backend import AppConfig, EditorApplication  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Animatorio motion editor.")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: loopback only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--open", type=Path, default=None, help="asset JSON to open on startup")
    args = parser.parse_args()

    application = EditorApplication(AppConfig.from_environment())
    if args.open is not None:
        application.open_on_startup(args.open.expanduser().resolve())

    server = ThreadingHTTPServer((args.host, args.port), application.make_handler())
    display_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{display_host}:{args.port}/"
    print(f"Animatorio editor running at {url}")
    print("Ctrl+C to stop. Assets remain on disk; unsaved browser edits do not.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
