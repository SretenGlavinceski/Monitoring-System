# inventory/

The inventory describes **which machines exist**, **which groups they belong
to**, and **which settings apply to them**. The playbooks and roles are the
same for every environment; only the inventory differs.

```
inventory/
├── staging/          6 hosts, the default (ansible.cfg)
└── production/       13 hosts, selected with -i inventory/production
```

Each environment has the same layout:

| Path | Content |
|------|---------|
| `hosts.ini` | hosts with their IP addresses, grouped into tiers |
| `group_vars/all/vars.yml` | settings for every host of the environment, and the mapping of the vault secrets |
| `group_vars/all/vault.yml` | secrets, encrypted with Ansible Vault |
| `group_vars/<group>.yml` | settings for the hosts of one group |
| `host_vars/<host>.yml` | settings for one host |

Details of every file: [staging/README.md](staging/README.md),
[production/README.md](production/README.md).

## Groups

| Group | Tier |
|-------|------|
| `proxy` | nginx reverse proxy |
| `metrics` | Prometheus and Grafana |
| `logging` | Elasticsearch and Kibana |
| `collectors` | Logstash |
| `alert` | Alertmanager |
| `app` | demo application |
| `monitoring` | parent group of all six (`[monitoring:children]`), used for plays that run on every host |

The playbooks only refer to groups, never to individual hosts. The same
`site.yml` therefore builds a 6-host staging environment or a 13-host
production environment.

## Where variables come from

Ansible combines variables from several places. From lowest to highest
priority, as used in this project:

1. **role defaults** (`roles/<role>/defaults/main.yml`): every setting a role
   has, with a sensible default
2. **`group_vars/all/`**: settings for the whole environment
3. **`group_vars/<group>.yml`**: settings for one tier
4. **`host_vars/<host>.yml`**: settings for one host
5. **play variables** (`vars:` in a playbook)
6. **extra variables** (`-e` on the command line)

A role therefore works without any inventory settings, and the inventory only
contains what differs from the defaults or between environments. Example:
`es_replicas` is `0` in the role defaults, stays `0` in staging and is set to
`1` in `production/group_vars/logging.yml`.

`group_vars/` and `host_vars/` exist only inside each environment, not in the
project root. Variables in a root-level `group_vars/` would have a higher
priority than the environment's own files and would silently override them.

## Secrets

`group_vars/all/vault.yml` contains only variables named `vault_*`, encrypted.
`group_vars/all/vars.yml` maps each to the name the roles use, for example
`grafana_admin_password: "{{ vault_grafana_admin_password }}"`. See section 4
of the root README.

## Differences between the environments

| Setting | File | Staging | Production |
|---------|------|---------|------------|
| hosts | `hosts.ini` | 1 per group | 2 per group, 3 in `logging` |
| `monitoring_host` | `group_vars/all/vars.yml` | 192.168.56.10 | 192.168.56.21 |
| Elasticsearch heap, mode, replicas | `group_vars/logging.yml` | 1g, single node, 0 | 512m, 3-node cluster, 1 |
| Logstash heap | `group_vars/collectors.yml` | 512m | 256m |
| Prometheus retention | `group_vars/metrics.yml` | 7 days | 30 days |
| Alertmanager | `group_vars/alert.yml` | single instance | cluster of 2 |
| alert addresses | `group_vars/alert.yml` | `*-staging@example.com` | `ops@`, `dev@example.com` |
| TLS certificate | `group_vars/proxy.yml` | for 192.168.56.10 | for 192.168.56.21 and .22 |
| Kibana | `host_vars/` | stg-logging | logging1, logging2 |

The production heaps are smaller than in staging because production runs 13
machines on the same host computer and each machine has less memory.
