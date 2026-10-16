# Role: demo-app

Installs the demo application: a small web application that the platform
monitors. It produces metrics, logs and, on request, errors and slow
responses, so every part of the platform has something real to show.

| | |
|-|-|
| Runs on | `app` hosts: play *Application tier* in `site.yml`, and `rolling_update.yml` |
| Reached at | `https://<proxy>/app/`, without login |

## Background

- **Flask** is a small Python web framework: one function per URL path.
- **gunicorn** runs the Flask application and listens on port 8000. Flask's
  own server is meant for development only; gunicorn is the usual production
  server. It runs with 1 worker and 4 threads, so four requests are handled at
  the same time and a slow request does not block the others.
- A **virtualenv** is a private set of Python packages for this application,
  installed at fixed versions and separate from the system's Python.
- A **systemd service** keeps the application running: it starts at boot, is
  restarted if it crashes, and runs as its own unprivileged user.

## The application (`files/app.py`)

| Path | Behaviour |
|------|-----------|
| `/` | page with the application version and the host that answered |
| `/fail` | returns HTTP 500 |
| `/slow` | answers after 1 to 3 seconds |
| `/health` | `{"status": "ok", "version": ..., "host": ...}`, used by the rolling update |
| `/metrics` | Prometheus metrics |

**Metrics** (library `prometheus_client`):

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `app_requests_total` | counter | `endpoint`, `status` | number of requests |
| `app_request_duration_seconds` | histogram | `endpoint` | response times in buckets, used for percentiles |

`endpoint` is the route pattern (`/fail`), not the raw path; unknown paths
are counted as `unknown`. Otherwise every random URL would create a new time
series in Prometheus.

**Logs:** every request writes one JSON line to `/var/log/demo-app/app.log`:

```json
{"level": "error", "message": "GET /fail 500", "method": "GET", "path": "/fail",
 "status": 500, "duration_ms": 0.4, "client": "192.168.56.1", "app_version": "1.0.0"}
```

Filebeat reads these lines as JSON, so every key becomes a searchable field in
Kibana. `/health` and `/metrics` are neither counted nor logged, since they are
requests from the platform itself.

## Files

| File | Type | Purpose |
|------|------|---------|
| `defaults/main.yml` | variables | version, port, threads, user, directories |
| `tasks/main.yml` | tasks | installs and starts the application |
| `handlers/main.yml` | handler | restarts the application |
| `templates/demo-app.service.j2` | template | the systemd service |
| `files/app.py` | code | the application |
| `files/requirements.txt` | package list | `flask`, `gunicorn`, `prometheus-client` at fixed versions |
| `meta/main.yml` | metadata | description, platform, no dependencies |

## Tasks (`tasks/main.yml`)

| # | Task | What it does |
|---|------|--------------|
| 1 | Install python venv | `python3-venv`, needed to create the virtualenv |
| 2 | Create application user | system user `demo-app` without login shell |
| 3 | Create application directory | `/opt/demo-app`, owned by root: the application cannot modify its own code |
| 4 | Create log directory | `/var/log/demo-app`, owned by `demo-app`: the only place it writes |
| 5 | Copy requirements | `requirements.txt` → `/opt/demo-app/` |
| 6 | Install python packages into a virtualenv | creates `/opt/demo-app/venv` and installs the pinned packages |
| 7 | Copy application | `app.py` → `/opt/demo-app/` |
| 8 | Install systemd service | renders `demo-app.service.j2` to `/etc/systemd/system/demo-app.service` |
| 9 | Enable and start the application | starts the service and enables it at boot |

Tasks 5 to 8 notify `Restart demo-app`: new packages, new code or a new
service file (which contains the version) restart the application.

## Handlers (`handlers/main.yml`)

| Handler | Action |
|---------|--------|
| `Restart demo-app` | `daemon_reload` (new service file) and restart |

In `rolling_update.yml` this handler restarts the application with the new
version before the health check.

## Templates

### demo-app.service.j2

```ini
[Unit]
Description=Demo application {{ app_version }}
After=network-online.target

[Service]
User={{ app_user }}
Group={{ app_user }}
WorkingDirectory={{ app_dir }}
Environment=APP_VERSION={{ app_version }}
Environment=APP_LOG_FILE={{ app_log_dir }}/app.log
ExecStart={{ app_dir }}/venv/bin/gunicorn --bind 0.0.0.0:{{ app_port }} --workers 1 --threads {{ app_threads }} app:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

| Line | Meaning |
|------|---------|
| `User`, `Group` | runs as `demo-app`, not root |
| `Environment=APP_VERSION` | the version shown on the page and in `/health`; a new version changes this file, which triggers the restart |
| `Environment=APP_LOG_FILE` | where the application writes its JSON log |
| `ExecStart` | gunicorn from the virtualenv, `app:app` = module `app.py`, Flask object `app` |
| `Restart=on-failure` | restarted by systemd after a crash |

## Variables (`defaults/main.yml`)

| Variable | Default | Description |
|----------|---------|-------------|
| `app_version` | `1.0.0` | version; set per environment in `inventory/<env>/group_vars/app.yml`, or with `-e app_version=...` |
| `app_port` | `8000` | listen port (also used by the nginx upstream and the Prometheus target) |
| `app_threads` | `4` | gunicorn threads |
| `app_user` | `demo-app` | system user |
| `app_dir` | `/opt/demo-app` | code and virtualenv |
| `app_log_dir` | `/var/log/demo-app` | log directory |

## How the platform sees the application

| Part | What it does with the application |
|------|-----------------------------------|
| nginx | publishes it at `/app/` without login, balances between app hosts |
| Prometheus | scrapes `:8000/metrics` (job `app`, label `team: app`) |
| Recording rules | `app:requests:rate1m`, `app:errors:rate1m` |
| Alert rule | `AppHighErrorRate`: more than 5 % failed requests for 1 minute |
| Alertmanager | routes app alerts to the `app` receiver |
| Grafana | dashboard *Application → Demo application* |
| Filebeat | ships `app.log` as JSON with `log_type: app`, `team: app` |
| Kibana | data view *application logs* (`monitoring-app-*`) |
| `rolling_update.yml` | replaces the version one host at a time |

## Verifying

```bash
ansible app -m shell -a "systemctl is-active demo-app"
ansible app -m shell -a "curl -s localhost:8000/health"
ansible app -m shell -a "curl -s localhost:8000/metrics | grep '^app_requests_total'"
ansible app -m shell -a "tail -n 3 /var/log/demo-app/app.log"
```

## Presentation notes

- The application exists to give the monitoring something real: traffic,
  errors on demand (`/fail`), latency on demand (`/slow`).
- Production-like setup: gunicorn, virtualenv with pinned packages, systemd,
  unprivileged user.
- The version lives in the service file, so a version change restarts the
  application through the handler; that is what the rolling update relies on.
