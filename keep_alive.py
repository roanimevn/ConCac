"""Web server nhỏ (Flask) để chạy được trên Render *Web Service*.

Render Web Service bắt buộc có 1 cổng HTTP mở (biến PORT), nếu không deploy sẽ báo lỗi
"No open ports detected". Module này mở cổng đó trong một thread riêng, song song với bot.

  GET /        -> "ok" (cho người/UptimeRobot kiểm tra)
  GET /health  -> JSON tình trạng bot (luôn trả HTTP 200 để không bị Render restart nhầm)
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from flask import Flask, jsonify
from werkzeug.serving import make_server

log = logging.getLogger("sportsbot.keepalive")


def create_app(health: Callable[[], dict]) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "✅ Discord sports bot đang chạy", 200

    @app.get("/health")
    def health_route():
        return jsonify(health()), 200

    return app


def start(health: Callable[[], dict], port: int) -> threading.Thread:
    """Chạy Flask ở thread nền (daemon) – chết cùng tiến trình bot."""
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # đỡ spam log mỗi lần ping
    app = create_app(health)

    def run() -> None:
        # make_server (Werkzeug) thay cho app.run(): không đụng tới CLI/.env của Flask, không in banner.
        server = make_server("0.0.0.0", port, app, threaded=True)
        server.serve_forever()

    thread = threading.Thread(target=run, name="keep-alive", daemon=True)
    thread.start()
    log.info("Keep-alive server chạy tại cổng %d", port)
    return thread
