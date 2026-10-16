 # templates/

Jinja2 templates used directly by the playbooks (templates that belong to a
role are in that role's `templates/` folder).

| File | Used by | Rendered to |
|------|---------|-------------|
| `upstreams.conf.j2` | `site.yml` (proxy play), `rolling_update.yml` | `/etc/nginx/conf.d/upstreams.conf` on every proxy |

When a task gives only a file name as `src` (`src: upstreams.conf.j2`),
Ansible looks for it in the `templates/` folder next to the playbook. Both
playbooks are in the project root, so both find this file.

## upstreams.conf.j2

An nginx **upstream** is a named group of backend servers. A `location` in the
server configuration forwards to an upstream with `proxy_pass http://<name>`,
and nginx distributes requests across the servers of the group. This template
generates one upstream per service from the inventory.

| Upstream | Servers | Port | Used by location |
|----------|---------|------|------------------|
| `grafana` | all hosts in `metrics` | 3000 | `/grafana/` |
| `prometheus` | all hosts in `metrics` | 9090 | `/prometheus/` |
| `alertmanager` | all hosts in `alert` | 9093 | `/alertmanager/` |
| `kibana` | hosts in `logging` with `kibana_enabled: true` | 5601 | `/kibana/` |
| `app` | all hosts in `app` | 8000 | `/app/` |

### How it is built

```jinja
{% set down = upstream_down | default([]) %}
{% macro servers(group, port) -%}
{% for h in groups[group] %}
    server {{ hostvars[h].ansible_host }}:{{ port }}{{ ' down' if h in down else '' }};
{% endfor %}
{%- endmacro %}
```

- `groups[group]` is the list of hosts in an inventory group;
  `hostvars[h].ansible_host` is the IP address of a host from `hosts.ini`.
  Adding a host to a group adds it to the upstream on the next run.
- The **macro** `servers(group, port)` writes one `server` line per host and
  is called once per upstream, so the loop is written only once.
- `upstream_down` is a list of host names to mark as `down`. Normally it is
  not set and nothing is marked. `rolling_update.yml` sets it to the host
  being updated: nginx then sends no new requests to that host.

The `kibana` upstream uses its own loop with a condition, because only the
logging hosts that run Kibana belong in it (`kibana_enabled` is set per host in
`host_vars/`).

### ip_hash

```nginx
upstream grafana {
    ip_hash;
    ...
}
```

With `ip_hash`, nginx sends all requests of one client (by IP address) to the
same server. Each Grafana keeps its login sessions in its own database; without
`ip_hash` a user logged in on one instance would land on the other one and be
asked to log in again. Prometheus uses `ip_hash` too, so one user always sees
the data of one instance. The other upstreams have no state per user and use
nginx's default round robin.

### Rendered example (production)

```nginx
upstream grafana {
    ip_hash;
    server 192.168.56.31:3000;
    server 192.168.56.32:3000;
}

upstream prometheus {
    ip_hash;
    server 192.168.56.31:9090;
    server 192.168.56.32:9090;
}

upstream alertmanager {
    server 192.168.56.61:9093;
    server 192.168.56.62:9093;
}

upstream kibana {
    server 192.168.56.41:5601;
    server 192.168.56.42:5601;
}

upstream app {
    server 192.168.56.71:8000;
    server 192.168.56.72:8000;
}
```

During a rolling update of app1, the `app` upstream becomes:

```nginx
upstream app {
    server 192.168.56.71:8000 down;
    server 192.168.56.72:8000;
}
```
