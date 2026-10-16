# Monitoring System

Ansible automation for a complete monitoring and logging platform, built for
the course *Infrastructure Programming*, Project 5: DevOps monitoring
platform.

A single command, `ansible-playbook site.yml`, takes a set of clean Ubuntu
24.04 machines to a working platform:

- **Metrics:** Prometheus collects metrics from every machine, Grafana shows
  them as dashboards, Alertmanager sends notifications.
- **Logs:** Filebeat ships logs from every machine to Logstash, which stores
  them in Elasticsearch; Kibana is used to search them.
- **Reverse proxy:** nginx with TLS and a login in front of all web interfaces.
- **Application:** a small web application that the platform monitors, so
  every part of the platform has real data to show.

## Contents

1. [Architecture](#1-architecture)
2. [Project structure](#2-project-structure)
3. [Installation on the host machine](#3-installation-on-the-host-machine)
4. [Ansible Vault](#4-ansible-vault)
5. [Running the project](#5-running-the-project)
6. [Demonstration guide](#6-demonstration-guide)
7. [Requirement coverage](#7-requirement-coverage)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Architecture

![Production architecture](docs/architecture-production.png)

Diagram of the staging environment: [docs/architecture-staging.png](docs/architecture-staging.png).

### 1.1 Tiers

The platform is divided into six tiers. Each tier is an Ansible inventory
group, and each group runs on its own virtual machines.

| Tier | Inventory group | Components | Staging | Production |
|------|-----------------|------------|---------|------------|
| Reverse proxy | `proxy` | nginx, nginx_exporter | stg-proxy | proxy1, proxy2 |
| Metrics | `metrics` | Prometheus, Grafana | stg-metrics | metrics1, metrics2 |
| Logs | `logging` | Elasticsearch, Kibana, elasticsearch_exporter | stg-logging | logging1, logging2, logging3 |
| Log collectors | `collectors` | Logstash | stg-collector | collectors1, collectors2 |
| Alerting | `alert` | Alertmanager | stg-alert | alert1, alert2 |
| Application | `app` | demo app (Flask, gunicorn) | stg-app | app1, app2 |
| *every host* | `monitoring` | node_exporter, Filebeat | all | all |

`monitoring` is the parent group of all six tiers. Plays that must run on
every machine target this group.

### 1.2 Machines, services and ports

| Machine | Staging IP | Production IPs | Services (port) |
|---------|-----------|----------------|-----------------|
| proxy | 192.168.56.10 | .21, .22 | nginx (80, 443), nginx_exporter (9113) |
| metrics | 192.168.56.11 | .31, .32 | Prometheus (9090), Grafana (3000) |
| logging | 192.168.56.12 | .41, .42, .43 | Elasticsearch (9200, 9300), Kibana (5601, not on logging3), elasticsearch_exporter (9114) |
| collectors | 192.168.56.13 | .51, .52 | Logstash (5044) |
| alert | 192.168.56.14 | .61, .62 | Alertmanager (9093, 9094 cluster) |
| app | 192.168.56.15 | .71, .72 | demo app (8000) |
| every machine | | | node_exporter (9100), Filebeat, rsyslog |

All machines are on the VirtualBox host-only network `192.168.56.0/24`. Only
the proxy is meant to be used from a browser; all other ports are reached by
the platform's own components.

### 1.3 Data flows

**Web traffic (through the proxy).** The browser connects to nginx over HTTPS.
nginx terminates TLS, checks the login and forwards the request by path:

| Path | Forwarded to | Login |
|------|--------------|-------|
| `/` | redirect to `/grafana/` | yes |
| `/grafana/` | Grafana, `metrics` hosts, port 3000 | yes (nginx), then Grafana's own login |
| `/prometheus/` | Prometheus, `metrics` hosts, port 9090 | yes |
| `/alertmanager/` | Alertmanager, `alert` hosts, port 9093 | yes |
| `/kibana/` | Kibana, `logging` hosts with Kibana, port 5601 | yes |
| `/app/` | demo app, `app` hosts, port 8000 | no, the application is public |

Port 80 only redirects to HTTPS and serves nginx's status page to the local
nginx_exporter.

**Metrics (pull).** Every 15 seconds Prometheus reads (*scrapes*) the
`/metrics` page of every target: node_exporter on every machine, the nginx
and Elasticsearch exporters, Alertmanager, the demo app and itself. The
target list is generated from the inventory. Prometheus evaluates recording
rules and alert rules on the collected data and sends firing alerts to
Alertmanager. Grafana queries the Prometheus on its own machine.

**Logs (push).** Filebeat on every machine reads log files (syslog, auth.log,
nginx logs on proxies, Elasticsearch logs on logging nodes, the JSON log of
the app on app hosts) and pushes new lines to Logstash on port 5044. Logstash
parses nginx access lines into fields and writes every event to
Elasticsearch, into an index named `monitoring-<log_type>-<date>`. Kibana
searches these indices.

**Alerts.** Alertmanager receives firing alerts, groups them, and routes
them by the `team` label to a receiver. Each receiver notifies through
Slack and email.

### 1.4 Infrastructure and application separation

Every scrape target and every log line carries a label `team` with the value
`infra` or `app`:

| Where | How the label is set | What uses it |
|-------|----------------------|--------------|
| Metrics | label on each scrape target in `prometheus.yml` | alert rules, Alertmanager routing |
| Alerts | inherited from the metric; set explicitly on `AppHighErrorRate` | Alertmanager: `team="app"` → receiver `app`, everything else → receiver `infra` |
| Logs | field `fields.team` set per Filebeat input | Kibana searches and filters |
| Grafana | folders *Infrastructure* and *Application* | dashboards |
| Kibana | data views *infrastructure logs* and *application logs* | Discover |

Infrastructure alerts reach the ops channel and address, application alerts
reach the dev channel and address.

### 1.5 Staging and production

Both environments use the same playbooks and roles. Only the inventory
differs.

| | Staging | Production |
|-|---------|------------|
| Purpose | development and testing | demonstration, high availability |
| Machines | 6, one per tier | 13 |
| Elasticsearch | single node, no replicas | 3-node cluster, one replica of every index |
| Alertmanager | single instance | two instances, clustered (gossip on port 9094) |
| Prometheus, Grafana | one | two, each scraping every target independently |
| Proxy address | https://192.168.56.10 | https://192.168.56.21 |
| Inventory | `inventory/staging` (default) | `inventory/production` |

Both environments run as VirtualBox machines on the same host, one at a time.

---

## 2. Project structure

```
monitoring-system/
├── README.md                     this document
├── ansible.cfg                   Ansible settings for this project
├── requirements.txt              Python packages for the control node (ansible-core)
├── requirements.yml              Galaxy roles and collections
├── Vagrantfile                   virtual machines of both environments
├── site.yml                      full deployment playbook
├── rolling_update.yml            rolling update of the application tier
├── templates/
│   ├── README.md
│   └── upstreams.conf.j2         nginx upstreams, used by both playbooks
├── inventory/
│   ├── README.md
│   ├── staging/                  6 hosts, see inventory/staging/README.md
│   └── production/               13 hosts, see inventory/production/README.md
├── roles/
│   ├── monitoring-agents/        node_exporter, Filebeat, exporters per group
│   ├── prometheus-config/        Prometheus configuration, alert and recording rules
│   ├── grafana-dashboards/       Grafana data source, dashboards, authentication
│   ├── elk-pipeline/             Elasticsearch, Logstash, Kibana, Filebeat configuration
│   └── demo-app/                 the monitored application
└── docs/
    ├── site.md                   site.yml play by play
    ├── rolling_update.md         rolling_update.yml step by step
    ├── architecture-production.png
    └── architecture-staging.png
```

Every role, the inventory, the `templates/` folder and both playbooks have
their own documentation; see the table in [2.3](#23-documentation-map).

Files created locally and kept out of Git (`.gitignore`): `.vault_pass`,
`.venv/`, `.vagrant/`, `.facts_cache/`, `galaxy_roles/`, `collections/`.

### 2.1 Root files

| File | Purpose |
|------|---------|
| `ansible.cfg` | Project-wide Ansible settings, explained below. |
| `requirements.txt` | Pins `ansible-core` to an exact version, installed with `pip`. |
| `requirements.yml` | Pins the Galaxy roles and collections, installed with `ansible-galaxy install -r requirements.yml` into `galaxy_roles/` and `collections/`. |
| `Vagrantfile` | Defines the VirtualBox machines of both environments with fixed IP addresses and memory sizes. The environment is selected with the variable `MON_ENV`. |
| `site.yml` | The full deployment. See [docs/site.md](docs/site.md). |
| `rolling_update.yml` | Deploys a new application version one host at a time. See [docs/rolling_update.md](docs/rolling_update.md). |
| `.gitignore` | Keeps secrets, downloads and generated files out of Git. |

**`ansible.cfg`:**

| Setting | Effect |
|---------|--------|
| `inventory = inventory/staging` | Staging is the default; production must be selected explicitly with `-i inventory/production`. |
| `roles_path = galaxy_roles:roles` | Galaxy roles install into `galaxy_roles/`, the project's own roles are in `roles/`. |
| `collections_path = collections` | Collections install inside the project. |
| `vault_password_file = .vault_pass` | Vault files are decrypted automatically during a run. |
| `forks = 20` | Up to 20 hosts are handled in parallel (all 13 production hosts at once). |
| `interpreter_python = auto_silent` | Python on the hosts is detected without warnings. |
| `retry_files_enabled = False` | No `.retry` files after a failed run. |
| `callback_result_format = yaml` | Readable task output. |
| `host_key_checking = False` | The lab machines are recreated often and change their SSH host keys. |
| `deprecation_warnings = False` | Hides deprecation notices of the Galaxy content. |
| `force_handlers = True` | Handlers still run on a host when a later task on it fails, so a failed run cannot leave a service with an old configuration. |
| `gathering = smart`, `fact_caching = jsonfile`, `fact_caching_connection = .facts_cache`, `fact_caching_timeout = 86400` | Facts are cached for 24 hours in `.facts_cache/` and reused by later plays. |
| `become = True` | Tasks run with sudo. |
| `pipelining = True` | Fewer SSH operations per task, faster runs. |

### 2.2 Galaxy content

The Galaxy roles install software; the project's own roles configure it.

| Galaxy role | Installs | Used by |
|-------------|----------|---------|
| `prometheus.prometheus.prometheus` | Prometheus | `prometheus-config` |
| `prometheus.prometheus.node_exporter` | node_exporter | `monitoring-agents` |
| `prometheus.prometheus.alertmanager` | Alertmanager, amtool | alerting play in `site.yml` |
| `grafana.grafana.grafana` | Grafana | `grafana-dashboards` |
| `geerlingguy.elasticsearch` | Elasticsearch 7 | `elk-pipeline` |
| `geerlingguy.nginx` | nginx | proxy play in `site.yml` |

The collections `community.general` (htpasswd module) and `ansible.posix`
(sysctl module) provide modules. The `cloudalchemy` roles named in the
assignment are archived; `prometheus.prometheus` and `grafana.grafana` are
their maintained successors.

### 2.3 Documentation map

| Document | Covers |
|----------|--------|
| `README.md` | architecture, structure, setup, Vault, operation, demonstration |
| `docs/site.md` | every play of `site.yml` |
| `docs/rolling_update.md` | the rolling update |
| `templates/README.md` | the nginx upstreams template |
| `inventory/README.md` | inventory layout, variable precedence |
| `inventory/staging/README.md`, `inventory/production/README.md` | every file of each environment |
| `roles/<role>/README.md` | every file, task, handler, template and variable of the role |

---

## 3. Installation on the host machine

The host is the machine that runs VirtualBox and Ansible. These instructions
are for **Ubuntu 24.04**.

### 3.1 Check hardware virtualization

```bash
grep -cE '(vmx|svm)' /proc/cpuinfo
```

A number greater than 0 means virtualization is available. If it is 0,
enable VT-x or AMD-V in the BIOS/UEFI settings.

### 3.2 VirtualBox 7.2 (Oracle repository)

Ubuntu's own VirtualBox package (7.0) does not build on the newer kernels of
Ubuntu 24.04.4, so VirtualBox comes from Oracle's repository:

```bash
sudo apt install build-essential linux-headers-$(uname -r)

wget -qO- https://www.virtualbox.org/download/oracle_vbox_2016.asc \
  | sudo gpg --dearmor -o /usr/share/keyrings/oracle-virtualbox-2016.gpg

echo "deb [arch=amd64 signed-by=/usr/share/keyrings/oracle-virtualbox-2016.gpg] https://download.virtualbox.org/virtualbox/debian $(lsb_release -cs) contrib" \
  | sudo tee /etc/apt/sources.list.d/virtualbox.list

sudo apt update && sudo apt install virtualbox-7.2
```

### 3.3 Vagrant (HashiCorp repository)

Ubuntu 24.04 has no `vagrant` package:

```bash
wget -qO- https://apt.releases.hashicorp.com/gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/hashicorp.list

sudo apt update && sudo apt install vagrant
```

### 3.4 Git and Python

```bash
sudo apt install git python3-venv
```

### 3.5 Verify

```bash
VBoxManage --version      # 7.2.8 or newer
vagrant --version         # 2.4.9 or newer
lsmod | grep vboxdrv      # prints a line: the VirtualBox kernel module is loaded
```

### 3.6 Project setup

```bash
git clone <repository-url> monitoring-system
cd monitoring-system

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ansible-galaxy install -r requirements.yml
```

`source .venv/bin/activate` must be repeated in every new terminal. Then set
up the Vault as described in the next section.

### 3.7 Resources

| | Staging | Production |
|-|---------|------------|
| VMs | 6 | 13 |
| RAM used by the VMs | about 7 GB | about 10.5 GB |
| Free disk space | about 20 GB | about 40 GB |

Only one environment should run at a time.

---

## 4. Ansible Vault

### 4.1 What is protected

Each environment has one encrypted file,
`inventory/<env>/group_vars/all/vault.yml`, with these values:

| Variable | Used for |
|----------|----------|
| `vault_grafana_admin_password` | Grafana admin login |
| `vault_proxy_basic_auth_password` | nginx login in front of all monitoring UIs |
| `vault_slack_webhook_infra` | Slack webhook of the infrastructure channel |
| `vault_slack_webhook_app` | Slack webhook of the application channel |
| `vault_smtp_password` | password of the SMTP account Alertmanager sends email with |
| `vault_tls_private_key` | private key of the proxy's TLS certificate |

The two environments have separate files with separate values, so staging
secrets never work in production.

### 4.2 How the secrets reach the roles

The roles never read `vault_*` variables directly. The plain file
`group_vars/all/vars.yml` next to the vault maps each one to the name the
roles use:

```yaml
grafana_admin_password: "{{ vault_grafana_admin_password }}"
proxy_basic_auth_password: "{{ vault_proxy_basic_auth_password }}"
tls_private_key: "{{ vault_tls_private_key }}"
```

Anyone reading the repository can see which secrets exist and where they are
used, without being able to read their values.

During a run, Ansible reads the vault password from `.vault_pass` (set in
`ansible.cfg`), decrypts `vault.yml` **in memory only**, and the values are
used like any other variable. The decrypted file is never written to disk on
the control node.

Tasks that handle secrets hide their values from the output: `no_log: true`
on the TLS key, the Grafana password check and reset and the `grafana.ini`
settings, and `alertmanager_mask_diff: true` for the Alertmanager
configuration. Do not run playbooks with `--diff` during a demonstration; it
prints the changed lines of templates.

### 4.3 First-time setup on a new machine

The repository contains the vault files already encrypted. To use them you
need the vault password from the project owner:

```bash
echo 'the-vault-password' > .vault_pass
chmod 600 .vault_pass
```

To check that it works:

```bash
ansible-vault view inventory/staging/group_vars/all/vault.yml
```

`.vault_pass` is listed in `.gitignore` and must never be committed.

### 4.4 Creating the vault files from scratch

When the vault files still contain the placeholder values (`change-me-*`):

1. Choose a vault password and store it in `.vault_pass` as above.
2. Open `inventory/staging/group_vars/all/vault.yml` and
   `inventory/production/group_vars/all/vault.yml` and set real values.
   Slack webhooks are created as *Incoming Webhooks* of a Slack app, one per
   channel. For Gmail, the SMTP password is an *app password*; the SMTP
   server and user are set in `group_vars/alert.yml`.
3. Encrypt both files **before the first commit**:

   ```bash
   ansible-vault encrypt inventory/staging/group_vars/all/vault.yml
   ansible-vault encrypt inventory/production/group_vars/all/vault.yml
   ```

4. Check: the first line of each file is `$ANSIBLE_VAULT;1.1;AES256`.

If an unencrypted version is ever committed, it remains in the Git history.
Change the affected secrets in that case.

### 4.5 Everyday operations

| Task | Command |
|------|---------|
| Show the decrypted content | `ansible-vault view inventory/staging/group_vars/all/vault.yml` |
| Change a value | `ansible-vault edit inventory/staging/group_vars/all/vault.yml` (re-encrypts on save) |
| Change the vault password | `ansible-vault rekey inventory/*/group_vars/all/vault.yml`, then update `.vault_pass` |
| Apply changed secrets | run `site.yml` again |

To add a new secret: add `vault_<name>` to `vault.yml` with `ansible-vault
edit`, map it in `vars.yml` as `<name>: "{{ vault_<name> }}"`, and use
`<name>` in the role.

### 4.6 TLS certificate and key

All proxies of an environment share one self-signed certificate. The
certificate is public and stored in `inventory/<env>/group_vars/proxy.yml`
(`tls_certificate`); the private key is in the vault (`vault_tls_private_key`).
To create a new pair (production example):

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 825 -sha256 \
  -keyout monitoring.key -out monitoring.crt \
  -subj "/CN=192.168.56.21" \
  -addext "subjectAltName=IP:192.168.56.21,IP:192.168.56.22"
```

Paste the certificate into `tls_certificate`, the key into
`vault_tls_private_key` with `ansible-vault edit`, then delete both files.

### 4.7 Limits

The Vault protects secrets in the repository and on the control node. On the
target machines the services need the values in plain form, for example the
Grafana password in `/etc/grafana/grafana.ini`. Those files are protected by
ownership and permissions (`0640`, readable by root and the service user;
the TLS key `0600`, root only). The proxy's password file stores a hash, not
the password.

---

## 5. Running the project

### 5.1 Environments at a glance

| | Staging | Production |
|-|---------|------------|
| Start VMs | `vagrant up` | `MON_ENV=production vagrant up` |
| Ansible inventory | default | `-i inventory/production` |
| Proxy URL | https://192.168.56.10 | https://192.168.56.21 |

Every Vagrant command for production needs `MON_ENV=production`, or run
`export MON_ENV=production` once in the terminal.

### 5.2 Virtual machines (Vagrant)

| Command | Effect |
|---------|--------|
| `vagrant up` | creates the machines on first use (downloads the Ubuntu 24.04 image once), otherwise starts them |
| `vagrant status` | shows the state of every machine |
| `vagrant ssh <name>` | opens a shell on one machine, e.g. `vagrant ssh stg-app` |
| `vagrant halt` | shuts the machines down, keeping their disks |
| `vagrant destroy -f` | deletes the machines completely |
| `vagrant destroy -f && vagrant up` | clean machines, as required for the "from a clean system" demonstration |

### 5.3 Deployment (Ansible)

```bash
source .venv/bin/activate

# connectivity
ansible all -m ping
ansible -i inventory/production all -m ping

# full deployment
ansible-playbook site.yml
ansible-playbook -i inventory/production site.yml
```

The first run takes 20 to 40 minutes, mostly downloading packages. A second
run should report `changed=0` for every host; a task that reports a change on
the second run is not idempotent.

Useful options:

| Option | Effect |
|--------|--------|
| `--limit app` | run only on the `app` group (any group or host name works) |
| `--syntax-check` | check the playbook without running it |
| `--list-tasks` | show every task the playbook would run |
| `-v` | more output, for debugging |

### 5.4 Rolling update

```bash
ansible-playbook -i inventory/production rolling_update.yml -e app_version=1.1.0
```

Updates the application hosts one at a time while the others keep serving.
See [docs/rolling_update.md](docs/rolling_update.md).

### 5.5 Ad-hoc commands

Ansible can run single commands on groups. Group names work in both
environments, so these commands need only the inventory to change:

```bash
ansible app -m systemd -a "name=demo-app state=restarted"     # restart a service
ansible metrics -m shell -a "systemctl is-active prometheus"   # check a service
ansible 'logging[0]' -m shell -a "curl -s localhost:9200/_cluster/health?pretty"   # first host of a group
```

### 5.6 Shutting down and rebuilding

```bash
vagrant halt                          # stop, keep everything
vagrant destroy -f                    # delete
rm -rf .facts_cache                   # optional, cached facts of the deleted machines
vagrant up && ansible-playbook site.yml
```

`site.yml` collects fresh facts at its start, so the cache does not need to be
removed; deleting it only keeps the folder tidy.

---

## 6. Demonstration guide

Each part below shows one service: what to open, what to point out, and how
to trigger something that becomes visible there or in another service.

### 6.0 Preparation

Set the variables of the environment once per terminal:

```bash
# staging
export PROXY=192.168.56.10 INV=inventory/staging
# production
export PROXY=192.168.56.21 INV=inventory/production MON_ENV=production
```

All browser addresses below start with `https://$PROXY`. The browser shows a
certificate warning (self-signed certificate); accept it once. Log in with
user `admin` and the proxy password from the vault.

Background traffic makes every dashboard more interesting. Run this in a
separate terminal during the demonstration; it sends one normal and one
failing request every second:

```bash
while true; do
  curl -sk -o /dev/null https://$PROXY/app/
  curl -sk -o /dev/null https://$PROXY/app/fail
  sleep 1
done
```

Stop it with Ctrl+C. Because half of its requests fail, it triggers the
`AppHighErrorRate` alert after about two minutes, which is useful for 6.5.

### 6.1 Reverse proxy (nginx)

**Show:**

```bash
curl -I http://$PROXY/                                   # 301 → https: no unencrypted access
curl -kI https://$PROXY/prometheus/                      # 401: login required
curl -kI -u admin:PROXY_PASSWORD https://$PROXY/prometheus/   # 200 with the login
curl -k https://$PROXY/app/                              # the app, no login: public
curl -I http://$PROXY/stub_status                        # 403: status page only for the local exporter
openssl s_client -connect $PROXY:443 </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -ext subjectAltName -enddate   # the certificate
```

In the browser: `https://$PROXY/` redirects to Grafana; `/prometheus/`,
`/alertmanager/`, `/kibana/` and `/app/` are all served from the same address.

**Effect elsewhere:** every request above is counted by nginx_exporter
(Prometheus job `nginx`) and written to nginx's access log, which appears in
Kibana as `fields.log_type: nginx_access`.

### 6.2 Demo application

**Show:** `https://$PROXY/app/` displays the version and the machine that
answered. In production, reload a few times: the machine alternates between
`app1` and `app2` (load balancing by nginx).

**Trigger:**

```bash
curl -k  https://$PROXY/app/fail -o /dev/null -w "%{http_code}\n"   # 500
curl -k  https://$PROXY/app/slow -o /dev/null -w "%{time_total}s\n" # 1-3 seconds
ansible app -m shell -a "curl -s localhost:8000/metrics | grep '^app_requests_total'"
ansible app -m shell -a "tail -n 3 /var/log/demo-app/app.log"
```

**Effect elsewhere:**

| Action | Visible in |
|--------|-----------|
| any request to `/app/` | Grafana → *Application → Demo application*: requests per second |
| `/app/fail` | Grafana: error rate; Kibana: `status >= 500` in *application logs*; after sustained failures `AppHighErrorRate` in Prometheus and Alertmanager |
| `/app/slow` | Grafana: latency p95 rises |
| stopping the app (`ansible app -m systemd -a "name=demo-app state=stopped"`) | Prometheus target `app` DOWN, `InstanceDown` with `team=app`, routed to the app receiver |

Start the app again with `state=started`.

### 6.3 Prometheus

**Show:**

- `/prometheus/targets`: every target grouped by job (`node`, `nginx`,
  `elasticsearch`, `alertmanager`, `app`, `prometheus`), each with the labels
  `host` and `team`.
- `/prometheus/rules`: recording rules and alert rules, all loaded.
- `/prometheus/alerts`: alert rules and their state.
- `/prometheus/query`, queries to run:

  ```promql
  up
  up == 0
  sum by (status) (rate(app_requests_total[1m]))
  instance:node_cpu_utilisation:rate5m
  instance:node_memory_utilisation:ratio * 100
  ```

**Trigger:** stop an exporter:

```bash
ansible collectors -m systemd -a "name=node_exporter state=stopped"
```

| After | Visible |
|-------|---------|
| 15 s | `/prometheus/targets`: the target is DOWN |
| 15 s | `/prometheus/alerts`: `InstanceDown` PENDING |
| 1 min | `InstanceDown` FIRING, sent to Alertmanager |

Start it again with `state=started`; the alert resolves.

**Optional, CPU alert:**

```bash
ansible app -m apt -a "name=stress-ng"
ansible app -B 480 -P 0 -m shell -a "stress-ng --cpu 0 --timeout 420s"
```

`HighCpuUsage` fires after about 6 to 10 minutes (the 5-minute average must
exceed 80 % for 5 minutes).

### 6.4 Grafana

**Show:** `/grafana/`, log in with `admin` and the Grafana password from the
vault.

- *Dashboards → Infrastructure → Hosts*: hosts up and down, targets down,
  firing alerts, CPU, memory, disk and network per machine.
- *Dashboards → Application → Demo application*: instances up, requests per
  second, error rate, latency p50 and p95, requests by status code.
- *Connections → Data sources*: the Prometheus data source, provisioned and
  not editable.

**Trigger:**

| Action | Visible |
|--------|---------|
| background traffic (6.0) | *Demo application*: requests per second, error rate around 50 % |
| `/app/slow` a few times | *Demo application*: latency p95 |
| stopping an exporter (6.3) | *Hosts*: "Hosts down" 1 (red), "Firing alerts" 1 after a minute |
| stress-ng (6.3) | *Hosts*: CPU of the app machine near 100 % |

Panels refresh every 30 seconds.

### 6.5 Alertmanager

**Show:** `/alertmanager/`: active alerts with their labels; *Status* shows
the configuration and, in production, both cluster members.

**Trigger:**

```bash
# a test alert sent directly, appears within seconds
ansible 'alert[0]' -m shell -a "amtool alert add DemoAlert team=app severity=warning host=demo --annotation=summary='test alert' --alertmanager.url=http://localhost:9093/alertmanager"

# routing: which receiver gets an alert with these labels
ansible 'alert[0]' -m shell -a "amtool config routes test --config.file=/etc/alertmanager/alertmanager.yml team=app"
ansible 'alert[0]' -m shell -a "amtool config routes test --config.file=/etc/alertmanager/alertmanager.yml team=infra"

# delivery attempts to Slack and email
ansible 'alert[0]' -m shell -a "journalctl -u alertmanager -n 20 --no-pager"
```

Real alerts: `InstanceDown` from 6.3 (team `infra`) and `AppHighErrorRate`
from the background traffic (team `app`) arrive here and go to different
receivers.

**Silence:** *New Silence*, matcher `host="stg-collector"` (production:
`host="collectors1"`), duration 1h. The matching alert leaves the active list
and no notifications are sent. Delete the silence afterwards.

### 6.6 Filebeat and Logstash

**Show:**

```bash
ansible collectors -m shell -a "curl -s localhost:9600/_node/stats/events?pretty"   # events in, filtered, out
ansible app -m shell -a "filebeat test output"                                     # connection to Logstash
ansible collectors -m shell -a "cat /etc/logstash/conf.d/beats.conf"               # the pipeline
```

**Trigger:** write a log line on any machine:

```bash
ansible app -m shell -a "logger 'demo: hello from the app machine'"
```

The Logstash event counters increase; the line appears in Kibana (6.8).

**Resilience:** no log line is lost while Logstash is down:

```bash
ansible collectors -m systemd -a "name=logstash state=stopped"
ansible app -m shell -a "logger 'demo: written while logstash was down'"
ansible collectors -m systemd -a "name=logstash state=started"
```

After Logstash has started (about a minute), the line appears in Kibana.
Filebeat retried and continued from its saved position.

### 6.7 Elasticsearch

**Show:**

```bash
ansible 'logging[0]' -m shell -a "curl -s localhost:9200/_cluster/health?pretty"          # status green
ansible 'logging[0]' -m shell -a "curl -s 'localhost:9200/_cat/nodes?v'"                  # nodes, master marked *
ansible 'logging[0]' -m shell -a "curl -s 'localhost:9200/_cat/indices/monitoring-*?v&s=index'"   # daily indices
ansible 'logging[0]' -m shell -a "curl -s localhost:9200/_index_template/monitoring-logs?pretty"  # index template
```

In Prometheus, `elasticsearch_cluster_health_status{color="green"}` is 1:
the metrics side monitors the logging side.

**Trigger (production):** lose a node:

```bash
ansible -i inventory/production logging3 -m systemd -a "name=elasticsearch state=stopped"
```

Cluster health becomes yellow (copies missing), every search still works,
`InstanceDown` fires for logging3's exporter. Start it again; health returns
to green once the copies are rebuilt.

### 6.8 Kibana

**Show:** `/kibana/` → *Discover*, time range *Last 1 hour*. Choose a data
view and type a query:

| Data view | Query | Shows |
|-----------|-------|-------|
| infrastructure logs | `message:"hello from the app machine"` | the `logger` line from 6.6 |
| infrastructure logs | `fields.log_type:nginx_access and response:500` | failed requests seen by nginx, fields parsed by Logstash |
| infrastructure logs | `fields.log_type:syslog and host.name:*proxy*` | system log of the proxy |
| application logs | `status >= 500` | failed requests logged by the app |
| application logs | `level:error and path:"/fail"` | the same, by field |

Open a document to show every field, including `fields.team`, `fields.env`
and `host.name`.

**Trigger:** every request in 6.1 and 6.2 produces a line here within a few
seconds.

### 6.9 Rolling update

Open `https://$PROXY/app/` and keep reloading, or watch it from a terminal:

```bash
while true; do curl -sk https://$PROXY/app/ | grep -o 'Version <b>[^<]*</b>, served by <b>[^<]*'; sleep 0.5; done
```

In another terminal:

```bash
ansible-playbook -i $INV rolling_update.yml -e app_version=1.1.0
```

In production, the output switches host by host from 1.0.0 to 1.1.0 and the
page never fails, because one app host keeps serving. In staging there is
only one app host, so requests fail briefly while it is updated.

### 6.10 Suggested order for the presentation

| Part of the demonstration | Time | Content |
|---------------------------|------|---------|
| Architecture | 5 min | section 1 and the diagram |
| `site.yml` from a clean system | 10 min | `vagrant destroy -f && vagrant up`, then `ansible-playbook site.yml`; while it runs, explain the plays (docs/site.md) |
| Services | | 6.1 → 6.8, following one request: proxy, app, metrics, alerts, logs |
| Rolling update | 2 min | 6.9 |
| Roles and templates | 2 min | role READMEs, e.g. `prometheus.yml.j2` and the upstreams template |
| Questions | 5 min | |

The first run of `site.yml` takes longer than 10 minutes. For the
presentation, start it in advance on clean machines or show a second,
idempotent run (`changed=0`) live.

---

## 7. Requirement coverage

| Requirement | Implementation |
|-------------|----------------|
| Full automation, one command | `ansible-playbook site.yml` |
| `roles/`, `inventory/`, `group_vars/`, `host_vars/` | see section 2 and `inventory/README.md` |
| At least 3 custom roles | 5: `monitoring-agents`, `prometheus-config`, `grafana-dashboards`, `elk-pipeline`, `demo-app` |
| Ansible Vault | section 4 |
| Idempotency | change detection in every task; second run reports `changed=0` |
| Handlers | every role, see the role READMEs |
| Jinja2 templates | every configuration file is a template |
| README | this document and the linked documents |
| Inventory with production and staging | `inventory/production`, `inventory/staging` |
| prometheus-config: dynamic targets, alert rules, recording rules | `roles/prometheus-config` |
| grafana-dashboards: data source provisioning, JSON dashboards, auth | `roles/grafana-dashboards` |
| elk-pipeline: Logstash pipeline, Filebeat, index templates, Kibana patterns | `roles/elk-pipeline` |
| monitoring-agents: node_exporter and Filebeat on all hosts, exporters per group | `roles/monitoring-agents` |
| Fact caching: facts first, then deployment with cached facts | first play of `site.yml`, `ansible.cfg` |
| Agents with `serial: 20%` | agents play of `site.yml` |
| Rolling update: `serial`, `delegate_to`, health check | `rolling_update.yml` |

---

## 8. Troubleshooting

| Problem | Cause and solution |
|---------|--------------------|
| `vagrant up` fails with an error about VT-x, VMX or KVM | KVM holds the CPU's virtualization feature. `sudo modprobe -r kvm_intel kvm` (Intel) or `sudo modprobe -r kvm_amd kvm` (AMD). Permanently: `echo "blacklist kvm_intel" \| sudo tee /etc/modprobe.d/blacklist-kvm.conf` |
| `vboxdrv` not loaded | `sudo /sbin/vboxconfig` builds and loads the module; it needs `build-essential` and the kernel headers |
| `ansible all -m ping` fails | Machines not running (`vagrant status`), or the inventory and running environment do not match (staging machines with `-i inventory/production`) |
| `Attempting to decrypt but no vault secrets found` | `.vault_pass` missing or wrong |
| A run fails in the middle | Fix the cause and run `site.yml` again; finished tasks report `ok` and the run continues |
| Changes to configuration not active after a failed run | Should not happen with `force_handlers = True`. Otherwise restart or reload the service, e.g. `ansible metrics -m systemd -a "name=prometheus state=reloaded"` |
| `curl` query with `{...}` returns nothing | `curl` treats braces as a pattern; use `curl -g` or `--data-urlencode` |
| Alert notifications not delivered | Placeholder Slack webhooks or SMTP values in the vault; see 4.4 and the Alertmanager log (6.5) |
