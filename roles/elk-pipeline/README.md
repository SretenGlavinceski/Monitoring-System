# Role: elk-pipeline

The log pipeline: **Filebeat → Logstash → Elasticsearch → Kibana**. The role
does different work depending on the groups of the host it runs on.

| Part | Runs on | Called from |
|------|---------|-------------|
| Elasticsearch, index template | `logging` hosts | play *Logging tier* in `site.yml` |
| Kibana, data views | `logging` hosts with `kibana_enabled: true` | play *Logging tier* |
| Logstash | `collectors` hosts | play *Collectors tier* |
| Filebeat | every host | role `monitoring-agents` (`include_role` with `tasks_from: filebeat.yml`) |

| | |
|-|-|
| Installs with | Galaxy role `geerlingguy.elasticsearch` (Elasticsearch); apt packages from Elastic's repository (Logstash, Kibana, Filebeat) |
| Assignment item | *elk-pipeline: Logstash pipeline, Filebeat configuration, ES index templates, Kibana patterns* |

## Background

- **Filebeat** runs on every machine, follows log files and sends every new
  line. It remembers its position in each file (the *registry*), so nothing is
  lost or sent twice after a restart or while Logstash is unreachable.
- **Logstash** receives the lines, turns text into fields where needed and
  writes them to Elasticsearch.
- **Elasticsearch** stores every line as a JSON **document** in an **index**
  and makes every field searchable. An **index template** defines field types
  and settings for new indices. Each index is stored in **shards**; a
  **replica** is a copy of a shard on another node.
- **Kibana** is the web interface for searching Elasticsearch. A **data view**
  (earlier: *index pattern*) tells Kibana which indices to search together.

All indices are named `monitoring-<log_type>-<date>`, for example
`monitoring-nginx_access-2026.10.15`. The prefix `logs-` is avoided on
purpose: Elasticsearch 7.17 ships a built-in template for `logs-*-*` that turns
such indices into data streams, which Logstash cannot write to the way it is
configured here.

## Files

| File | Type | Purpose |
|------|------|---------|
| `defaults/main.yml` | variables | settings of all four components |
| `tasks/main.yml` | tasks | chooses the parts for the host's groups |
| `tasks/elasticsearch.yml` | tasks | kernel setting, Elasticsearch, index template |
| `tasks/kibana.yml` | tasks | Kibana and its data views |
| `tasks/logstash.yml` | tasks | Logstash and its pipeline |
| `tasks/filebeat.yml` | tasks | rsyslog and Filebeat; included by `monitoring-agents` |
| `tasks/elastic_repo.yml` | tasks | Elastic's apt key and repository, shared by Logstash and Filebeat |
| `handlers/main.yml` | handlers | restart Kibana, Logstash, Filebeat |
| `templates/elasticsearch-cluster.yml.j2` | template | cluster settings, appended to `elasticsearch.yml` |
| `templates/index-template.json.j2` | template | the `monitoring-logs` index template |
| `templates/kibana.yml.j2` | template | Kibana configuration |
| `templates/beats.conf.j2` | template | the Logstash pipeline |
| `templates/filebeat.yml.j2` | template | the Filebeat configuration |
| `meta/main.yml` | metadata | description, platform, no dependencies |

## Tasks

### tasks/main.yml

| Task | Condition | Includes |
|------|-----------|----------|
| Elasticsearch | host in `logging` | `elasticsearch.yml` |
| Kibana | host in `logging` and `kibana_enabled` | `kibana.yml` |
| Logstash | host in `collectors` | `logstash.yml` |

`group_names` is the list of groups of the current host. One role thus serves
two tiers, and Filebeat is included separately by `monitoring-agents`.

### tasks/elasticsearch.yml

| # | Task | What it does |
|---|------|--------------|
| 1 | Set vm.max_map_count | sets the kernel parameter to 262144, which Elasticsearch requires to start. Skipped in LXC containers, where the host's kernel setting applies. |
| 2 | Render cluster settings | renders `elasticsearch-cluster.yml.j2` into the fact `es_extra_options` |
| 3 | Install Elasticsearch | runs `geerlingguy.elasticsearch` with the Elastic 7.x repository, listen address `0.0.0.0`, port, heap size, and `es_extra_options`. The Galaxy role adds the repository, installs the package, writes `elasticsearch.yml` and the heap settings, and starts the service. |
| 4 | Wait for the cluster to accept writes | waits until the cluster health is at least yellow (up to about 2 minutes) |
| 5 | Build the index template | renders `index-template.json.j2` and parses it into a fact. `run_once`: the template belongs to the cluster, not to a node. |
| 6 | Read the current index template | `GET /_index_template/monitoring-logs`; 200 or 404 are both expected |
| 7 | Create or update the index template | `PUT` of the template with `_meta.checksum`, a SHA-1 of its content. Runs only when the template does not exist yet or its stored checksum differs, so a changed template file is applied and an unchanged one reports no change. |

### tasks/kibana.yml

