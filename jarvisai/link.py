"""Localhost state feed for the Wallpaper Engine desktop."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("jarvisai.link")

LINK_PORT = 47321


class StateLink:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.port = LINK_PORT

    def start(self) -> None:
        handler = self._handler()
        try:
            server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        except OSError:
            log.exception("Desktop link could not start")
            return
        threading.Thread(target=server.serve_forever, name="jarvis-link", daemon=True).start()
        log.info("Desktop link ready on 127.0.0.1:%s", self.port)

    def _handler(self):
        provider = self.provider

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path != "/state":
                    self.send_error(404)
                    return
                body = json.dumps(provider()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args) -> None:
                return

        return Handler
