#!/usr/bin/env python3
#
# Copyright (C) 2018-2019 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import jinja2

from vyos.config import Config
from vyos import ConfigError

config_file = r'/etc/ddclient/ddclient.conf'
cache_file = r'/var/cache/ddclient/ddclient.cache'
pid_file = r'/var/run/ddclient/ddclient.pid'

config_tmpl = """
### Autogenerated by dynamic_dns.py ###
daemon=1m
syslog=yes
ssl=yes
pid={{ pid_file }}
cache={{ cache_file }}

{% for interface in interfaces -%}

#
# ddclient configuration for interface "{{ interface.interface }}":
#
{% if interface.web_url -%}
use=web, web='{{ interface.web_url}}' {%- if interface.web_skip %}, web-skip='{{ interface.web_skip }}'{% endif %}
{% else -%}
use=if, if={{ interface.interface }}
{% endif -%}

{% for rfc in interface.rfc2136 -%}
{% for record in rfc.record %}
# RFC2136 dynamic DNS configuration for {{ record }}.{{ rfc.zone }}
server={{ rfc.server }}
protocol=nsupdate
password={{ rfc.keyfile }}
ttl={{ rfc.ttl }}
zone={{ rfc.zone }}
{{ record }}
{% endfor -%}
{% endfor -%}

{% for srv in interface.service %}
{% for host in srv.host %}
# DynDNS provider configuration for {{ host }}
protocol={{ srv.protocol }},
max-interval=28d,
login={{ srv.login }},
password='{{ srv.password }}',
{% if srv.server -%}
server={{ srv.server }},
{% endif -%}
{% if 'cloudflare' in srv.protocol -%}
{% set zone = host.split('.',1) -%}
zone={{ zone[1] }},
{% endif -%}
{{ host }}
{% endfor %}
{% endfor %}

{% endfor %}
"""

# Mapping of service name to service protocol
default_service_protocol = {
    'afraid': 'freedns',
    'changeip': 'changeip',
    'cloudflare': 'cloudflare',
    'dnspark': 'dnspark',
    'dslreports': 'dslreports1',
    'dyndns': 'dyndns2',
    'easydns': 'easydns',
    'namecheap': 'namecheap',
    'noip': 'noip',
    'sitelutions': 'sitelutions',
    'zoneedit': 'zoneedit1'
}

default_config_data = {
    'interfaces': [],
    'cache_file': cache_file,
    'pid_file': pid_file
}

def get_config():
    dyndns = default_config_data
    conf = Config()
    if not conf.exists('service dns dynamic'):
        return None
    else:
        conf.set_level('service dns dynamic')

    for interface in conf.list_nodes('interface'):
        node = {
            'interface': interface,
            'rfc2136': [],
            'service': [],
            'web_skip': '',
            'web_url': ''
        }

        # set config level to e.g. "service dns dynamic interface eth0"
        conf.set_level('service dns dynamic interface {0}'.format(interface))

        # Handle RFC2136 - Dynamic Updates in the Domain Name System
        for rfc2136 in conf.list_nodes('rfc2136'):
            rfc = {
                'name': rfc2136,
                'keyfile': '',
                'record': [],
                'server': '',
                'ttl': '600',
                'zone': ''
            }

            if conf.exists('rfc2136 {0} key'.format(rfc2136)):
                rfc['keyfile'] = conf.return_value('rfc2136 {0} key'.format(rfc2136))

            if conf.exists('rfc2136 {0} record'.format(rfc2136)):
                rfc['record'] = conf.return_values('rfc2136 {0} record'.format(rfc2136))

            if conf.exists('rfc2136 {0} server'.format(rfc2136)):
                rfc['server'] = conf.return_value('rfc2136 {0} server'.format(rfc2136))

            if conf.exists('rfc2136 {0} ttl'.format(rfc2136)):
                rfc['ttl'] = conf.return_value('rfc2136 {0} ttl'.format(rfc2136))

            if conf.exists('rfc2136 {0} zone'.format(rfc2136)):
                rfc['zone'] = conf.return_value('rfc2136 {0} zone'.format(rfc2136))

            node['rfc2136'].append(rfc)

        # Handle DynDNS service providers
        for service in conf.list_nodes('service'):
            srv = {
                'provider': service,
                'host': [],
                'login': '',
                'password': '',
                'protocol': '',
                'server': '',
                'custom' : False
            }

            # preload protocol from default service mapping
            if service in default_service_protocol.keys():
                srv['protocol'] = default_service_protocol[service]
            else:
                srv['custom'] = True

            if conf.exists('service {0} login'.format(service)):
                srv['login'] = conf.return_value('service {0} login'.format(service))

            if conf.exists('service {0} host-name'.format(service)):
                srv['host'] = conf.return_values('service {0} host-name'.format(service))

            if conf.exists('service {0} protocol'.format(service)):
                srv['protocol'] = conf.return_value('service {0} protocol'.format(service))

            if conf.exists('service {0} password'.format(service)):
                srv['password'] = conf.return_value('service {0} password'.format(service))

            if conf.exists('service {0} server'.format(service)):
                srv['server'] = conf.return_value('service {0} server'.format(service))

            node['service'].append(srv)

        # Additional settings in CLI
        if conf.exists('use-web skip'):
            node['web_skip'] = conf.return_value('use-web skip')

        if conf.exists('use-web url'):
            node['web_url'] = conf.return_value('use-web url')

        dyndns['interfaces'].append(node)

    return dyndns

