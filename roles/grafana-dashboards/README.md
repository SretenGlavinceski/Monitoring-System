# Role: grafana-dashboards

Installs Grafana and configures its authentication, its data source and its
dashboards, so a new machine comes up with everything ready and nothing has
to be set up in the user interface.

| | |
|-|-|
| Runs on | `metrics` hosts, play *Metrics tier* in `site.yml`, after `prometheus-config` |
| Installs with | Galaxy role `grafana.grafana.grafana` |
| Provides | authentication settings, Prometheus data source, dashboards in two folders |
| Assignment item | *grafana-dashboards: data source provisioning, JSON dashboard import, auth configuration* |

## Background

**Grafana** draws dashboards. Each panel runs a query against a **data
source**, here Prometheus, and shows the result. Grafana stores no metrics
itself.

**Provisioning** means Grafana reads YAML files from
`/etc/grafana/provisioning/` at start-up and creates data sources and
dashboards from them. Provisioned items are the same on every machine, are
recreated on every deployment, and are locked against changes in the UI.

Grafana keeps its users and login sessions in a small SQLite database on the
machine. That is why nginx sends each user to the same Grafana (`ip_hash` in
`templates/upstreams.conf.j2`).

## Files

| File | Type | Purpose |
|------|------|---------|
| `defaults/main.yml` | variables | version, port, admin user, URLs, dashboard folders |
| `tasks/main.yml` | tasks | prepares `grafana.ini`, installs Grafana, provisions data source and dashboards, keeps the admin password in sync with the vault |
| `handlers/main.yml` | handler | restarts Grafana after a provisioning change |
| `templates/datasource.yml.j2` | template | the Prometheus data source |
| `templates/dashboards.yml.j2` | template | dashboard providers, one per folder |
| `files/dashboards/infra/hosts.json` | dashboard | *Hosts*, folder *Infrastructure* |
| `files/dashboards/app/demo-app.json` | dashboard | *Demo application*, folder *Application* |
| `meta/main.yml` | metadata | description, platform, no dependencies |

## Tasks (`tasks/main.yml`)

| # | Task | What it does |
|---|------|--------------|
| 1 | Set grafana.ini values for the Galaxy role | sets the fact `grafana_ini` with the settings below, and `grafana_import_dir` (see task 3). `no_log: true`, the values contain the admin password. |
| 2 | Install python3-debian (the Galaxy role needs it to add the apt repository) | the Galaxy role adds Grafana's apt repository with the `deb822_repository` module, which needs this Python package on the host |
| 3 | Install Grafana | runs the Galaxy role with `grafana_version` (from `grafana_release`). It adds the repository, installs the package, merges our `grafana_ini` with its defaults, writes `/etc/grafana/grafana.ini`, and starts the service. `grafana_dashboards_dir` points to this role's `templates/` folder, which contains no `.json` files, so the Galaxy role's own dashboard import does nothing; this role provisions the dashboards itself (tasks 4 to 7). |
| 4 | Provision the Prometheus data source | renders `datasource.yml.j2` to `/etc/grafana/provisioning/datasources/prometheus.yml`; a change notifies `Restart grafana-server` |
| 5 | Provision the dashboard folders | renders `dashboards.yml.j2` to `/etc/grafana/provisioning/dashboards/monitoring.yml`; a change notifies `Restart grafana-server` |
| 6 | Create dashboard directories | `/var/lib/grafana/provisioned/infra` and `.../app`, owned by `grafana` |
| 7 | Copy dashboards | copies the JSON files from `files/dashboards/<folder>/` into those directories |
| 8 | Apply provisioning changes | `meta: flush_handlers`, runs a pending Grafana restart now, so the next tasks talk to the updated Grafana |
| 9 | Wait for the Grafana API | requests `/grafana/api/health` every 5 s until Grafana answers |
| 10 | Check the admin password from the vault | logs in to `/grafana/api/user` with the admin user and the vault password; 200 = correct, 401 = wrong. `no_log: true`. |
| 11 | Reset the admin password to the vault value | only when task 10 got 401: runs `grafana cli admin reset-admin-password` as the `grafana` user. `no_log: true`. |

**Why `set_fact` in task 1.** The Galaxy role merges its defaults with
`grafana_ini` in a `set_fact` of its own. Values passed directly to
`include_role` have a higher priority than `set_fact`, so they would replace
the merged result and Grafana would lose the role's defaults (paths, database,
listen address). A `set_fact` has the same priority, so the merge works.

**Why tasks 10 and 11.** Grafana uses `admin_password` from `grafana.ini` only
once, when it creates its database. A password changed in the vault later
would be written to the file but ignored. Testing the password with a real
login, and resetting it only when the login fails, applies vault changes and
keeps the task idempotent (no change when the password is already correct).

### grafana.ini settings (task 1)

| Section | Setting | Value | Purpose |
|---------|---------|-------|---------|
| `server` | `http_port` | `3000` | listen port |
| `server` | `domain`, `root_url` | `https://<monitoring_host>/grafana/` | Grafana's public address behind the proxy, used for its links |
| `server` | `serve_from_sub_path` | `true` | Grafana answers under `/grafana/` |
| `security` | `admin_user`, `admin_password` | `admin`, vault value | admin login |
| `users` | `allow_sign_up` | `false` | no self-registration |
| `auth.anonymous` | `enabled` | `false` | nothing visible without a login |

