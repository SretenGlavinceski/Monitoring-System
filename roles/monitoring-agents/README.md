# Role: monitoring-agents

Installs everything that runs on **every** host so the host is monitored:
node_exporter for metrics, Filebeat for logs, and extra exporters on the
hosts that need them.

| | |
|-|-|
| Runs on | all hosts (`monitoring` group), play *Monitoring agents on all hosts* in `site.yml`, with `serial: 20%` and `max_fail_percentage: 0` |
| Installs with | Galaxy role `prometheus.prometheus.node_exporter`; the `filebeat.yml` tasks of `elk-pipeline`; the exporters itself |
| Assignment item | *monitoring-agents: node_exporter + Filebeat on ALL hosts, conditional exporters per group* |

## Background

An **exporter** is a small program that reads the state of something and
publishes it as a `/metrics` page that Prometheus can scrape.

| Exporter | Hosts | Port | Reads |
|----------|-------|------|-------|
| node_exporter | all | 9100 | the machine: CPU, memory, disks, network |
| nginx_exporter | `proxy` | 9113 | nginx's status page (`/stub_status`): connections, requests |
| elasticsearch_exporter | `logging` | 9114 | Elasticsearch: cluster health, nodes, indices |

Prometheus cannot read nginx or Elasticsearch directly, so these two
exporters translate. Which hosts get them depends on the groups the host is
in: these are the **conditional exporters per group**.

## Files

| File | Type | Purpose |
|------|------|---------|
| `defaults/main.yml` | variables | ports, versions, the list of extra exporters |
| `tasks/main.yml` | tasks | node_exporter, the extra exporters, Filebeat |
| `tasks/exporter.yml` | tasks | installs one extra exporter; run once per exporter the host needs |
| `handlers/main.yml` | handlers | restart each extra exporter |
| `templates/exporter.service.j2` | template | systemd service of an extra exporter |
| `meta/main.yml` | metadata | description, platform, no dependencies |

## Tasks

### tasks/main.yml

| # | Task | What it does |
|---|------|--------------|
| 1 | Install node_exporter | runs the Galaxy role `prometheus.prometheus.node_exporter`, listening on `0.0.0.0:9100` |
| 2 | Install the exporters for the groups this host belongs to | runs `exporter.yml` once for each entry of `agent_exporters` whose `group` is one of the host's groups |
| 3 | Install Filebeat | runs `filebeat.yml` of the role `elk-pipeline`; the Filebeat configuration belongs to the log pipeline and is maintained there |

The filter of task 2:

```yaml
loop: "{{ agent_exporters | selectattr('group', 'in', group_names) | list }}"
```

`agent_exporters` is the list of all extra exporters; `selectattr` keeps those
whose `group` is in `group_names`, the groups of the current host. On a proxy
the list contains nginx_exporter, on a logging host elasticsearch_exporter, on
other hosts nothing. Adding an exporter for another group means adding one
entry to the list, without new tasks.

### tasks/exporter.yml

Runs for one exporter, available as the loop variable `exporter`.

| # | Task | What it does |
|---|------|--------------|
| 1 | Create user for `<exporter>` | system user without login shell; the exporter does not run as root |
| 2 | Create directory for `<exporter>` | `/opt/exporters/<exporter>` |
| 3 | Download and unpack `<exporter>` | downloads the release archive from GitHub and unpacks it. `creates:` skips the step when the binary already exists, which keeps it idempotent. |
| 4 | Install the binary of `<exporter>` | copies it to `/usr/local/bin/<exporter>`, mode 0755 |
| 5 | Install the systemd service of `<exporter>` | renders `exporter.service.j2` |
| 6 | Enable and start `<exporter>` | starts the service and enables it at boot; `daemon_reload` makes systemd read a new service file |

Tasks 4 and 5 notify `Restart <exporter>`.

## Handlers (`handlers/main.yml`)

| Handler | Notified by |
|---------|-------------|
| `Restart nginx_exporter` | new binary or service file on a proxy |
| `Restart elasticsearch_exporter` | new binary or service file on a logging host |

The handler name is built from the exporter name
(`notify: "Restart {{ exporter.name }}"`), so each exporter restarts only
itself. Filebeat's handler is in `elk-pipeline`, node_exporter's in the Galaxy
role.

## Templates

### exporter.service.j2

```ini
[Unit]
Description={{ exporter.name }}
After=network-online.target

[Service]
User={{ exporter.name }}
ExecStart=/usr/local/bin/{{ exporter.name }} {{ exporter.args }}
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

One template for every extra exporter; name and arguments come from the
`agent_exporters` entry. `Restart=on-failure` restarts the exporter if it
crashes.

## Variables (`defaults/main.yml`)

| Variable | Default | Description |
|----------|---------|-------------|
| `node_exporter_port` | `9100` | node_exporter port |
| `exporter_install_dir` | `/opt/exporters` | where archives are unpacked |
| `exporter_arch` | `amd64`, or `arm64` on ARM hosts | CPU architecture in the download URL, from the fact `ansible_architecture` |
| `nginx_exporter_version` | `1.5.2` | |
| `es_exporter_version` | `1.10.0` | |
| `agent_exporters` | two entries | the extra exporters |

Each entry of `agent_exporters`:

| Key | nginx_exporter | elasticsearch_exporter |
|-----|----------------|------------------------|
| `name` | `nginx_exporter` | `elasticsearch_exporter` |
| `group` | `proxy` | `logging` |
| `url` | GitHub release archive | GitHub release archive |
| `binary` | path of the program inside the archive | path of the program inside the archive |
| `args` | `--nginx.scrape-uri=http://127.0.0.1/stub_status --web.listen-address=:9113` | `--es.uri=http://127.0.0.1:9200 --web.listen-address=:9114` |

## Rollout behaviour

In `site.yml` this role runs with:

- `serial: "20%"`: hosts are processed in batches, each finished before the
  next starts (production: batches of 2, staging: 1).
- `max_fail_percentage: 0`: the rollout stops at the first failed host.

A broken agent version or configuration therefore stops after the first batch
instead of reaching every machine.

## Verifying

```bash
ansible all -m shell -a "systemctl is-active node_exporter filebeat"
ansible proxy -m shell -a "curl -s localhost:9113/metrics | grep '^nginx_up'"
ansible logging -m shell -a "curl -s localhost:9114/metrics | grep '^elasticsearch_cluster_health_status'"
```

In the browser: `/prometheus/targets`, jobs `node`, `nginx`, `elasticsearch`.

## Design decisions

- One role for every host; group membership decides which extra exporters
  a host gets.
- The exporter list is data (`agent_exporters`) and the tasks are generic,
  so a new exporter needs one new list entry, no new tasks.
- Rollout in batches with `serial` and an immediate stop with
  `max_fail_percentage` limits the impact of a broken agent version.
