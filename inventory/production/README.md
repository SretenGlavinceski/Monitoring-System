# inventory/production

Production environment: every tier on two hosts, Elasticsearch on three,
13 hosts in total. It must be selected explicitly.

```bash
MON_ENV=production vagrant up
ansible-playbook -i inventory/production site.yml
```

Proxy address: https://192.168.56.21 (https://192.168.56.22 works as well).

## Hosts

| Host | IP | Group | Vagrant memory |
|------|----|-------|----------------|
| proxy1, proxy2 | 192.168.56.21, .22 | proxy | 384 MB |
| metrics1, metrics2 | 192.168.56.31, .32 | metrics | 768 MB |
| logging1, logging2 | 192.168.56.41, .42 | logging | 2 GB |
| logging3 | 192.168.56.43 | logging | 1 GB |
| collectors1, collectors2 | 192.168.56.51, .52 | collectors | 768 MB |
| alert1, alert2 | 192.168.56.61, .62 | alert | 384 MB |
| app1, app2 | 192.168.56.71, .72 | app | 384 MB |

The IP addresses must match the `production` section of the `Vagrantfile`.

### What two or three hosts per tier provide

| Tier | Behaviour |
|------|-----------|
| proxy | either proxy can be used; both have the same certificate and configuration |
| metrics | both Prometheus instances scrape every target and hold the same data; each Grafana uses its local Prometheus |
| logging | one Elasticsearch cluster; every index has one replica on another node, so one node can fail without data loss; three nodes are needed for a safe master election |
| collectors | Filebeat spreads log lines over both Logstash instances and uses the other one if one is down |
| alert | the two Alertmanagers share state; every notification is sent once, even though both Prometheus instances send every alert to both |
| app | nginx balances requests between both; the rolling update replaces them one at a time |

## Files

### hosts.ini

The 13 hosts with `ansible_host`, one section per group, and
`[monitoring:children]`.

### group_vars/all/vars.yml

Same variables as staging, with production values:

| Variable | Value |
|----------|-------|
| `env_name` | `production` |
| `monitoring_host` | `192.168.56.21` |
| `ansible_user`, `ansible_ssh_private_key_file` | Vagrant user and key, as in staging |
| `proxy_basic_auth_user` | `admin` |
| secret mappings | `{{ vault_... }}` |

### group_vars/all/vault.yml

Encrypted. The production secrets, separate from staging: Grafana admin
password, proxy password, two Slack webhooks, SMTP password, TLS private key.
Edit with `ansible-vault edit inventory/production/group_vars/all/vault.yml`.

### group_vars/logging.yml

| Variable | Value | Meaning |
|----------|-------|---------|
| `es_cluster_name` | `monitoring` | cluster name, the same on all three nodes |
| `es_heap_size` | `512m` | Elasticsearch memory per node |
| `es_single_node` | `false` | the nodes find each other through the seed list generated from the `logging` group |
| `es_replicas` | `1` | one copy of every index on another node |
| `kibana_max_old_space_mb` | `512` | Kibana memory limit |

### group_vars/collectors.yml

`logstash_heap_size: 256m`.

### group_vars/metrics.yml

`prometheus_retention: 30d`.

### group_vars/alert.yml

| Variable | Meaning |
|----------|---------|
| `alertmanager_cluster` | `listen-address` is the host's own address on port 9094; `peers` is generated from the `alert` group: both hosts, port 9094 |
| `alert_email_infra`, `alert_email_app`, `alert_email_from` | recipients and sender |
| `smtp_smarthost`, `smtp_username` | SMTP server and login (the password is in the vault) |

### group_vars/app.yml

`app_version: "1.0.0"`: the version `site.yml` deploys. `rolling_update.yml`
can deploy another one with `-e app_version=...`.

### group_vars/proxy.yml

`tls_certificate`: the self-signed certificate shared by proxy1 and proxy2,
valid for 192.168.56.21 and 192.168.56.22.

### host_vars/

| File | Content | Meaning |
|------|---------|---------|
| `logging1.yml` | `kibana_enabled: true` | Kibana runs here |
| `logging2.yml` | `kibana_enabled: true` | Kibana runs here (second instance behind the proxy) |
| `logging3.yml` | `kibana_enabled: false` | Elasticsearch only |
