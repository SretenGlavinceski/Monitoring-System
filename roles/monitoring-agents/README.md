# monitoring-agents

Everything that runs on every host:

- node_exporter, installed with the Galaxy role `prometheus.prometheus.node_exporter`
- Filebeat, by including `tasks/filebeat.yml` of the `elk-pipeline` role
  (the Filebeat configuration is part of the log pipeline)
- extra exporters depending on group membership: `nginx_exporter` on hosts in
  `proxy`, `elasticsearch_exporter` on hosts in `logging`

The list of extra exporters is a variable (`agent_exporters`). Each entry names
the group that gets it, the role installs only the entries whose group the
current host is a member of.

In `site.yml` this role runs with `serial: 20%` and `max_fail_percentage: 0`:
hosts are updated in batches and the rollout stops at the first failure.

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `node_exporter_port` | `9100` | node_exporter listen port |
| `exporter_install_dir` | `/opt/exporters` | where exporter archives are unpacked |
| `nginx_exporter_version` | `1.5.2` | nginx-prometheus-exporter version |
| `es_exporter_version` | `1.10.0` | elasticsearch_exporter version |
| `agent_exporters` | see defaults | exporters and the group that gets them |

## Handlers

`restart nginx_exporter`, `restart elasticsearch_exporter`