def verify(dyndns):
    # bail out early - looks like removal from running config
    if dyndns is None:
        return None

    # A 'node' corresponds to an interface
    for node in dyndns['interfaces']:

        # RFC2136 - configuration validation
        for rfc2136 in node['rfc2136']:
            if not rfc2136['record']:
                raise ConfigError('Set key for service "{0}" to send DDNS updates for interface "{1}"'.format(rfc2136['name'], node['interface']))

            if not rfc2136['zone']:
                raise ConfigError('Set zone for service "{0}" to send DDNS updates for interface "{1}"'.format(rfc2136['name'], node['interface']))

            if not rfc2136['keyfile']:
                raise ConfigError('Set keyfile for service "{0}" to send DDNS updates for interface "{1}"'.format(rfc2136['name'], node['interface']))
            else:
                if not os.path.isfile(rfc2136['keyfile']):
                    raise ConfigError('Keyfile for service "{0}" to send DDNS updates for interface "{1}" does not exist'.format(rfc2136['name'], node['interface']))

            if not rfc2136['server']:
                raise ConfigError('Set server for service "{0}" to send DDNS updates for interface "{1}"'.format(rfc2136['name'], node['interface']))

        # DynDNS service provider - configuration validation
        for service in node['service']:
            if not service['host']:
                raise ConfigError('Set host-name for service "{0}" to send DDNS updates for interface "{1}"'.format(service['provider'], node['interface']))

            if not service['login']:
                raise ConfigError('Set login for service "{0}" to send DDNS updates for interface "{1}"'.format(service['provider'], node['interface']))

            if not service['password']:
                raise ConfigError('Set password for service "{0}" to send DDNS updates for interface "{1}"'.format(service['provider'], node['interface']))

            if service['custom'] is True:
                if not service['protocol']:
                    raise ConfigError('Set protocol for service "{0}" to send DDNS updates for interface "{1}"'.format(service['provider'], node['interface']))

                if not service['server']:
                    raise ConfigError('Set server for service "{0}" to send DDNS updates for interface "{1}"'.format(service['provider'], node['interface']))

    return None

def generate(dyndns):
    # bail out early - looks like removal from running config
    if dyndns is None:
        return None

    dirname = os.path.dirname(dyndns['pid_file'])
    if not os.path.exists(dirname):
        os.mkdir(dirname)

    dirname = os.path.dirname(config_file)
    if not os.path.exists(dirname):
        os.mkdir(dirname)

    tmpl = jinja2.Template(config_tmpl)
    config_text = tmpl.render(dyndns)
    with open(config_file, 'w') as f:
        f.write(config_text)

    return None

def apply(dyndns):
    if dyndns is None:
        os.system('/etc/init.d/ddclient stop')
        if os.path.exists(pid_file):
            os.unlink(pid_file)
        if os.path.exists(config_file):
            os.unlink(config_file)
        if os.path.exists(cache_file):
            os.unlink(cache_file)
    else:
        os.system('/etc/init.d/ddclient restart')

    return None

if __name__ == '__main__':
    try:
        c = get_config()
        verify(c)
        generate(c)
        apply(c)
    except ConfigError as e:
        print(e)
        sys.exit(1)
