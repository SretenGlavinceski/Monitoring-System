# site.yml

`site.yml` is the main playbook. It takes clean Ubuntu 24.04 hosts to a fully
working platform and can be run again at any time to bring the hosts back to
the defined state.

```bash
ansible-playbook site.yml                              # staging
ansible-playbook -i inventory/production site.yml      # production
```

## Overview

The playbook consists of eight plays, run in this order:

| # | Play | Hosts | Roles | Purpose |
|---|------|-------|-------|---------|
| 1 | Gather facts on all hosts | `monitoring` | | collect facts into the cache, refresh apt |
| 2 | Logging tier | `logging` | `elk-pipeline` | Elasticsearch, index template, Kibana |
| 3 | Collectors tier | `collectors` | `elk-pipeline` | Logstash |
| 4 | Metrics tier | `metrics` | `prometheus-config`, `grafana-dashboards` | Prometheus, Grafana |
| 5 | Alerting tier | `alert` | `prometheus.prometheus.alertmanager` | Alertmanager with routing |
| 6 | Application tier | `app` | `demo-app` | the monitored application |
| 7 | Monitoring agents on all hosts | `monitoring` | `monitoring-agents` | node_exporter, exporters, Filebeat |
| 8 | Reverse proxy | `proxy` | `geerlingguy.nginx` | nginx, TLS, login, routing |

### Why this order

- **Facts first.** Play 1 fills the fact cache for every host, so all later
  plays can use the facts of hosts that are not part of the play.
- **Storage before senders.** Elasticsearch (2) exists before Logstash (3)
  writes to it, and Logstash exists before Filebeat (7) sends to it, so
  connections succeed immediately instead of retrying.
- **Monitoring before the monitored.** Prometheus (4) and Alertmanager (5)
  are ready when the agents (7) start reporting.
- **Proxy last.** nginx (8) forwards to services that all exist by then.

If a play fails on every one of its hosts, Ansible stops the whole run. After
fixing the cause, run the playbook again: finished work reports `ok` and the
run continues.

---

## Play 1: Gather facts on all hosts

```yaml
- name: Gather facts on all hosts
  hosts: monitoring
  gather_facts: false
  tasks:
    - name: Gather facts
      ansible.builtin.setup:
    - name: Update apt cache
      ansible.builtin.apt:
        update_cache: true
        cache_valid_time: 3600
```

**Facts** are information Ansible collects about each host: IP addresses,
operating system, CPU architecture, memory and more. `ansible.cfg` stores
them in a cache (`gathering = smart`, `fact_caching = jsonfile`,
`.facts_cache/`, valid 24 hours).

- `gather_facts: false` plus an explicit `setup` task: with the `smart`
  setting, Ansible skips gathering for hosts that already have cached facts.
  After `vagrant destroy` and `vagrant up` the cache would still describe the
  old machines. Calling `setup` directly always collects fresh facts and
  overwrites the cache.
- All following plays use the cached facts and do not gather again. This is
  the "gather facts on all hosts first, then deploy with cached facts"
  requirement.
- `Update apt cache` refreshes the package lists once, so the plays that
  install packages do not each do it. `cache_valid_time: 3600` skips it when
  the lists are less than an hour old, which keeps the play idempotent.

---

## Play 2: Logging tier

```yaml
- name: Logging tier
  hosts: logging
  roles:
    - elk-pipeline
```

The `elk-pipeline` role checks the groups of each host. On `logging` hosts it
installs Elasticsearch (through `geerlingguy.elasticsearch`), waits for the
cluster, creates the index template and, where `kibana_enabled` is true,
installs Kibana and its data views. Details: `roles/elk-pipeline/README.md`.

---

## Play 3: Collectors tier

```yaml
- name: Collectors tier
  hosts: collectors
  roles:
    - elk-pipeline
```

The same role, on `collectors` hosts: installs Logstash with the beats
pipeline that writes to all `logging` hosts.

---

## Play 4: Metrics tier

```yaml
- name: Metrics tier
  hosts: metrics
  roles:
    - prometheus-config
    - grafana-dashboards
```

- `prometheus-config` installs Prometheus through the Galaxy role and gives it
  this project's configuration: scrape targets from the inventory, alert
  rules, recording rules.
