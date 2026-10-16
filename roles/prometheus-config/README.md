# Role: prometheus-config

Installs Prometheus and configures what it collects and which alerts it
raises.

| | |
|-|-|
| Runs on | `metrics` hosts, play *Metrics tier* in `site.yml` |
| Installs with | Galaxy role `prometheus.prometheus.prometheus` |
| Provides | `prometheus.yml` with scrape targets from the inventory, recording rules, alert rules |
| Assignment item | *prometheus-config: prometheus.yml with dynamic targets, alert rules, recording rules* |

## Background

**Prometheus** is a time-series database. Every 15 seconds it reads
(*scrapes*) the `/metrics` page of every *target* and stores each value with
a timestamp. Each stored series is identified by its name and its **labels**,
for example `node_cpu_seconds_total{host="app1", team="infra", ...}`.
Prometheus also records for every target a series `up`: 1 if the last scrape
succeeded, 0 if not.

**Recording rules** compute a query regularly and store the result as a new
series with a short name. **Alert rules** are conditions; a condition that
holds for the configured time makes the alert *firing*, and Prometheus sends
it to Alertmanager.

## Files

| File | Type | Purpose |
|------|------|---------|
| `defaults/main.yml` | variables | every setting of the role with its default |
| `tasks/main.yml` | tasks | installs Prometheus with this role's configuration, installs the rule files |
| `handlers/main.yml` | handler | reloads Prometheus after a rule change |
| `templates/prometheus.yml.j2` | template | main configuration: scrape targets, rule files, Alertmanager addresses |
| `templates/recording.yml.j2` | template | recording rules |
| `templates/alerts.yml.j2` | template | alert rules |
| `meta/main.yml` | metadata | description, supported platform (Ubuntu 24.04), no dependencies |

## Tasks (`tasks/main.yml`)

| # | Task | What it does |
|---|------|--------------|
| 1 | Point the Galaxy role to this role's prometheus.yml template | stores the full path of `templates/prometheus.yml.j2` in a fact. The path must be resolved here: inside the Galaxy role, `role_path` would point to the Galaxy role. |
| 2 | Install Prometheus | runs the Galaxy role `prometheus.prometheus.prometheus` with these variables: `prometheus_version` (from `prometheus_release`), `prometheus_config_file` (our template), listen address, external URL, retention, and `prometheus_alert_rules: []`, which disables the example rules the Galaxy role ships. The Galaxy role creates the `prometheus` user and directories, downloads and verifies the binaries, renders **our** template to `/etc/prometheus/prometheus.yml` (checked with `promtool check config`), and installs and starts the systemd service. |
| 3 | Install alert and recording rules | renders `recording.yml.j2` and `alerts.yml.j2` to `/etc/prometheus/rules/`, owned by `prometheus`, mode 0640. `validate: promtool check rules %s` checks each file before it replaces the old one, so an invalid rule fails the run instead of breaking Prometheus. A change notifies `Reload prometheus rules`. |

The Galaxy role installs Prometheus; this role decides what Prometheus does.

## Handlers (`handlers/main.yml`)

| Handler | Action | Notified by |
|---------|--------|-------------|
| `Reload prometheus rules` | `systemctl reload prometheus`: Prometheus re-reads its configuration and rules without stopping | task 3 |

A reload is used instead of a restart because Prometheus keeps running and
does not miss scrapes. Changes of `prometheus.yml` itself are reloaded by the
Galaxy role's own handler.

## Templates

### prometheus.yml.j2

```yaml
global:
  scrape_interval: {{ prometheus_scrape_interval }}
  evaluation_interval: {{ prometheus_scrape_interval }}
  external_labels:
    env: {{ env_name }}
```

- Targets are scraped and rules evaluated every 15 s.
- `external_labels` adds `env: staging` or `env: production` to everything
  this Prometheus sends out (alerts), so a notification shows its environment.

```yaml
rule_files:
  - /etc/prometheus/rules/*.yml

alerting:
  alertmanagers:
    - path_prefix: /alertmanager/
      static_configs:
        - targets:
{% for h in groups['alert'] %}
            - {{ hostvars[h].ansible_host }}:{{ prometheus_alertmanager_port }}
{% endfor %}
```

- Every `.yml` file in the rules folder is loaded.
- Firing alerts go to **every** host in the `alert` group. `path_prefix` is
  needed because Alertmanager runs under `/alertmanager/` behind the proxy.

**Scrape targets.** A macro writes one target per host of a group, with the
labels `host` (inventory name) and `team`:

```jinja
{% macro targets(group, port, team) -%}
{% for h in groups[group] %}
      - targets: ["{{ hostvars[h].ansible_host }}:{{ port }}"]
        labels:
          host: {{ h }}
          team: {{ team }}
{% endfor %}
{%- endmacro %}
```

