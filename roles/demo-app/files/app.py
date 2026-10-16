"""Small web application used as the monitored workload.

/        normal page
/fail    returns HTTP 500
/slow    answers after 1-3 seconds
/health  health check used by the rolling update
/metrics Prometheus metrics
Every request (except /health and /metrics) is logged as one JSON line.
"""
import json
import logging
import os
import random
import socket
import time

from flask import Flask, Response, g, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

VERSION = os.environ.get("APP_VERSION", "dev")
LOG_FILE = os.environ.get("APP_LOG_FILE", "app.log")
HOSTNAME = socket.gethostname()

REQUESTS = Counter("app_requests_total", "HTTP requests", ["endpoint", "status"])
LATENCY = Histogram("app_request_duration_seconds", "Request duration", ["endpoint"])

log = logging.getLogger("demo-app")
log.setLevel(logging.INFO)
handler = logging.FileHandler(LOG_FILE)
handler.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(handler)

app = Flask(__name__)

PAGE = """<!doctype html>
<html>
<head><title>Demo app</title></head>
<body style="font-family: sans-serif; margin: 3em">
  <h1>Demo app</h1>
  <p>Version <b>{version}</b>, served by <b>{host}</b></p>
  <ul>
    <li><a href="fail">fail</a> - returns an error</li>
    <li><a href="slow">slow</a> - slow response</li>
  </ul>
</body>
</html>
"""

UNTRACKED = {"/health", "/metrics"}


@app.before_request
def start_timer():
    g.start = time.monotonic()


@app.after_request
def track(response):
    if request.path in UNTRACKED:
        return response
    duration = time.monotonic() - g.start
    # the route pattern, not the raw path, keeps the number of label values small
    endpoint = request.url_rule.rule if request.url_rule else "unknown"
    REQUESTS.labels(endpoint, str(response.status_code)).inc()
    LATENCY.labels(endpoint).observe(duration)
    log.info(json.dumps({
        "level": "error" if response.status_code >= 500 else "info",
        "message": f"{request.method} {request.path} {response.status_code}",
        "method": request.method,
        "path": request.path,
        "status": response.status_code,
        "duration_ms": round(duration * 1000, 1),
        "client": request.headers.get("X-Real-IP", request.remote_addr),
        "app_version": VERSION,
    }))
    return response


@app.route("/")
def index():
    return PAGE.format(version=VERSION, host=HOSTNAME)


@app.route("/fail")
def fail():
    return "Something went wrong\n", 500


@app.route("/slow")
def slow():
    time.sleep(random.uniform(1, 3))
    return "Done, slowly\n"


@app.route("/health")
def health():
    return {"status": "ok", "version": VERSION, "host": HOSTNAME}


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
