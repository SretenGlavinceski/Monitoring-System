# inventory/staging

Staging environment: one host per tier, six hosts in total. It is the default
inventory (`ansible.cfg`), so commands without `-i` use it.

```bash
vagrant up
ansible-playbook site.yml
```

Proxy address: https://192.168.56.10

## Hosts

| Host | IP | Group | Vagrant memory |
|------|----|-------|----------------|
| stg-proxy | 192.168.56.10 | proxy | 512 MB |
| stg-metrics | 192.168.56.11 | metrics | 1 GB |
| stg-logging | 192.168.56.12 | logging | 3 GB |
| stg-collector | 192.168.56.13 | collectors | 1.5 GB |
| stg-alert | 192.168.56.14 | alert | 384 MB |
| stg-app | 192.168.56.15 | app | 512 MB |

The IP addresses must match the `staging` section of the `Vagrantfile`.

## Files

### hosts.ini

The six hosts with `ansible_host` (the IP address Ansible connects to), one
section per group, and `[monitoring:children]`, which makes all six groups
members of `monitoring`.

### group_vars/all/vars.yml

Applies to every host.

| Variable | Value | Meaning |
|----------|-------|---------|
| `env_name` | `staging` | written into Prometheus labels and Filebeat fields |
| `monitoring_host` | `192.168.56.10` | the address users open; used for the URLs of Grafana, Prometheus, Alertmanager and Kibana behind the proxy |
| `ansible_user` | `vagrant` | SSH user created by Vagrant |
| `ansible_ssh_private_key_file` | `.vagrant/machines/<host>/virtualbox/private_key` | SSH key Vagrant creates for each machine |
| `proxy_basic_auth_user` | `admin` | user name of the proxy login |
| `grafana_admin_password` and the other secrets | `{{ vault_... }}` | mapping of the vault values to the names the roles use |

### group_vars/all/vault.yml

Encrypted. The Grafana admin password, the proxy password, the two Slack
webhooks, the SMTP password and the TLS private key of this environment.
Edit with `ansible-vault edit inventory/staging/group_vars/all/vault.yml`.

### group_vars/logging.yml

| Variable | Value | Meaning |
|----------|-------|---------|
| `es_cluster_name` | `monitoring-staging` | Elasticsearch cluster name |
| `es_heap_size` | `1g` | Elasticsearch memory |
| `es_single_node` | `true` | one node, no cluster discovery |
| `es_replicas` | `0` | no copies of indices, there is no second node |
| `kibana_max_old_space_mb` | `512` | Kibana memory limit |

### group_vars/collectors.yml

`logstash_heap_size: 512m`: Logstash memory.

### group_vars/metrics.yml

`prometheus_retention: 7d`: metrics are kept for 7 days.

### group_vars/alert.yml

| Variable | Meaning |
|----------|---------|
| `alertmanager_cluster` | `listen-address: ""` disables clustering, there is one instance |
| `alert_email_infra`, `alert_email_app` | recipients of infrastructure and application alerts |
| `alert_email_from` | sender address |
| `smtp_smarthost`, `smtp_username` | SMTP server and login (the password is in the vault) |

### group_vars/app.yml

`app_version: "1.0.0"`: version of the demo application deployed by
`site.yml`.

### group_vars/proxy.yml

`tls_certificate`: the self-signed certificate of the proxy, for
192.168.56.10. Public by nature; the matching private key is in the vault.

### host_vars/stg-logging.yml

`kibana_enabled: true`: Kibana runs on this host.