| # | Task | What it does |
|---|------|--------------|
| 1 | Install Kibana | apt package (the repository was added by the Elasticsearch role) |
| 2 | Limit Kibana memory | writes `--max-old-space-size=<kibana_max_old_space_mb>` to `/etc/kibana/node.options`; Kibana runs on Node.js and would otherwise take more memory than the lab machines have |
| 3 | Configure Kibana | renders `kibana.yml.j2` to `/etc/kibana/kibana.yml` |
| 4 | Enable and start Kibana | systemd |
| 5 | Apply configuration changes | `flush_handlers`, runs a pending restart now |
| 6 | Wait for the Kibana API | up to 5 minutes; Kibana starts slowly |
| 7 | Read the current data views | `GET` of each data view in `kibana_data_views` |
| 8 | Create or update data views | `POST ...?overwrite=true` for each data view that does not exist (404) or whose index list differs |

Tasks 2 and 3 notify `Restart kibana`.

### tasks/logstash.yml

| # | Task | What it does |
|---|------|--------------|
| 1 | Elastic apt repository | includes `elastic_repo.yml` |
| 2 | Install Logstash | apt package |
| 3 | Set JVM heap | sets `-Xms` and `-Xmx` in `/etc/logstash/jvm.options` to `logstash_heap_size` |
| 4 | Configure pipeline | renders `beats.conf.j2` to `/etc/logstash/conf.d/beats.conf` |
| 5 | Enable and start Logstash | systemd |

Tasks 3 and 4 notify `Restart logstash`.

### tasks/filebeat.yml

Included by `monitoring-agents` on every host.

| # | Task | What it does |
|---|------|--------------|
| 1 | Make sure rsyslog is installed (Filebeat reads /var/log/syslog) | rsyslog writes `/var/log/syslog`, which Filebeat reads |
| 2 | Elastic apt repository | includes `elastic_repo.yml` |
| 3 | Install Filebeat | apt package |
| 4 | Configure Filebeat | renders `filebeat.yml.j2` to `/etc/filebeat/filebeat.yml`, mode 0600; notifies `Restart filebeat` |
| 5 | Enable and start Filebeat | systemd |

### tasks/elastic_repo.yml

Adds Elastic's signing key and the repository line
`deb https://artifacts.elastic.co/packages/7.x/apt stable main`. Key and line
are exactly those `geerlingguy.elasticsearch` uses, so on logging hosts, where
both run, apt sees one repository and not two conflicting ones.

## Handlers (`handlers/main.yml`)

| Handler | Notified by |
|---------|-------------|
| `Restart kibana` | memory limit or `kibana.yml` changed |
| `Restart logstash` | heap or pipeline changed |
| `Restart filebeat` | `filebeat.yml` changed |

Elasticsearch restarts are handled by the Galaxy role's own handler.

## Templates

### elasticsearch-cluster.yml.j2

Appended to `elasticsearch.yml` through the Galaxy role's
`elasticsearch_extra_options`.

```jinja
cluster.name: {{ es_cluster_name }}
node.name: {{ inventory_hostname }}
network.publish_host: {{ ansible_host }}
{% if es_single_node | bool %}
discovery.type: single-node
{% else %}
discovery.seed_hosts: [ ...IP of every host in logging... ]
cluster.initial_master_nodes: [ ...name of every host in logging... ]
{% endif %}
```

| Setting | Meaning |
|---------|---------|
| `cluster.name` | nodes only join a cluster with the same name |
| `node.name` | the inventory name, shown in `_cat/nodes` |
| `network.publish_host` | the address other nodes use to reach this one. Every VirtualBox machine also has a NAT interface with the same address on every machine; without this setting the nodes could announce that address and never find each other. |
| `discovery.type: single-node` | staging: one node, no search for others |
| `discovery.seed_hosts` | production: where to find the other nodes, generated from the `logging` group |
| `cluster.initial_master_nodes` | production: nodes that take part in the first master election |

The master is elected by majority. With three nodes, two form a majority, so
the cluster keeps working when one node fails.

Rendered for production, logging1:

```yaml
cluster.name: monitoring
node.name: logging1
network.publish_host: 192.168.56.41
discovery.seed_hosts: ["192.168.56.41", "192.168.56.42", "192.168.56.43"]
cluster.initial_master_nodes: ["logging1", "logging2", "logging3"]
```

### index-template.json.j2

The **ES index template** of the assignment item. It applies to every new
index matching `monitoring-*`, with `priority: 200`.

| Part | Content |
|------|---------|
| settings | 1 shard per index, `number_of_replicas` from `es_replicas` (0 staging, 1 production) |
| mappings | `@timestamp` date, `message` text, `level` keyword, `status` integer, `duration_ms` float, `host.name` keyword, `fields.env`, `fields.log_type`, `fields.team` keyword |

`keyword` fields are matched exactly (good for filters such as
`fields.team:app`), `text` fields by words. Fields not listed are typed
automatically when they first appear.

### kibana.yml.j2

