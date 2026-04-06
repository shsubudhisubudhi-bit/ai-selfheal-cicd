"""
AI Self-Healing CI/CD Demo Application
A simple Flask API with intentional failure modes for demonstrating
AI-powered self-healing in CI/CD pipelines.
"""

import os
import logging
import json
from datetime import datetime
from flask import Flask, jsonify, request

app = Flask(__name__)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("selfheal-app")

# --- Feature flag for intentional failure ---
FAIL_MODE = os.environ.get("FAIL_MODE", "false").lower() == "true"


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint - used by CI/CD pipeline to verify deployment."""
    if FAIL_MODE:
        logger.error("HEALTH CHECK FAILED - Application in failure mode")
        return jsonify({
            "status": "unhealthy",
            "error": "Application is in failure mode",
            "timestamp": datetime.utcnow().isoformat(),
        }), 500

    return jsonify({
        "status": "healthy",
        "version": os.environ.get("APP_VERSION", "1.0.0"),
        "timestamp": datetime.utcnow().isoformat(),
        "uptime": "ok",
    })


@app.route("/", methods=["GET"])
def index():
    """Root endpoint."""
    return jsonify({
        "app": "AI Self-Healing CI/CD Demo",
        "version": os.environ.get("APP_VERSION", "1.0.0"),
        "endpoints": ["/health", "/api/data", "/api/process"],
    })


@app.route("/api/data", methods=["GET"])
def get_data():
    """Sample data endpoint."""
    if FAIL_MODE:
        logger.error("DATA ENDPOINT CRASHED - Division by zero triggered")
        # Intentional error for demo
        result = 1 / 0  # noqa

    return jsonify({
        "data": [
            {"id": 1, "name": "Sample Item A", "value": 42},
            {"id": 2, "name": "Sample Item B", "value": 87},
            {"id": 3, "name": "Sample Item C", "value": 15},
        ],
        "count": 3,
        "timestamp": datetime.utcnow().isoformat(),
    })


@app.route("/api/process", methods=["POST"])
def process():
    """Sample processing endpoint."""
    data = request.get_json(silent=True) or {}
    logger.info(f"Processing request: {json.dumps(data)}")

    if FAIL_MODE:
        logger.error("PROCESS ENDPOINT FAILED - Memory allocation error simulated")
        return jsonify({
            "error": "MemoryError: Unable to allocate resources",
            "timestamp": datetime.utcnow().isoformat(),
        }), 503

    return jsonify({
        "status": "processed",
        "input": data,
        "result": "ok",
        "timestamp": datetime.utcnow().isoformat(),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9090))
    logger.info(f"Starting app on port {port} | FAIL_MODE={FAIL_MODE}")
    logger.info(f"Added test log app on port {port} | FAIL_MODE={FAIL_MODE}")
    app.run(host="0.0.0.0", port=port, debug=False)
