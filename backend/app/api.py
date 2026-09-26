from __future__ import annotations

from flask import Flask, jsonify, request

from .as_of_round import rank_as_of_payload
from .ranking import rank_payload


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/api/rankings")
    def rankings():
        payload = request.get_json(silent=True)
        try:
            return jsonify(rank_payload(payload))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/rankings/as-of-round")
    def rankings_as_of_round():
        payload = request.get_json(silent=True)
        try:
            return jsonify(rank_as_of_payload(payload))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return app


app = create_app()
