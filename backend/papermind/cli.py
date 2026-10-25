from __future__ import annotations

import argparse
import threading
import time
import webbrowser

import uvicorn

from papermind.config import DEFAULT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(prog="papermind")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="start the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--open", action="store_true", help="open the browser")
    args = parser.parse_args()

    if args.cmd == "serve":
        if args.open:
            url = f"http://{args.host}:{args.port}"
            threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
        uvicorn.run(
            "papermind.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            log_level="info",
        )


if __name__ == "__main__":
    main()