| Job | Targets (group) | Port | Path | `team` |
|-----|-----------------|------|------|--------|
| `prometheus` | itself | 9090 | `/prometheus/metrics` | infra |
| `alertmanager` | `alert` | 9093 | `/alertmanager/metrics` | infra |
| `node` | `monitoring` (every host) | 9100 | `/metrics` | infra |
| `nginx` | `proxy` | 9113 | `/metrics` | infra |
| `elasticsearch` | `logging` | 9114 | `/metrics` | infra |
| `app` | `app` | 8000 | `/metrics` | app |

These are the **dynamic targets**: nothing is written by hand. A host added to
the inventory is scraped after the next run.

Rendered for staging (excerpt):

```yaml
  - job_name: node
    static_configs:
      - targets: ["192.168.56.10:9100"]
        labels:
          host: stg-proxy
          team: infra
      - targets: ["192.168.56.11:9100"]
        labels:
          host: stg-metrics
          team: infra
      ...
```

### recording.yml.j2

| Recorded series | Query | Meaning |
|-----------------|-------|---------|
| `instance:node_cpu_utilisation:rate5m` | `100 * (1 - avg by (instance, host, team) (rate(node_cpu_seconds_total{mode="idle"}[5m])))` | CPU usage in %, 5-minute average, per host |
| `instance:node_memory_utilisation:ratio` | `1 - MemAvailable / MemTotal` | memory in use, 0 to 1 |
| `instance:node_filesystem_utilisation:ratio` | `1 - avail / size` for real file systems | disk in use per mount point, 0 to 1 |
| `app:requests:rate1m` | `sum by (host, team) (rate(app_requests_total[1m]))` | requests per second per app host |
| `app:errors:rate1m` | the same for `status=~"5.."` | failed requests per second |

The CPU query, step by step: node_exporter counts the seconds each core has
been idle; `rate(...[5m])` turns the counter into "share of time idle";
`avg by` averages the cores of a host; `1 -` gives the busy share; `100 *`
makes it a percentage. `team` is listed in `by (...)`, otherwise the
aggregation would drop the label that Alertmanager routes on.

Alert rules and the Grafana dashboards use these short names, so each
calculation is defined once.

### alerts.yml.j2

| Alert | Condition | For | Severity | Team |
|-------|-----------|-----|----------|------|
| `InstanceDown` | `up == 0` | 1 min | critical | from the target (infra or app) |
| `HighCpuUsage` | CPU > `alert_cpu_threshold` (80 %) | 5 min | warning | infra |
| `HighMemoryUsage` | memory > `alert_memory_threshold` (85 %) | 5 min | warning | infra |
| `LowDiskSpace` | disk > `alert_disk_threshold` (85 %) | 10 min | warning | infra |
| `AppHighErrorRate` | errors / requests × 100 > `alert_app_error_rate_threshold` (5 %) | 1 min | critical | app (set in the rule) |

- `for:` prevents alerts from short spikes: the condition must hold for that
  long, until then the alert is *pending*.
- The thresholds are variables, so they can be changed per environment
  without editing the template.
- The `summary` annotations contain Prometheus template syntax
  (`{{ $labels.host }}`). It is wrapped in `{% raw %}...{% endraw %}` so that
  Ansible's Jinja2 leaves it alone and Prometheus fills it in when the alert
  fires.

## Variables (`defaults/main.yml`)

| Variable | Default | Description |
|----------|---------|-------------|
| `prometheus_release` | `3.13.3` | Prometheus version |
| `prometheus_port` | `9090` | listen port |
| `prometheus_retention` | `15d` | how long data is kept (inventory: 7d staging, 30d production) |
| `prometheus_scrape_interval` | `15s` | scrape and evaluation interval |
| `prometheus_external_url` | `https://<monitoring_host>/prometheus/` | address behind the proxy |
| `prometheus_node_exporter_port` | `9100` | target port |
| `prometheus_nginx_exporter_port` | `9113` | target port |
| `prometheus_es_exporter_port` | `9114` | target port |
| `prometheus_alertmanager_port` | `9093` | target port |
| `prometheus_app_port` | `8000` | target port |
| `prometheus_infra_team` | `infra` | `team` label of infrastructure targets |
| `prometheus_app_team` | `app` | `team` label of application targets |
| `alert_cpu_threshold` | `80` | % |
| `alert_memory_threshold` | `85` | % |
| `alert_disk_threshold` | `85` | % |
| `alert_app_error_rate_threshold` | `5` | % of failed requests |

## Verifying

```bash
ansible metrics -m shell -a "promtool check config /etc/prometheus/prometheus.yml"
ansible metrics -m shell -a "curl -s localhost:9090/prometheus/api/v1/rules | python3 -m json.tool | grep '\"name\"'"
```

In the browser: `/prometheus/targets`, `/prometheus/rules`, `/prometheus/alerts`.

## Presentation notes

- Dynamic targets: show `prometheus.yml.j2`, then `/prometheus/targets`; one
  loop per group produces every target with its labels.
- Pull model: a target that stops answering is detected by the failed scrape
  (`up == 0`), which is what `InstanceDown` checks.
- Recording rules are used by both the alerts and the dashboards.
- Validation with `promtool` keeps broken configuration away from the running
  service; changes are applied with a reload, not a restart.
