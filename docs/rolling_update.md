# rolling_update.yml

`rolling_update.yml` deploys a new version of the demo application without
taking the application offline. The application hosts are updated one at a
time; while one host is updated, nginx sends all traffic to the others.

```bash
ansible-playbook -i inventory/production rolling_update.yml -e app_version=1.1.0
```

`-e app_version=1.1.0` sets the version to deploy. Without it, the version
from `inventory/<env>/group_vars/app.yml` is used.

## How it works

```yaml
- name: Rolling update of the application tier
  hosts: app
  serial: 1
  max_fail_percentage: 0
  pre_tasks:  ...take the host out of the proxies...
  roles:
    - demo-app
  post_tasks: ...check the host, put it back...
```

- `hosts: app`: only the application tier is updated.
- `serial: 1`: the whole play (pre_tasks, role, post_tasks) runs for one host
  before the next host starts.
- `max_fail_percentage: 0`: if a host fails, the update stops. The remaining
  hosts keep the old version and keep serving.

### Steps for each host

| Step | Task | Runs on | Effect |
|------|------|---------|--------|
| 1 | Take this host out of the proxy upstreams | every proxy (`delegate_to`) | renders `templates/upstreams.conf.j2` with `upstream_down: [<this host>]`; the host is marked `down` in the `app` upstream |
| 2 | Reload nginx | every proxy (`delegate_to`) | nginx stops sending new requests to the host; running requests finish |
| 3 | role `demo-app` | the host | installs the new version; the service file changes (it contains the version), so the handler `Restart demo-app` restarts the application at the end of the role |
| 4 | Wait until the new version answers | the host | requests `http://127.0.0.1:8000/health` every 5 s, up to 12 times, until it answers 200 **and** reports the expected version |
| 5 | Put this host back into the proxy upstreams | every proxy (`delegate_to`) | renders the template without `upstream_down`; the host is no longer marked `down` |
| 6 | Reload nginx | every proxy (`delegate_to`) | the host receives traffic again |

**`delegate_to`** runs a task on a different host than the one the play is
currently working on. Here the play works on an app host, but the upstream
file lives on the proxies, so steps 1, 2, 5 and 6 are delegated to every host
in the `proxy` group (`loop: "{{ groups['proxy'] }}"`).

**The health check (step 4)** is what makes the update safe: a host only gets
traffic again when it runs and reports the new version. If it never does, the
task fails after one minute, the host stays marked `down`, and
`max_fail_percentage: 0` stops the update. Users keep being served by the
hosts that were not touched.

## Production and staging

| | Production | Staging |
|-|------------|---------|
| App hosts | app1, app2 | stg-app |
| During the update | the other host serves every request | no host left, nginx answers 502 for a few seconds |

The rolling update is meant for production; in staging it runs the same
steps, which is enough to test the playbook.

## Observing an update

In one terminal, poll the application to see which version and host answer:

```bash
while true; do
  curl -sk https://192.168.56.21/app/ | grep -o 'Version <b>[^<]*</b>, served by <b>[^<]*'
  sleep 0.5
done
```

In a second terminal, start the update:

```bash
ansible-playbook -i inventory/production rolling_update.yml -e app_version=1.1.0
```

The first terminal shows only app2 while app1 is updated, then app1 with 1.1.0 and
app2 with 1.0.0, then only app1 while app2 is updated, and finally both with
1.1.0. No request fails.

In Grafana (*Application → Demo application*) the request rate stays
continuous; in `/prometheus/targets` the `app` targets stay up except for the
seconds of each restart.

## Keeping the version

`-e app_version=1.1.0` applies only to this run. The next run of `site.yml`
installs the version from `inventory/<env>/group_vars/app.yml` again. To make
a new version permanent, change it there.