- `grafana-dashboards` installs Grafana through the Galaxy role and
  provisions the data source, the dashboards and the authentication settings.

Prometheus and Grafana share the metrics hosts because Grafana queries
Prometheus constantly; on the same host that traffic stays local.

---

## Play 5: Alerting tier

```yaml
- name: Alerting tier
  hosts: alert
  vars:
    alertmanager_web_external_url: "https://{{ monitoring_host }}/alertmanager/"
    alertmanager_mask_diff: true
    alertmanager_smtp: ...
    alertmanager_route: ...
    alertmanager_receivers: ...
  roles:
    - prometheus.prometheus.alertmanager
```

Alertmanager has no custom role; it is configured entirely through variables
of the Galaxy role, defined in this play because the routing is the same in
both environments. Values that differ per environment (addresses, SMTP
server, cluster) come from `inventory/<env>/group_vars/alert.yml`, secrets
from the vault.

| Variable | Meaning |
|----------|---------|
| `alertmanager_web_external_url` | Alertmanager is served behind the proxy at `/alertmanager/`; links in notifications use this address |
| `alertmanager_mask_diff` | hides the configuration (it contains webhooks and the SMTP password) in Ansible's output |
| `alertmanager_smtp` | sender address, SMTP server and login used for all email notifications |
| `alertmanager_route` | the routing tree, see below |
| `alertmanager_receivers` | two receivers, `infra` and `app`, each with Slack and email |

**Routing:**

```yaml
alertmanager_route:
  receiver: infra                # default receiver
  group_by: [alertname, host]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - receiver: app
      matchers:
        - team="app"
```

- Alerts with the label `team="app"` go to the receiver `app`; all others to
  `infra`.
- `group_by`: alerts with the same name and host become one notification.
- `group_wait`: wait 30 s for related alerts before the first notification.
- `group_interval`: send updates of a group at most every 5 minutes.
- `repeat_interval`: remind every 4 hours while an alert is still firing.

**Receivers:**

| Receiver | Slack | Email |
|----------|-------|-------|
| `infra` | `slack_webhook_infra`, channel `#infra-alerts` | `alert_email_infra` |
| `app` | `slack_webhook_app`, channel `#app-alerts` | `alert_email_app` |

`send_resolved: true` also notifies when an alert stops firing.

The Galaxy role writes `/etc/alertmanager/alertmanager.yml` from these
variables, validates it with `amtool check-config`, and installs a systemd
service with the cluster flags from `alertmanager_cluster` (production: two
peers, staging: clustering disabled).

---

## Play 6: Application tier

```yaml
- name: Application tier
  hosts: app
  roles:
    - demo-app
```

Installs the demo application: virtualenv, packages, code, systemd service.
The version comes from `inventory/<env>/group_vars/app.yml`. Details:
`roles/demo-app/README.md`.

---

## Play 7: Monitoring agents on all hosts

```yaml
- name: Monitoring agents on all hosts
  hosts: monitoring
  serial: "20%"
  max_fail_percentage: 0
  roles:
    - monitoring-agents
```

Installs node_exporter and Filebeat on every host, nginx_exporter on
proxies and elasticsearch_exporter on logging hosts.

- `serial: "20%"`: the hosts are processed in batches of 20 % (production:
  2 hosts per batch, 13 hosts → 7 batches; staging: 1 host per batch). Each
  batch is finished completely before the next starts. A broken agent version
  or configuration therefore affects only the first batch.
- `max_fail_percentage: 0`: the play stops as soon as any host fails. Without
  it, Ansible would only stop when *every* host of a batch failed, and a
  rollout could continue past a broken host.

---

## Play 8: Reverse proxy

```yaml
- name: Reverse proxy
  hosts: proxy
  vars:
    nginx_remove_default_vhost: true
    nginx_listen_ipv6: false
    nginx_vhosts: [ ...two servers... ]
  pre_tasks: [ ...certificate, key, login, upstreams... ]
  roles:
    - geerlingguy.nginx
  tasks:
    - name: Reload nginx after a certificate, password or upstream change
```

### Variables for `geerlingguy.nginx`

| Variable | Meaning |
|----------|---------|
| `nginx_remove_default_vhost` | removes nginx's default site, which would also listen on port 80 |
| `nginx_listen_ipv6` | no IPv6 listeners; the platform uses IPv4 only |
| `nginx_vhosts` | the two server blocks below |