These are the **auth configuration** of the assignment item.

## Handlers (`handlers/main.yml`)

| Handler | Action | Notified by |
|---------|--------|-------------|
| `Restart grafana-server` | restarts Grafana so it reads the provisioning files again | tasks 4 and 5 |

Changes of `grafana.ini` are handled by the Galaxy role's own handler.

## Templates

### datasource.yml.j2

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: {{ grafana_datasource_url }}      # http://127.0.0.1:9090/prometheus
    isDefault: true
    editable: false
```

| Field | Meaning |
|-------|---------|
| `url` | the Prometheus on the same machine; `/prometheus` because Prometheus runs under that path. In production each Grafana uses its own Prometheus, so one failed metrics host does not affect the other. |
| `access: proxy` | the Grafana server sends the queries, not the browser |
| `isDefault` | panels without an explicit data source use this one |
| `editable: false` | cannot be changed in the UI |

### dashboards.yml.j2

```jinja
providers:
{% for folder in grafana_dashboard_folders %}
  - name: {{ folder.dir }}
    folder: {{ folder.title }}
    type: file
    disableDeletion: true
    updateIntervalSeconds: 30
    options:
      path: {{ grafana_provisioned_dashboards_dir }}/{{ folder.dir }}
{% endfor %}
```

One **provider** per entry of `grafana_dashboard_folders`: "load every JSON
file from this directory into this Grafana folder".

| Field | Meaning |
|-------|---------|
| `folder` | folder name shown in Grafana (*Infrastructure*, *Application*) |
| `disableDeletion` | provisioned dashboards cannot be deleted in the UI |
| `updateIntervalSeconds` | changed JSON files are picked up within 30 s without a restart |
| `options.path` | directory filled by task 7 |

## Dashboards (`files/dashboards/`)

These JSON files are the **JSON dashboard import** of the assignment item.

**infra/hosts.json, *Hosts*:**

| Panel | Query |
|-------|-------|
| Hosts up | `count(up{job="node"} == 1)` |
| Hosts down | `count(up{job="node"} == 0) or vector(0)` |
| Targets down (all jobs) | `count(up == 0) or vector(0)` |
| Firing alerts | `count(ALERTS{alertstate="firing"}) or vector(0)` |
| CPU usage | `instance:node_cpu_utilisation:rate5m` |
| Memory usage | `instance:node_memory_utilisation:ratio * 100` |
| Disk usage / | `instance:node_filesystem_utilisation:ratio{mountpoint="/"} * 100` |
| Network traffic | received and sent bytes per second per host |

**app/demo-app.json, *Demo application*:**

| Panel | Query |
|-------|-------|
| Instances up | `count(up{job="app"} == 1)` |
| Requests / s | `sum(app:requests:rate1m)` |
| Error rate % | `sum(app:errors:rate1m) / sum(app:requests:rate1m) * 100` |
| p95 latency (s) | `histogram_quantile(0.95, ...app_request_duration_seconds_bucket...)` |
| Requests per second | `app:requests:rate1m`, per host |
| Error rate % | per host |
| Requests by status | `sum by (status) (rate(app_requests_total[1m]))` |
| Latency p50 / p95 | per host |

`or vector(0)` shows 0 instead of "no data" when nothing matches. The
`app:` and `instance:` series are recording rules of `prometheus-config`.
A new dashboard is added by exporting it from Grafana as JSON and saving it in
one of the folders.

## Variables (`defaults/main.yml`)

| Variable | Default | Description |
|----------|---------|-------------|
| `grafana_release` | `12.4.10` | Grafana version |
| `grafana_http_port` | `3000` | listen port |
| `grafana_admin_user` | `admin` | admin user |
| `grafana_admin_password` | from the vault (`group_vars/all/vars.yml`) | admin password, required |
| `grafana_root_url` | `https://<monitoring_host>/grafana/` | address behind the proxy |
| `grafana_datasource_url` | `http://127.0.0.1:9090/prometheus` | Prometheus address |
| `grafana_provisioned_dashboards_dir` | `/var/lib/grafana/provisioned` | dashboard files on the host |
| `grafana_dashboard_folders` | `infra` → *Infrastructure*, `app` → *Application* | folder mapping |

## Verifying

```bash
ansible metrics -m shell -a "curl -s localhost:3000/grafana/api/health"
ansible metrics -m shell -a "ls -R /etc/grafana/provisioning /var/lib/grafana/provisioned"
```

In the browser: `/grafana/` → Dashboards (two folders), Connections → Data
sources (Prometheus, provisioned).

## Design decisions

- Data source and dashboards are provisioned from files; a rebuilt machine
  comes back identical after one run.
- Authentication: password from the vault, no sign-up, no anonymous access,
  and the proxy login in front.
- The password check makes the one-time `admin_password` setting follow the
  vault while keeping the role idempotent.
- The nginx location for Grafana removes the `Authorization` header;
  otherwise Grafana would try to log in with the proxy's credentials.
