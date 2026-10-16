# Local lab for both environments. Only one environment runs at a time:
#   vagrant up                          staging (default)
#   MON_ENV=production vagrant up       production
# The IP addresses must match inventory/<env>/hosts.ini.

ENVIRONMENTS = {
  "staging" => {
    "stg-proxy"     => ["192.168.56.10", 512],
    "stg-metrics"   => ["192.168.56.11", 1024],
    "stg-logging"   => ["192.168.56.12", 3072],
    "stg-collector" => ["192.168.56.13", 1536],
    "stg-alert"     => ["192.168.56.14", 384],
    "stg-app"       => ["192.168.56.15", 512],
  },
  "production" => {
    "proxy1"      => ["192.168.56.21", 384],
    "proxy2"      => ["192.168.56.22", 384],
    "metrics1"    => ["192.168.56.31", 768],
    "metrics2"    => ["192.168.56.32", 768],
    "logging1"    => ["192.168.56.41", 2048],
    "logging2"    => ["192.168.56.42", 2048],
    "logging3"    => ["192.168.56.43", 1024],
    "collectors1" => ["192.168.56.51", 768],
    "collectors2" => ["192.168.56.52", 768],
    "alert1"      => ["192.168.56.61", 384],
    "alert2"      => ["192.168.56.62", 384],
    "app1"        => ["192.168.56.71", 384],
    "app2"        => ["192.168.56.72", 384],
  },
}

env = ENV.fetch("MON_ENV", "staging")
abort "Unknown MON_ENV '#{env}', use staging or production" unless ENVIRONMENTS.key?(env)

Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.synced_folder ".", "/vagrant", disabled: true

  ENVIRONMENTS[env].each do |name, (ip, memory)|
    config.vm.define name do |node|
      node.vm.hostname = name
      node.vm.network "private_network", ip: ip
      node.vm.provider "virtualbox" do |vb|
        vb.name = "mon-#{name}"
        vb.memory = memory
        vb.cpus = memory >= 1024 ? 2 : 1
        vb.linked_clone = true
      end
    end
  end
end