| Setting | Value | Meaning |
|---------|-------|---------|
| `server.host` | `0.0.0.0` | reachable from the proxy |
| `server.port` | `5601` | |
| `server.basePath`, `server.rewriteBasePath` | `/kibana`, `true` | Kibana works under `/kibana/` behind the proxy |
| `server.publicBaseUrl` | `https://<monitoring_host>/kibana` | public address, used for links |
| `elasticsearch.hosts` | `http://127.0.0.1:9200` | the Elasticsearch node on the same machine |

### beats.conf.j2

The **Logstash pipeline** of the assignment item.

```
input {
  beats { port => 5044 }
}

filter {
  if [fields][log_type] == "nginx_access" {
    grok { match => { "message" => "%{COMBINEDAPACHELOG}" } }
    date { match => [ "timestamp", "dd/MMM/yyyy:HH:mm:ss Z" ] }
  }
}

output {
  elasticsearch {
    hosts => [ ...every host in logging, port 9200... ]
    index => "monitoring-%{[fields][log_type]}-%{+YYYY.MM.dd}"
    manage_template => false
    ilm_enabled => false
    data_stream => "false"
  }
}
```

| Part | Meaning |
|------|---------|
| `beats` input | receives events from Filebeat on port 5044 |
| `grok` | splits an nginx access line into fields (`clientip`, `verb`, `request`, `response`, `bytes`, `agent`, ...) with the standard pattern `COMBINEDAPACHELOG` |
| `date` | uses the time written in the log line as the event's timestamp |
| `hosts` | all logging nodes; Logstash spreads the writes |
| `index` | one index per log type and day |
| `manage_template => false` | Logstash does not install its own template; ours defines the fields |
| `ilm_enabled`, `data_stream` | plain daily indices, without lifecycle management or data streams |

App logs need no filter: they are JSON and Filebeat splits them into fields.

### filebeat.yml.j2

The **Filebeat configuration** of the assignment item. Inputs depend on the
host's groups:

| Input id | Files | Hosts | `log_type` | `team` |
|----------|-------|-------|------------|--------|
| `syslog` | `/var/log/syslog`, `/var/log/auth.log` | all | `syslog` | infra |
| `nginx-access` | `/var/log/nginx/access.log` | `proxy` | `nginx_access` | infra |
| `nginx-error` | `/var/log/nginx/error.log` | `proxy` | `nginx_error` | infra |
| `elasticsearch` | `/var/log/elasticsearch/<cluster name>.log` | `logging` | `elasticsearch` | infra |
| `app` | `/var/log/demo-app/app.log`, parsed as JSON (`ndjson`) | `app` | `app` | app |

Also:

- `fields.env`: `staging` or `production`, on every event
- `add_host_metadata`: adds `host.name` and other host details
- `output.logstash`: every host in `collectors`, port 5044, `loadbalance: true`
  (spread over all collectors; if one is down, the others are used)

## Variables (`defaults/main.yml`)

| Variable | Default | Description |
|----------|---------|-------------|
| `es_version` | `7.x` | Elastic repository branch |
| `es_cluster_name` | `monitoring` | cluster name |
| `es_heap_size` | `1g` | Elasticsearch memory |
| `es_single_node` | `true` | single node mode |
| `es_replicas` | `0` | replicas per index |
| `es_port` | `9200` | HTTP port |
| `es_index_prefix` | `monitoring` | index name prefix |
| `kibana_enabled` | `false` | Kibana on this host (set in `host_vars/`) |
| `kibana_port` | `5601` | |
| `kibana_base_path` | `/kibana` | path behind the proxy |
| `kibana_max_old_space_mb` | `512` | Kibana memory limit |
| `kibana_data_views` | `infra-logs`: `monitoring-syslog-*,monitoring-nginx_*,monitoring-elasticsearch-*`; `app-logs`: `monitoring-app-*` | data views (**Kibana patterns** of the assignment item) |
| `logstash_heap_size` | `512m` | Logstash memory |
| `logstash_beats_port` | `5044` | beats input port |
| `filebeat_app_log` | `/var/log/demo-app/app.log` | log file of the demo app |
| `filebeat_infra_team`, `filebeat_app_team` | `infra`, `app` | values of `fields.team` |

## Verifying

```bash
ansible 'logging[0]' -m shell -a "curl -s localhost:9200/_cluster/health?pretty"
ansible 'logging[0]' -m shell -a "curl -s 'localhost:9200/_cat/indices/monitoring-*?v'"
ansible collectors -m shell -a "curl -s localhost:9600/_node/stats/events?pretty"
ansible all -m shell -a "filebeat test output"
```

## Design decisions

- One role for the whole pipeline; `group_names` decides what each host gets.
- The Filebeat configuration belongs to this role and is reused by
  `monitoring-agents`.
- The index template and the data views are compared with the existing ones
  and only written when they differ.
- `network.publish_host` and the `monitoring-` index prefix are required for
  the cluster and the indices to work in this environment.