**Server on port 80** (`monitoring-http.conf`):

- `location = /stub_status`: nginx's built-in status page, allowed only from
  `127.0.0.1`, read by nginx_exporter on the same host.
- `location /`: every other request is redirected to HTTPS (301).

**Server on port 443** (`monitoring.conf`):

- `ssl_certificate`, `ssl_certificate_key`: TLS with the certificate and key
  installed by the pre_tasks.
- `auth_basic`, `auth_basic_user_file`: login required for the whole server,
  checked against `/etc/nginx/.htpasswd`.
- `proxy_set_header ...`: passes the original host, client address and
  protocol to the services behind the proxy.
- `location = /`: redirects to `/grafana/`.
- `location /grafana/`: forwards to the `grafana` upstream. The
  `Authorization` header is removed, otherwise Grafana would try to log in
  with the proxy's credentials and reject the request.
- `location /kibana/`, `/prometheus/`, `/alertmanager/`: forward to their
  upstreams.
- `location /app/`: `auth_basic off`, the application is public;
  `proxy_pass http://app/` removes the `/app` prefix, so the application sees
  `/`, `/fail` and so on.

The upstreams (which hosts serve each path) are defined in
`templates/upstreams.conf.j2`, see `templates/README.md`.

### pre_tasks

Run before the nginx role, so the files exist when nginx first checks its
configuration.

| Task | Effect |
|------|--------|
| Install python passlib for the htpasswd module | `community.general.htpasswd` needs this library on the host |
| Create nginx directories | `/etc/nginx/ssl` and `/etc/nginx/conf.d` |
| Install TLS certificate | `tls_certificate` (from `group_vars/proxy.yml`) → `/etc/nginx/ssl/monitoring.crt`, mode 0644 |
| Install TLS private key | `tls_private_key` (from the vault) → `/etc/nginx/ssl/monitoring.key`, mode 0600, `no_log: true` |
| Create basic auth user | user `proxy_basic_auth_user` with the vault password, stored as a hash in `/etc/nginx/.htpasswd`, readable by root and nginx (`www-data`) |
| Configure upstreams | renders `templates/upstreams.conf.j2` to `/etc/nginx/conf.d/upstreams.conf` |

Each of these tasks registers its result (`tls_cert`, `tls_key`, `htpasswd`,
`upstreams`).

### Role and final task

`geerlingguy.nginx` installs nginx, writes `nginx.conf` and the two server
blocks, and reloads nginx when they change.

On a clean host the pre_tasks run before nginx is installed, so a handler
notified there would try to reload a service that does not exist yet. The
reload is therefore a normal task at the end, run only when one of the
registered pre_tasks reported a change:

```yaml
- name: Reload nginx after a certificate, password or upstream change
  ansible.builtin.service:
    name: nginx
    state: reloaded
  when: tls_cert.changed or tls_key.changed or htpasswd.changed or upstreams.changed
```

A reload applies the new configuration without dropping open connections.

---

## ansible.cfg

Settings that apply to every run of `site.yml` and `rolling_update.yml`:

| Setting | Effect |
|---------|--------|
| `inventory = inventory/staging` | staging is the default; production is selected with `-i inventory/production` |
| `roles_path = galaxy_roles:roles` | Galaxy roles install into `galaxy_roles/`, the project's roles are in `roles/` |
| `collections_path = collections` | collections install inside the project |
| `vault_password_file = .vault_pass` | vault files are decrypted automatically |
| `forks = 20` | up to 20 hosts are handled in parallel |
| `force_handlers = True` | handlers still run on a host when a later task on it fails, so a failed run cannot leave a service with an old configuration |
| `gathering = smart`, `fact_caching = jsonfile`, `fact_caching_connection = .facts_cache`, `fact_caching_timeout = 86400` | facts are cached for 24 hours and reused by later plays |
| `host_key_checking = False` | the lab machines are recreated often and change their SSH host keys |
| `become = True` | tasks run with sudo |
| `pipelining = True` | fewer SSH operations per task |
| `interpreter_python`, `retry_files_enabled`, `callback_result_format`, `deprecation_warnings` | quieter, more readable output |

