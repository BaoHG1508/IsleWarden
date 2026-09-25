"""Runs the server: python -m islewarden_server [--config appsettings.json] [--host 127.0.0.1] [--port 5088]"""

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from .app import create_app
from .settings import SettingsError, load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m islewarden_server", description="IsleWarden server")
    parser.add_argument("--config", help="settings file (default: appsettings.json in the current directory)")
    parser.add_argument("--dev", action="store_true",
                        help="also load appsettings.Development.json next to it (local testing only)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to listen on (default 127.0.0.1; put a reverse proxy with HTTPS in front)")
    parser.add_argument("--port", type=int, default=5088)
    parser.add_argument("--access-log", action="store_true", help="log every HTTP request")
    args = parser.parse_args(argv)

    # Log files stay UTF-8 (the messages are Vietnamese) even when Windows redirects output in a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    if args.config and not Path(args.config).is_file():
        print(f"Không tìm thấy file cấu hình {args.config}", file=sys.stderr)
        return 2
    try:
        settings = load_settings(args.config or "appsettings.json", dev=args.dev)
    except SettingsError as ex:
        print(ex, file=sys.stderr)
        return 2

    app = create_app(settings)
    # log_config=None keeps uvicorn on the logging set up above.
    uvicorn.run(app, host=args.host, port=args.port, access_log=args.access_log, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
