#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import os
import os.path
import ssl
import subprocess
import sys
import threading
from collections import OrderedDict
from configparser import ConfigParser
from datetime import datetime
from signal import signal, SIGPIPE, SIG_DFL
from time import time, sleep, localtime, strftime

import paho.mqtt.client as mqtt
import requests
import sdnotify
from colorama import Fore, Style
from tzlocal import get_localzone
from unidecode import unidecode
from urllib3.exceptions import InsecureRequestWarning

apt_available = True
try:
    import apt
except ImportError:
    apt_available = False

# make sure this script is not run on Python 2.x
if sys.version_info[0] < 3:
    sys.stderr.write('Sorry, this script requires a python3 runtime environment.')
    sys.exit(1)

script_version = "1.8.5"
script_name = 'ISP-RPi-mqtt-daemon.py'
script_info = '{} v{}'.format(script_name, script_version)
project_name = 'RPi Reporter MQTT2HA Daemon'
project_url = 'https://github.com/ironsheep/RPi-Reporter-MQTT2HA-Daemon'

signal(SIGPIPE, SIG_DFL)

# turn off insecure connection warnings (our KZ0Q site has bad certs)
# REF: https://www.geeksforgeeks.org/how-to-disable-security-certificate-checks-for-requests-in-python/
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# we'll use this throughout
local_tz = get_localzone()

# Systemd Service Notifications - https://github.com/bb4242/sdnotify
sd_notifier = sdnotify.SystemdNotifier()

# TODO:
#  - add announcement of free-space and temperature endpoints

# Argparse
parser = argparse.ArgumentParser(
    description=project_name, epilog='For further details see: ' + project_url)
parser.add_argument("-v", "--verbose",
                    help="increase output verbosity", action="store_true")
parser.add_argument(
    "-d", "--debug", help="show debug output", action="store_true")
parser.add_argument(
    "-s", "--stall", help="TEST: report only the first time", action="store_true")
parser.add_argument("-c", '--config_dir',
                    help='set directory where config.ini is located', default=sys.path[0])
parse_args = parser.parse_args()

config_dir = parse_args.config_dir
opt_debug = parse_args.debug
opt_verbose = parse_args.verbose
opt_stall = parse_args.stall


def print_line(text, error=False, warning=False, info=False, verbose=False, debug=False, console=True, sd_notify=False):
    """Logging function"""
    timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
    if sd_notify:
        text = '* NOTIFY: {}'.format(text)
    if console:
        if error:
            print(Fore.RED + Style.BRIGHT + '[{}] '.format(
                timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL, file=sys.stderr)
        elif warning:
            print(Fore.YELLOW + '[{}] '.format(timestamp) +
                  Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
        elif info or verbose:
            if opt_verbose:
                print(Fore.GREEN + '[{}] '.format(timestamp) +
                      Fore.YELLOW + '- ' + '{}'.format(text) + Style.RESET_ALL)
        elif debug:
            if opt_debug:
                print(Fore.CYAN + '[{}] '.format(timestamp) +
                      '- (DBG): ' + '{}'.format(text) + Style.RESET_ALL)
        else:
            print(Fore.GREEN + '[{}] '.format(timestamp) +
                  Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)

    timestamp_sd = strftime('%b %d %H:%M:%S', localtime())
    if sd_notify:
        sd_notifier.notify(
            'STATUS={} - {}.'.format(timestamp_sd, unidecode(text)))


# Identifier cleanup
def clean_identifier(name):
    clean = name.strip()
    for this, that in [[' ', '-'], ['ä', 'ae'], ['Ä', 'Ae'], ['ö', 'oe'], ['Ö', 'Oe'], ['ü', 'ue'], ['Ü', 'Ue'],
                       ['ß', 'ss']]:
        clean = clean.replace(this, that)
    clean = unidecode(clean)
    return clean


print_line('--------------------------------------------------------------------', debug=True)
print_line(script_info, info=True)
if opt_verbose:
    print_line('Verbose enabled', info=True)
if opt_debug:
    print_line('Debug enabled', debug=True)
if opt_stall:
    print_line('TEST: Stall (no-re-reporting) enabled', debug=True)

# -----------------------------------------------------------------------------
#  MQTT handlers
# -----------------------------------------------------------------------------

# Eclipse Paho callbacks - http://www.eclipse.org/paho/clients/python/docs/#callbacks

mqtt_client_connected = False
print_line('* init mqtt_client_connected=[{}]'.format(mqtt_client_connected), debug=True)
mqtt_client_should_attempt_reconnect = True


def on_connect(client, userdata, flags, rc):
    global mqtt_client_connected
    if rc == 0:
        print_line('* MQTT connection established', console=True, sd_notify=True)
        print_line('')  # blank line?!

        # threading.Thread(target=afterMQTTConnect).start()

        mqtt_client_connected = True
        print_line('on_connect() mqtt_client_connected=[{}]'.format(mqtt_client_connected), debug=True)

        # -------------------------------------------------------------------------
        # Commands Subscription
        # -------------------------------------------------------------------------
        if len(commands) > 0:
            print_line('MQTT subscription to {}/+ enabled'.format(command_base_topic), console=True, sd_notify=True)
            mqtt_client.subscribe('{}/+'.format(command_base_topic))
        else:
            print_line('MQTT subscription to {}/+ disabled'.format(command_base_topic), console=True, sd_notify=True)

    else:
        print_line('! Connection error with result code {} - {}'.format(str(rc),
                                                                        mqtt.connack_string(rc)), error=True)
        print_line('MQTT Connection error with result code {} - {}'.format(str(rc),
                                                                           mqtt.connack_string(rc)), error=True,
                   sd_notify=True)
        # technically NOT useful but readying possible new shape...
        mqtt_client_connected = False
        print_line('on_connect() mqtt_client_connected=[{}]'.format(mqtt_client_connected), debug=True, error=True)
        # kill main thread
        sys.exit(1)


def on_disconnect(client, userdata, mid):
    global mqtt_client_connected
    mqtt_client_connected = False
    print_line('* MQTT connection lost', console=True, sd_notify=True)
    print_line('on_disconnect() mqtt_client_connected=[{}]'.format(mqtt_client_connected), debug=True)


def on_publish(client, userdata, mid):
    # ToDo(frennkie): Consider setting this back to "pass" as it was
    print_line('* Data successfully published.', debug=True)


# -----------------------------------------------------------------------------
# Commands - MQTT Subscription Callback
# -----------------------------------------------------------------------------
# Command catalog
def on_subscribe(client, userdata, mid, granted_qos):
    print_line('on_subscribe() - {} - {}'.format(str(mid), str(granted_qos)), debug=True, sd_notify=True)


shell_cmd_fspec = None


def on_message(client, userdata, message):
    global shell_cmd_fspec
    if not shell_cmd_fspec:
        shell_cmd_fspec = get_shell_cmd()
        if shell_cmd_fspec == '':
            print_line('* Failed to locate shell Command!', error=True)
            # kill main thread
            sys.exit(1)

    decoded_payload = message.payload.decode('utf-8')
    _command = message.topic.split('/')[-1]
    print_line('on_message() Topic=[{}] payload=[{}] _command=[{}]'.format(message.topic, message.payload, _command),
               console=True, sd_notify=True, debug=True)

    if _command != 'status':
        if _command in commands:
            print_line('- Command "{}" Received - Run {} {} -'.format(_command, commands[_command], decoded_payload),
                       console=True, debug=True)
            pHandle = subprocess.Popen([shell_cmd_fspec, "-c", commands[_command].format(decoded_payload)])
            output, errors = pHandle.communicate()
            if errors:
                print_line('- Command exec says: errors=[{}]'.format(errors), console=True, debug=True)
        else:
            print_line('* Invalid Command received.', error=True)


# -----------------------------------------------------------------------------
# Load configuration file
# -----------------------------------------------------------------------------
config = ConfigParser(delimiters=('=',), inline_comment_prefixes='#', interpolation=None)
config.optionxform = str
try:
    with open(os.path.join(config_dir, 'config.ini')) as config_file:
        config.read_file(config_file)
except IOError:
    print_line('No configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

daemon_enabled = config['Daemon'].getboolean('enabled', True)

# ToDo(frennkie): This (update_flag_filespec) is not used anywhere
# This script uses a flag file containing a date/timestamp of when the system was last updated
default_update_flag_filespec = '/home/pi/bin/lastupd.date'
update_flag_filespec = config['Daemon'].get('update_flag_filespec', default_update_flag_filespec)

default_base_topic = 'home/nodes'
base_topic = config['MQTT'].get('base_topic', default_base_topic).lower()

default_sensor_name = 'rpi-reporter'
sensor_name = config['MQTT'].get('sensor_name', default_sensor_name).lower()

# by default Home Assistant listens to the /homeassistant, but it can be changed for a given installation
default_discovery_prefix = 'homeassistant'
discovery_prefix = config['MQTT'].get('discovery_prefix', default_discovery_prefix).lower()

# report our RPi values every 5min
min_interval_in_minutes = 1
max_interval_in_minutes = 30
default_interval_in_minutes = 5
interval_in_minutes = config['Daemon'].getint('interval_in_minutes', default_interval_in_minutes)

# check our RPi pending-updates every 4 hours
min_check_interval_in_hours = 2
max_check_interval_in_hours = 24
default_check_interval_in_hours = 4
check_interval_in_hours = config['Daemon'].getint('check_updates_in_hours', default_check_interval_in_hours)

# default domain when hostname -f doesn't return it
default_domain = ''
fallback_domain = config['Daemon'].get('fallback_domain', default_domain).lower()

commands = OrderedDict([])
if config.has_section('Commands'):
    command_set = dict(config['Commands'].items())
    if len(command_set) > 0:
        commands.update(command_set)

# -----------------------------------------------------------------------------
#  Commands Subscription
# -----------------------------------------------------------------------------

# Check configuration
#
if (interval_in_minutes < min_interval_in_minutes) or (interval_in_minutes > max_interval_in_minutes):
    print_line('ERROR: Invalid "interval_in_minutes" found in configuration '
               'file: "config.ini"! Must be [{}-{}] Fix and try again... '
               'Aborting'.format(min_interval_in_minutes, max_interval_in_minutes),
               error=True, sd_notify=True)
    sys.exit(1)

if (check_interval_in_hours < min_check_interval_in_hours) or (check_interval_in_hours > max_check_interval_in_hours):
    print_line('ERROR: Invalid "check_updates_in_hours" found in configuration '
               'file: "config.ini"! Must be [{}-{}] Fix and try again... '
               'Aborting'.format(min_check_interval_in_hours, max_check_interval_in_hours),
               error=True, sd_notify=True)
    sys.exit(1)

# Ensure required values within sections of our config are present
if not config['MQTT']:
    print_line('ERROR: No MQTT settings found in configuration file "config.ini"! Fix and try again... Aborting',
               error=True, sd_notify=True)
    sys.exit(1)

print_line('Configuration accepted', console=False, sd_notify=True)

# -----------------------------------------------------------------------------
#  Daemon variables monitored
# -----------------------------------------------------------------------------

daemon_version_list = ['NOT-LOADED']
daemon_last_fetch_time = 0.0


def get_daemon_releases():
    # retrieve latest formal release versions list from repo
    global daemon_version_list
    global daemon_last_fetch_time

    new_version_list = []
    latestVersion = ''

    response = requests.request('GET', 'http://kz0q.com/daemon-releases', verify=False)
    if response.status_code != 200:
        print_line('- get_daemon_releases() RQST status=({})'.format(response.status_code), error=True)
        daemon_version_list = ['NOT-LOADED']  # mark as NOT fetched
    else:
        content = response.text
        lines = content.split('\n')
        for line in lines:
            if len(line) > 0:
                # print_line('- RLS Line=[{}]'.format(line), debug=True)
                line_parts = line.split(' ')
                # print_line('- RLS line_parts=[{}]'.format(line_parts), debug=True)
                if len(line_parts) >= 2:
                    curr_version = line_parts[0]
                    rls_type = line_parts[1]
                    if curr_version not in new_version_list:
                        if 'latest' not in rls_type.lower():
                            new_version_list.append(curr_version)  # append to list
                        else:
                            latestVersion = curr_version

        if len(new_version_list) > 1:
            new_version_list.sort()
        if len(latestVersion) > 0:
            if latestVersion not in new_version_list:
                new_version_list.insert(0, latestVersion)  # append to list

        daemon_version_list = new_version_list
        print_line('- RQST daemon_version_list=({})'.format(daemon_version_list), debug=True)
        daemon_last_fetch_time = time()  # record when we last fetched the versions


get_daemon_releases()  # and load them!
print_line('* daemon_last_fetch_time=({})'.format(daemon_last_fetch_time), debug=True)

# -----------------------------------------------------------------------------
#  RPi variables monitored
# -----------------------------------------------------------------------------

rpi_mac = ''
rpi_model_raw = ''
rpi_model = ''
rpi_connections = ''
rpi_hostname = ''
rpi_fqdn = ''
rpi_linux_release = ''
rpi_linux_version = ''
rpi_uptime_raw = ''
rpi_uptime = ''
rpi_uptime_sec = 0
rpi_last_update_date = datetime.min
# rpi_last_update_date_v2 = datetime.min
rpi_filesystem_space_raw = ''
rpi_filesystem_space = ''
rpi_filesystem_percent = ''
rpi_system_temp = ''
rpi_gpu_temp = ''
rpi_cpu_temp = ''
rpi_mqtt_script = script_info
rpi_interfaces = []
rpi_filesystem = []
# Tuple (Total, Free, Avail., Swap Total, Swap Free)
rpi_memory_tuple = ()
# Tuple (Hardware, Model Name, NbrCores, BogoMIPS, Serial)
rpi_cpu_tuple = ()
# for thermal status reporting
rpi_throttle_status = []
# new cpu loads
rpi_cpuload1 = ''
rpi_cpuload5 = ''
rpi_cpuload15 = ''
rpi_update_count = 0

if not apt_available:
    rpi_update_count = -1  # if packaging system not avail. report -1

# Time for network transfer calculation
previous_time = time()


# -----------------------------------------------------------------------------
#  monitor variable fetch routines
# -----------------------------------------------------------------------------

def get_device_cpu_info():
    global rpi_cpu_tuple
    #  cat /proc/cpuinfo | /bin/egrep -i "processor|model|bogo|hardware|serial"
    # MULTI-CORE
    #  processor	: 0
    #  model name	: ARMv7 Processor rev 4 (v7l)
    #  BogoMIPS	: 38.40
    #  processor	: 1
    #  model name	: ARMv7 Processor rev 4 (v7l)
    #  BogoMIPS	: 38.40
    #  processor	: 2
    #  model name	: ARMv7 Processor rev 4 (v7l)
    #  BogoMIPS	: 38.40
    #  processor	: 3
    #  model name	: ARMv7 Processor rev 4 (v7l)
    #  BogoMIPS	: 38.40
    #  Hardware	: BCM2835
    #  Serial		: 00000000a8d11642
    #
    # SINGLE CORE
    #  processor	: 0
    #  model name	: ARMv6-compatible processor rev 7 (v6l)
    #  BogoMIPS	: 697.95
    #  Hardware	: BCM2835
    #  Serial		: 00000000131030c0
    #  Model		: Raspberry Pi Zero W Rev 1.1
    cmd_string = '/bin/cat /proc/cpuinfo | /bin/egrep -i "processor|model|bogo|hardware|serial"'
    out = subprocess.Popen(cmd_string,
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    lines = stdout.decode('utf-8').split("\n")
    trimmed_lines = []
    for curr_line in lines:
        trimmed_line = curr_line.lstrip().rstrip()
        trimmed_lines.append(trimmed_line)
    cpu_hardware = ''  # 'hardware'
    cpu_cores = 0  # count of 'processor' lines
    _cpu_model = ''  # 'model name'
    cpu_bogoMIPS = 0.0  # sum of 'BogoMIPS' lines
    cpu_serial = ''  # 'serial'
    for curr_line in trimmed_lines:
        lineParts = curr_line.split(':')
        currValue = '{?unk?}'
        if len(lineParts) >= 2:
            currValue = lineParts[1].lstrip().rstrip()
        if 'Hardware' in curr_line:
            cpu_hardware = currValue
        if 'model name' in curr_line:
            _cpu_model = currValue
        if 'BogoMIPS' in curr_line:
            cpu_bogoMIPS += float(currValue)
        if 'processor' in curr_line:
            cpu_cores += 1
        if 'Serial' in curr_line:
            cpu_serial = currValue

    out = subprocess.Popen("/bin/cat /proc/loadavg",
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    cpu_loads_raw = stdout.decode('utf-8').split()
    print_line('cpu_loads_raw=[{}]'.format(cpu_loads_raw), debug=True)
    cpu_load1 = round(float(float(cpu_loads_raw[0]) / int(cpu_cores) * 100), 1)
    cpu_load5 = round(float(float(cpu_loads_raw[1]) / int(cpu_cores) * 100), 1)
    cpu_load15 = round(float(float(cpu_loads_raw[2]) / int(cpu_cores) * 100), 1)

    # Tuple (Hardware, Model Name, NbrCores, BogoMIPS, Serial)
    rpi_cpu_tuple = (cpu_hardware, _cpu_model, cpu_cores,
                     cpu_bogoMIPS, cpu_serial, cpu_load1, cpu_load5, cpu_load15)
    print_line('rpi_cpu_tuple=[{}]'.format(rpi_cpu_tuple), debug=True)


def get_device_memory():
    global rpi_memory_tuple
    #  $ cat /proc/meminfo | /bin/egrep -i "mem[TFA]"
    #  MemTotal:         948304 kB
    #  MemFree:           40632 kB
    #  MemAvailable:     513332 kB
    out = subprocess.Popen("cat /proc/meminfo",
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    lines = stdout.decode('utf-8').split("\n")
    trimmed_lines = []
    for curr_line in lines:
        trimmed_line = curr_line.lstrip().rstrip()
        trimmed_lines.append(trimmed_line)
    mem_total = ''
    mem_free = ''
    mem_avail = ''
    swap_total = ''
    swap_free = ''
    for curr_line in trimmed_lines:
        line_parts = curr_line.split()
        if 'MemTotal' in curr_line:
            mem_total = float(line_parts[1]) / 1024
        if 'MemFree' in curr_line:
            mem_free = float(line_parts[1]) / 1024
        if 'MemAvail' in curr_line:
            mem_avail = float(line_parts[1]) / 1024
        if 'SwapTotal' in curr_line:
            swap_total = float(line_parts[1]) / 1024
        if 'SwapFree' in curr_line:
            swap_free = float(line_parts[1]) / 1024

    # Tuple (Total, Free, Avail., Swap Total, Swap Free)
    rpi_memory_tuple = (mem_total, mem_free, mem_avail, swap_total,
                        swap_free)  # [0]=total, [1]=free, [2]=avail., [3]=swap total, [4]=swap free
    print_line('rpi_memory_tuple=[{}]'.format(rpi_memory_tuple), debug=True)


def get_device_model():
    global rpi_model
    global rpi_model_raw
    global rpi_connections
    cmd_string = '/bin/cat /proc/device-tree/model | /bin/sed -e "s/\\x0//g"'
    out = subprocess.Popen(cmd_string,
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    rpi_model_raw = stdout.decode('utf-8')
    # now reduce string length (just more compact, same info)
    rpi_model = rpi_model_raw.replace('Raspberry ', 'R').replace(
        'i Model ', 'i 1 Model').replace('Rev ', 'r').replace(' Plus ', '+')

    # now decode interfaces
    rpi_connections = 'e,w,b'  # default
    if 'Pi 3 ' in rpi_model:
        if ' A ' in rpi_model:
            rpi_connections = 'w,b'
        else:
            rpi_connections = 'e,w,b'
    elif 'Pi 2 ' in rpi_model:
        rpi_connections = 'e'
    elif 'Pi 1 ' in rpi_model:
        if ' A ' in rpi_model:
            rpi_connections = ''
        else:
            rpi_connections = 'e'

    print_line('rpi_model_raw=[{}]'.format(rpi_model_raw), debug=True)
    print_line('rpi_model=[{}]'.format(rpi_model), debug=True)
    print_line('rpi_connections=[{}]'.format(rpi_connections), debug=True)


def get_linux_release():
    global rpi_linux_release
    cmd_string = ('/bin/cat /etc/apt/sources.list | /bin/egrep -v "#" | /usr/bin/awk \'{ print $3 }\' | '
                  '/bin/sed -e "s/-/ /g" | /usr/bin/cut -f1 -d" " | /bin/grep . | /usr/bin/sort -u')
    out = subprocess.Popen(cmd_string,
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    rpi_linux_release = stdout.decode('utf-8').rstrip()
    print_line('rpi_linux_release=[{}]'.format(rpi_linux_release), debug=True)


def get_linux_version():
    global rpi_linux_version
    out = subprocess.Popen("/bin/uname -r",
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    rpi_linux_version = stdout.decode('utf-8').rstrip()
    print_line('rpi_linux_version=[{}]'.format(rpi_linux_version), debug=True)


def get_hostnames():
    global rpi_hostname
    global rpi_fqdn
    out = subprocess.Popen("/bin/hostname -f",
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    fqdn_raw = stdout.decode('utf-8').rstrip()
    print_line('fqdn_raw=[{}]'.format(fqdn_raw), debug=True)
    rpi_hostname = fqdn_raw
    if '.' in fqdn_raw:
        # have good fqdn
        nameParts = fqdn_raw.split('.')
        rpi_fqdn = fqdn_raw
        rpi_hostname = nameParts[0]
    else:
        # missing domain, if we have a fallback apply it
        if len(fallback_domain) > 0:
            rpi_fqdn = '{}.{}'.format(fqdn_raw, fallback_domain)
        else:
            rpi_fqdn = rpi_hostname

    print_line('rpi_fqdn=[{}]'.format(rpi_fqdn), debug=True)
    print_line('rpi_hostname=[{}]'.format(rpi_hostname), debug=True)


def get_uptime():
    global rpi_uptime_raw
    global rpi_uptime
    global rpi_uptime_sec
    out = subprocess.Popen("/usr/bin/uptime",
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    rpi_uptime_raw = stdout.decode('utf-8').rstrip().lstrip()
    print_line('rpi_uptime_raw=[{}]'.format(rpi_uptime_raw), debug=True)
    basicParts = rpi_uptime_raw.split()
    timeStamp = basicParts[0]
    lineParts = rpi_uptime_raw.split(',')
    if 'user' in lineParts[1]:
        rpi_uptime_raw = lineParts[0]
    else:
        rpi_uptime_raw = '{}, {}'.format(lineParts[0], lineParts[1])
    rpi_uptime = rpi_uptime_raw.replace(
        timeStamp, '').lstrip().replace('up ', '')
    print_line('rpi_uptime=[{}]'.format(rpi_uptime), debug=True)
    # Ex: 10 days, 23:57
    # Ex: 27 days, 27 min
    # Ex: 0 min

    # b_has_colon = (':' in rpi_uptime)  # is not used
    uptime_parts = rpi_uptime.split(',')
    print_line('- uptime_parts=[{}]'.format(uptime_parts), debug=True)
    if len(uptime_parts) > 1:
        # have days and time
        day_parts = uptime_parts[0].strip().split(' ')
        days_val = int(day_parts[0])
        time_str = uptime_parts[1].strip()
    else:
        # have time only
        days_val = 0
        time_str = uptime_parts[0].strip()
    print_line('- days=({}), time_str=[{}]'.format(days_val, time_str), debug=True)
    if ':' in time_str:
        # time_str = '23:57'
        time_parts = time_str.split(':')
        hours_val = int(time_parts[0])
        mins_val = int(time_parts[1])
    else:
        # time_str = 27 of: '27 min'
        hours_val = 0
        time_parts = time_str.split(' ')
        mins_val = int(time_parts[0])
    print_line('- hours_val=({}), minsVal=({})'.format(hours_val, mins_val), debug=True)
    rpi_uptime_sec = (mins_val * 60) + (hours_val * 60 * 60) + (days_val * 24 * 60 * 60)
    print_line('rpi_uptime_sec=({})'.format(rpi_uptime_sec), debug=True)


def get_network_ifs_using_ip(ip_cmd):
    cmd_str = '{} link show | /bin/egrep -v "link" | /bin/egrep " eth| wlan"'.format(ip_cmd)
    out = subprocess.Popen(cmd_str,
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    lines = stdout.decode('utf-8').split("\n")
    interface_names = []
    line_count = len(lines)
    if line_count > 2:
        line_count = 2
    if line_count == 0:
        print_line('ERROR no lines left by ip(8) filter!', error=True)
        sys.exit(1)

    for line_idx in range(line_count):
        trimmed_line = lines[line_idx].lstrip().rstrip()
        if len(trimmed_line) > 0:
            line_parts = trimmed_line.split()
            interface_name = line_parts[1].replace(':', '')
            # if interface is within a  container then we have eth0@if77
            interface_names.append(interface_name)

    print_line('interface_names=[{}]'.format(interface_names), debug=True)

    trimmed_lines = []
    for interface in interface_names:
        lines = get_single_interface_details(interface)
        for curr_line in lines:
            trimmed_lines.append(curr_line)

    load_network_if_details_from_lines(trimmed_lines)


def get_single_interface_details(interface_name):
    cmd_string = '/sbin/ifconfig {} | /bin/egrep "Link|flags|inet |ether |TX packets |RX packets "'.format(
        interface_name)
    out = subprocess.Popen(cmd_string,
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    lines = stdout.decode('utf-8').split("\n")
    trimmed_lines = []
    for curr_line in lines:
        trimmed_line = curr_line.lstrip().rstrip()
        if len(trimmed_line) > 0:
            trimmed_lines.append(trimmed_line)

    # print_line('interface:[{}] trimmed_lines=[{}]'.format(interfaceName, trimmed_lines), debug=True)
    return trimmed_lines


def load_network_if_details_from_lines(if_config_lines):
    global rpi_interfaces
    global rpi_mac
    global previous_time
    #
    # OLDER SYSTEMS
    #  eth0      Link encap:Ethernet  HWaddr b8:27:eb:c8:81:f2
    #    inet addr:192.168.100.41  Bcast:192.168.100.255  Mask:255.255.255.0
    #  wlan0     Link encap:Ethernet  HWaddr 00:0f:60:03:e6:dd
    # NEWER SYSTEMS
    #  The following means eth0 (wired is NOT connected, and WiFi is connected)
    #  eth0: flags=4099<UP,BROADCAST,MULTICAST>  mtu 1500
    #    ether b8:27:eb:1a:f3:bc  txqueuelen 1000  (Ethernet)
    #    RX packets 0  bytes 0 (0.0 B)
    #    TX packets 0  bytes 0 (0.0 B)
    #  wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
    #    inet 192.168.100.189  netmask 255.255.255.0  broadcast 192.168.100.255
    #    ether b8:27:eb:4f:a6:e9  txqueuelen 1000  (Ethernet)
    #    RX packets 1358790  bytes 1197368205 (1.1 GiB)
    #    TX packets 916361  bytes 150440804 (143.4 MiB)
    #
    tmp_interfaces = []
    have_if = False
    imterfc = ''
    rpi_mac = ''
    current_time = time()
    if current_time == previous_time:
        current_time += 1

    for curr_line in if_config_lines:
        line_parts = curr_line.split()
        # print_line('- curr_line=[{}]'.format(curr_line), debug=True)
        # print_line('- line_parts=[{}]'.format(line_parts), debug=True)
        if len(line_parts) > 0:
            # skip interfaces generated by Home Assistant on RPi
            if 'docker' in curr_line or 'veth' in curr_line or 'hassio' in curr_line:
                have_if = False
                continue
            # let's evaluate remaining interfaces
            if 'flags' in curr_line:  # NEWER ONLY
                have_if = True
                imterfc = line_parts[0].replace(':', '')
                # print_line('newIF=[{}]'.format(imterfc), debug=True)
            elif 'Link' in curr_line:  # OLDER ONLY
                have_if = True
                imterfc = line_parts[0].replace(':', '')
                new_tuple = (imterfc, 'mac', line_parts[4])
                if rpi_mac == '':
                    rpi_mac = line_parts[4]
                    print_line('rpi_mac=[{}]'.format(rpi_mac), debug=True)
                tmp_interfaces.append(new_tuple)
                print_line('new_tuple=[{}]'.format(new_tuple), debug=True)
            elif have_if:
                print_line('IF=[{}], line_parts=[{}]'.format(
                    imterfc, line_parts), debug=True)
                if 'inet' in curr_line:  # OLDER & NEWER
                    new_tuple = (imterfc, 'IP',
                                 line_parts[1].replace('addr:', ''))
                    tmp_interfaces.append(new_tuple)
                    print_line('new_tuple=[{}]'.format(new_tuple), debug=True)
                elif 'ether' in curr_line:  # NEWER ONLY
                    new_tuple = (imterfc, 'mac', line_parts[1])
                    tmp_interfaces.append(new_tuple)
                    if rpi_mac == '':
                        rpi_mac = line_parts[1]
                        print_line('rpi_mac=[{}]'.format(rpi_mac), debug=True)
                    print_line('new_tuple=[{}]'.format(new_tuple), debug=True)
                elif 'RX' in curr_line:  # NEWER ONLY
                    previous_value = get_previous_network_data(imterfc, 'rx_data')
                    current_value = int(line_parts[4])
                    rx_data = round((current_value - previous_value) / (current_time - previous_time) * 8 / 1024)
                    new_tuple = (imterfc, 'rx_data', rx_data)
                    tmp_interfaces.append(new_tuple)
                    print_line('new_tuple=[{}]'.format(new_tuple), debug=True)
                elif 'TX' in curr_line:  # NEWER ONLY
                    previous_value = get_previous_network_data(imterfc, 'tx_data')
                    current_value = int(line_parts[4])
                    tx_data = round((current_value - previous_value) / (current_time - previous_time) * 8 / 1024)
                    new_tuple = (imterfc, 'tx_data', tx_data)
                    tmp_interfaces.append(new_tuple)
                    print_line('new_tuple=[{}]'.format(new_tuple), debug=True)
                    have_if = False

    rpi_interfaces = tmp_interfaces
    print_line('rpi_interfaces=[{}]'.format(rpi_interfaces), debug=True)
    print_line('rpi_mac=[{}]'.format(rpi_mac), debug=True)


def get_previous_network_data(interface, field):
    global rpi_interfaces
    value = [item for item in rpi_interfaces if item[0] == interface and item[1] == field]
    if len(value) > 0:
        return value[0][2]
    else:
        return 0


def get_network_ifs():
    ip_cmd = get_ip_cmd()
    if ip_cmd:
        get_network_ifs_using_ip(ip_cmd)
    else:
        cmd_string = ('/sbin/ifconfig | /bin/egrep "Link|flags|inet |ether " | '
                      '/bin/egrep -v -i "lo:|loopback|inet6|\:\:1|127\.0\.0\.1"')
        out = subprocess.Popen(cmd_string,
                               shell=True,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
        stdout, _ = out.communicate()
        lines = stdout.decode('utf-8').split("\n")
        trimmed_lines = []
        for curr_line in lines:
            trimmed_line = curr_line.lstrip().rstrip()
            if len(trimmed_line) > 0:
                trimmed_lines.append(trimmed_line)

        print_line('trimmed_lines=[{}]'.format(trimmed_lines), debug=True)

        load_network_if_details_from_lines(trimmed_lines)


def get_file_system_drives():
    global rpi_filesystem_space_raw
    global rpi_filesystem_space
    global rpi_filesystem_percent
    global rpi_filesystem
    out = subprocess.Popen("/bin/df -m | /usr/bin/tail -n +2 | /bin/egrep -v 'tmpfs|boot'",
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    lines = stdout.decode('utf-8').split("\n")
    trimmed_lines = []
    for curr_line in lines:
        trimmed_line = curr_line.lstrip().rstrip()
        if len(trimmed_line) > 0:
            trimmed_lines.append(trimmed_line)

    print_line('get_file_system_drives() trimmed_lines=[{}]'.format(trimmed_lines), debug=True)

    #  EXAMPLES
    #
    #  Filesystem     1M-blocks  Used Available Use% Mounted on
    #  /dev/root          59998   9290     48208  17% /
    #  /dev/sda1         937872 177420    712743  20% /media/data
    # or
    #  /dev/root          59647  3328     53847   6% /
    #  /dev/sda1           3703    25      3472   1% /media/pi/SANDISK
    # or
    #  xxx.xxx.xxx.xxx:/srv/c2db7b94 200561 148655 41651 79% /

    # FAILING Case v1.4.0:
    # Here is the output of 'df -m'

    # Sys. de fichiers blocs de 1M Utilisé Disponible Uti% Monté sur
    # /dev/root 119774 41519 73358 37% /
    # devtmpfs 1570 0 1570 0% /dev
    # tmpfs 1699 0 1699 0% /dev/shm
    # tmpfs 1699 33 1667 2% /run
    # tmpfs 5 1 5 1% /run/lock
    # tmpfs 1699 0 1699 0% /sys/fs/cgroup
    # /dev/mmcblk0p1 253 55 198 22% /boot
    # tmpfs 340 0 340 0% /run/user/1000

    # FAILING Case v1.6.x (issue #61)
    # [[/bin/df: /mnt/sabrent: No such device or address',
    #   '/dev/root         119756  19503     95346  17% /',
    #   '/dev/sda1         953868 882178     71690  93% /media/usb0',
    #   '/dev/sdb1         976761  93684    883078  10% /media/pi/SSD']]

    tmp_drives = []
    for curr_line in trimmed_lines:
        if 'no such device' in curr_line.lower():
            print_line('BAD LINE FORMAT, Skipped=[{}]'.format(curr_line), debug=True, warning=True)
            continue
        line_parts = curr_line.split()
        print_line('line_parts({})=[{}]'.format(len(line_parts), line_parts), debug=True)
        if len(line_parts) < 6:
            print_line('BAD LINE FORMAT, Skipped=[{}]'.format(line_parts), debug=True, warning=True)
            continue
        # tuple { total blocks, used%, mountPoint, device }
        #
        # new mech:
        #  Filesystem     1M-blocks  Used Available Use% Mounted on
        #     [0]           [1]       [2]     [3]    [4]   [5]
        #     [--]         [n-3]     [n-2]   [n-1]   [n]   [--]
        #  where  percent_field_index  is 'n'
        #

        # locate our % used field...
        percent_field_index = 0
        for percent_field_index in range(len(line_parts) - 2, 1, -1):
            if '%' in line_parts[percent_field_index]:
                break
        print_line('percent_field_index=[{}]'.format(percent_field_index), debug=True)

        total_size_idx = percent_field_index - 3
        mount_idx = percent_field_index + 1

        # do we have a two part device name?
        device = line_parts[0]
        if total_size_idx != 1:
            device = '{} {}'.format(line_parts[0], line_parts[1])
        print_line('device=[{}]'.format(device), debug=True)

        # do we have a two part mount point?
        mount_point = line_parts[mount_idx]
        if len(line_parts) - 1 > mount_idx:
            mount_point = '{} {}'.format(
                line_parts[mount_idx], line_parts[mount_idx + 1])
        print_line('mount_point=[{}]'.format(mount_point), debug=True)

        total_size_in_gb = '{:.0f}'.format(
            next_power_of_2(line_parts[total_size_idx]))
        new_tuple = (total_size_in_gb, line_parts[percent_field_index].replace(
            '%', ''), mount_point, device)
        tmp_drives.append(new_tuple)
        print_line('new_tuple=[{}]'.format(new_tuple), debug=True)
        if new_tuple[2] == '/':
            rpi_filesystem_space_raw = curr_line
            rpi_filesystem_space = new_tuple[0]
            rpi_filesystem_percent = new_tuple[1]
            print_line('rpi_filesystem_space=[{}GB]'.format(new_tuple[0]), debug=True)
            print_line('rpi_filesystem_percent=[{}]'.format(new_tuple[1]), debug=True)

    rpi_filesystem = tmp_drives
    print_line('rpi_filesystem=[{}]'.format(rpi_filesystem), debug=True)


def next_power_of_2(size):
    size_as_nbr = int(size) - 1
    return 1 if size == 0 else (1 << size_as_nbr.bit_length()) / 1024


def get_vc_gen_cmd():
    cmd_locn1 = '/usr/bin/vcgencmd'
    cmd_locn2 = '/opt/vc/bin/vcgencmd'
    desired_command = None
    if os.path.exists(cmd_locn1):
        desired_command = cmd_locn1
    elif os.path.exists(cmd_locn2):
        desired_command = cmd_locn2
    else:
        print_line('ERROR: vcgencmd(8) not found!', error=True)

    if desired_command:
        print_line('Found vcgencmd(8)=[{}]'.format(desired_command), debug=True)
    else:
        pass  # ToDo: maybe exit?
    return desired_command


def get_shell_cmd():
    cmd_locn1 = '/usr/bin/sh'
    cmd_locn2 = '/bin/sh'
    desired_command = None
    if os.path.exists(cmd_locn1):
        desired_command = cmd_locn1
    elif os.path.exists(cmd_locn2):
        desired_command = cmd_locn2
    else:
        print_line('ERROR: sh(1) not found!', error=True)

    if desired_command:
        print_line('Found sh(1)=[{}]'.format(desired_command), debug=True)
    else:
        pass  # ToDo: maybe exit?
    return desired_command


def get_ip_cmd():
    cmd_locn1 = '/bin/ip'
    cmd_locn2 = '/sbin/ip'
    desired_command = None
    if os.path.exists(cmd_locn1):
        desired_command = cmd_locn1
    elif os.path.exists(cmd_locn2):
        desired_command = cmd_locn2
    else:
        print_line('ERROR: ip(8) not found!', error=True)

    if desired_command:
        print_line('Found ip(8)=[{}]'.format(desired_command), debug=True)
    else:
        pass  # ToDo: maybe exit?
    return desired_command


def get_system_temperature():
    global rpi_system_temp
    global rpi_gpu_temp
    global rpi_cpu_temp
    rpi_gpu_temp_raw = 'failed'

    cmd_fspec = get_vc_gen_cmd()
    if cmd_fspec and os.access("/dev/vcio", os.R_OK):
        retry_count = 3
        while retry_count > 0 and 'failed' in rpi_gpu_temp_raw:
            cmd_string = "{} measure_temp | /bin/sed -e 's/\\x0//g'".format(cmd_fspec)
            out = subprocess.Popen(cmd_string,
                                   shell=True,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
            stdout, _ = out.communicate()
            rpi_gpu_temp_raw = stdout.decode(
                'utf-8').rstrip().replace('temp=', '').replace('\'C', '')
            retry_count -= 1
            sleep(1)

        if 'failed' in rpi_gpu_temp_raw:
            interpreted_temp = float('-1.0')
        else:
            interpreted_temp = float(rpi_gpu_temp_raw)
        rpi_gpu_temp = interpreted_temp
        print_line('rpi_gpu_temp=[{}]'.format(rpi_gpu_temp), debug=True)

        rpi_cpu_temp = get_system_cpu_temperature()

        # fallback to CPU temp if is GPU not available
        rpi_system_temp = rpi_gpu_temp
        if rpi_gpu_temp == -1.0:
            rpi_system_temp = rpi_cpu_temp

    else:
        # fallback to CPU temp if is GPU not available
        print_line('- (WARN): GPU temp not available - falling back to CPU'.format(rpi_gpu_temp), warning=True)
        rpi_system_temp = float('-1.0')
        rpi_gpu_temp = float('-1.0')
        rpi_cpu_temp = get_system_cpu_temperature()
        if rpi_cpu_temp != -1.0:
            rpi_system_temp = rpi_cpu_temp


def get_system_cpu_temperature():
    cmd_locn1 = '/sys/class/thermal/thermal_zone0/temp'
    cmd_string = '/bin/cat {}'.format(cmd_locn1)
    if not os.path.exists(cmd_locn1):
        _rpi_cpu_temp = float('-1.0')
    else:
        out = subprocess.Popen(cmd_string,
                               shell=True,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
        stdout, _ = out.communicate()
        rpi_cpu_temp_raw = stdout.decode('utf-8').rstrip()
        _rpi_cpu_temp = float(rpi_cpu_temp_raw) / 1000.0
    print_line('_rpi_cpu_temp=[{}]'.format(_rpi_cpu_temp), debug=True)
    return _rpi_cpu_temp


def get_system_thermal_status():
    global rpi_throttle_status
    # sudo vcgencmd get_throttled
    #   throttled=0x0
    #
    #  REF: https://harlemsquirrel.github.io/shell/2019/01/05/monitoring-raspberry-pi-power-and-thermal-issues.html
    #
    rpi_throttle_status = []
    cmd_fspec = get_vc_gen_cmd()
    if cmd_fspec == '':
        rpi_throttle_status.append('Not Available')
    else:
        cmd_string = "{} get_throttled".format(cmd_fspec)
        out = subprocess.Popen(cmd_string,
                               shell=True,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
        stdout, _ = out.communicate()
        rpi_throttle_status_raw = stdout.decode('utf-8').rstrip()
        print_line('rpi_throttle_status_raw=[{}]'.format(rpi_throttle_status_raw), debug=True)

        if 'throttled' not in rpi_throttle_status_raw:
            rpi_throttle_status.append('bad response [{}] from vcgencmd'.format(rpi_throttle_status_raw))
        else:
            values = []
            line_parts = rpi_throttle_status_raw.split('=')
            print_line('line_parts=[{}]'.format(line_parts), debug=True)
            rpi_throttle_value_raw = ''
            if len(line_parts) > 1:
                rpi_throttle_value_raw = line_parts[1]
            if len(rpi_throttle_value_raw) > 0:
                values.append('throttled = {}'.format(rpi_throttle_value_raw))
                if rpi_throttle_value_raw.startswith('0x'):
                    rpi_throttle_value = int(rpi_throttle_value_raw, 16)
                else:
                    rpi_throttle_value = int(rpi_throttle_value_raw, 10)
                # decode test code
                # rpi_throttle_value = int('0x50002', 16)
                if rpi_throttle_value > 0:
                    values = interpret_throttle_value(rpi_throttle_value)
                else:
                    values.append('Not throttled')
            if len(values) > 0:
                rpi_throttle_status = values

    print_line('rpi_throttle_status=[{}]'.format(rpi_throttle_status), debug=True)


def interpret_throttle_value(throttle_value):
    """
    01110000000000000010
    ||||            ||||_ Under-voltage detected
    ||||            |||_ Arm frequency capped
    ||||            ||_ Currently throttled
    ||||            |_ Soft temperature limit active
    ||||_ Under-voltage has occurred since last reboot
    |||_ Arm frequency capped has occurred
    ||_ Throttling has occurred
    |_ Soft temperature limit has occurred
    """
    print_line('throttleValue=[{}]'.format(bin(throttle_value)), debug=True)
    interp_result = []
    meanings = [
        (2 ** 0, 'Under-voltage detected'),
        (2 ** 1, 'Arm frequency capped'),
        (2 ** 2, 'Currently throttled'),
        (2 ** 3, 'Soft temperature limit active'),
        (2 ** 16, 'Under-voltage has occurred'),
        (2 ** 17, 'Arm frequency capped has occurred'),
        (2 ** 18, 'Throttling has occurred'),
        (2 ** 19, 'Soft temperature limit has occurred'),
    ]

    for meaning_index in range(len(meanings)):
        bit_tuple = meanings[meaning_index]
        if throttle_value & bit_tuple[0] > 0:
            interp_result.append(bit_tuple[1])

    print_line('interp_result=[{}]'.format(interp_result), debug=True)
    return interp_result


def get_last_update_date():
    global rpi_last_update_date
    # apt-get update writes to following dir (so date changes on update)
    apt_listdir_filespec = '/var/lib/apt/lists/partial'
    # apt-get dist-upgrade | autoremove update the following file when actions are taken
    apt_lockdir_filespec = '/var/lib/dpkg/lock'
    cmd_string = '/bin/ls -ltrd {} {}'.format(apt_listdir_filespec, apt_lockdir_filespec)
    out = subprocess.Popen(cmd_string,
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    lines = stdout.decode('utf-8').split("\n")
    trimmed_lines = []
    for curr_line in lines:
        trimmed_line = curr_line.lstrip().rstrip()
        if len(trimmed_line) > 0:
            trimmed_lines.append(trimmed_line)
    print_line('trimmed_lines=[{}]'.format(trimmed_lines), debug=True)

    file_spec_latest = ''
    if len(trimmed_lines) > 0:
        last_line_idx = len(trimmed_lines) - 1
        line_parts = trimmed_lines[last_line_idx].split()
        if len(line_parts) > 0:
            lastPartIdx = len(line_parts) - 1
            file_spec_latest = line_parts[lastPartIdx]
    print_line('file_spec_latest=[{}]'.format(file_spec_latest), debug=True)

    file_mod_date_in_seconds = os.path.getmtime(file_spec_latest)
    file_mod_date = datetime.fromtimestamp(file_mod_date_in_seconds)
    rpi_last_update_date = file_mod_date.replace(tzinfo=local_tz)
    print_line('rpi_last_update_date=[{}]'.format(
        rpi_last_update_date), debug=True)


def get_last_install_date():
    global rpi_last_update_date
    # apt_log_filespec = '/var/log/dpkg.log'
    # apt_log_filespec2 = '/var/log/dpkg.log.1'
    cmd_string = ("/bin/grep --binary-files=text 'status installed' /var/log/dpkg.log "
                  "/var/log/dpkg.log.1 2>/dev/null | sort | tail -1")
    out = subprocess.Popen(cmd_string,
                           shell=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    last_installed_pkg_raw = stdout.decode(
        'utf-8').rstrip().replace('/var/log/dpkg.log:', '').replace('/var/log/dpkg.log.1:', '')
    print_line('last_installed_pkg_raw=[{}]'.format(last_installed_pkg_raw), debug=True)
    line_parts = last_installed_pkg_raw.split()
    if len(line_parts) > 1:
        pkg_date_string = '{} {}'.format(line_parts[0], line_parts[1])
        print_line('pkg_date_string=[{}]'.format(pkg_date_string), debug=True)
        # Example:
        #   2020-07-22 17:08:26 status installed python3-tzlocal:all 1.3-1

        pkg_install_date = datetime.strptime(
            pkg_date_string, '%Y-%m-%d %H:%M:%S').replace(tzinfo=local_tz)
        rpi_last_update_date = pkg_install_date

    print_line('rpi_last_update_date=[{}]'.format(rpi_last_update_date), debug=True)


update_last_fetch_time = 0.0


def get_number_of_available_updates():
    global rpi_update_count
    global update_last_fetch_time
    if apt_available:
        cache = apt.Cache()
        cache.open(None)
        cache.upgrade()
        changes = cache.get_changes()
        print_line('APT changes=[{}]'.format(changes), debug=True)
        print_line('APT Avail Updates: ({})'.format(len(changes)), info=True)
        # return str(cache.get_changes().len())
        rpi_update_count = len(changes)
        update_last_fetch_time = time()


# get our hostnames so we can set up MQTT
get_hostnames()
if sensor_name == default_sensor_name:
    sensor_name = 'rpi-{}'.format(rpi_hostname)
# get model so we can use it too in MQTT
get_device_model()
get_device_cpu_info()
get_linux_release()
get_linux_version()
get_file_system_drives()
if apt_available:
    get_number_of_available_updates()

# -----------------------------------------------------------------------------
#  MQTT Topic def's
# -----------------------------------------------------------------------------

command_base_topic = '{}/command/{}'.format(base_topic, sensor_name.lower())

# -----------------------------------------------------------------------------
#  timer and timer funcs for ALIVE MQTT Notices handling
# -----------------------------------------------------------------------------

K_ALIVE_TIMOUT_IN_SECONDS = 60


def publish_alive_status():
    print_line('- SEND: yes, still alive -', debug=True)
    mqtt_client.publish(lwt_sensor_topic, payload=lwt_online_val, retain=False)
    mqtt_client.publish(lwt_command_topic, payload=lwt_online_val, retain=False)


def publish_shutting_down_status():
    print_line('- SEND: shutting down -', debug=True)
    mqtt_client.publish(lwt_sensor_topic, payload=lwt_offline_val, retain=False)
    mqtt_client.publish(lwt_command_topic, payload=lwt_offline_val, retain=False)


def alive_timeout_handler():
    print_line('- MQTT TIMER INTERRUPT -', debug=True)
    threading.Thread(target=publish_alive_status).start()
    start_alive_timer()


def start_alive_timer():
    global alive_timer
    global alive_timer_running_status
    stop_alive_timer()
    alive_timer = threading.Timer(K_ALIVE_TIMOUT_IN_SECONDS, alive_timeout_handler)
    alive_timer.start()
    alive_timer_running_status = True
    print_line('- started MQTT timer - every {} seconds'.format(K_ALIVE_TIMOUT_IN_SECONDS), debug=True)


def stop_alive_timer():
    global alive_timer
    global alive_timer_running_status
    alive_timer.cancel()
    alive_timer_running_status = False
    print_line('- stopped MQTT timer', debug=True)


def is_alive_timer_running():
    global alive_timer_running_status
    return alive_timer_running_status


# our ALIVE TIMER
alive_timer = threading.Timer(K_ALIVE_TIMOUT_IN_SECONDS, alive_timeout_handler)
# our BOOL tracking state of ALIVE TIMER
alive_timer_running_status = False

# -----------------------------------------------------------------------------
#  MQTT setup and startup
# -----------------------------------------------------------------------------

# MQTT connection
lwt_sensor_topic = '{}/sensor/{}/status'.format(base_topic, sensor_name.lower())
lwt_command_topic = '{}/command/{}/status'.format(base_topic, sensor_name.lower())
lwt_online_val = 'online'
lwt_offline_val = 'offline'

print_line('Connecting to MQTT broker ...', verbose=True)
mqtt_client = mqtt.Client()
# hook up MQTT callbacks
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_publish = on_publish
mqtt_client.on_message = on_message

mqtt_client.will_set(lwt_sensor_topic, payload=lwt_offline_val, retain=True)
mqtt_client.will_set(lwt_command_topic, payload=lwt_offline_val, retain=True)

if config['MQTT'].getboolean('tls', False):
    # According to the docs, setting PROTOCOL_SSLv23 "Selects the highest protocol version
    # that both the client and server support. Despite the name, this option can select
    # “TLS” protocols as well as “SSL”" - so this seems like a reasonable default
    mqtt_client.tls_set(
        ca_certs=config['MQTT'].get('tls_ca_cert', None),
        keyfile=config['MQTT'].get('tls_keyfile', None),
        certfile=config['MQTT'].get('tls_certfile', None),
        tls_version=ssl.PROTOCOL_SSLv23
    )

mqtt_username = os.environ.get("MQTT_USERNAME", config['MQTT'].get('username'))
mqtt_password = os.environ.get(
    "MQTT_PASSWORD", config['MQTT'].get('password', None))

if mqtt_username:
    mqtt_client.username_pw_set(mqtt_username, mqtt_password)
try:
    mqtt_client.connect(os.environ.get('MQTT_HOSTNAME', config['MQTT'].get('hostname', 'localhost')),
                        port=int(os.environ.get(
                            'MQTT_PORT', config['MQTT'].get('port', '1883'))),
                        keepalive=config['MQTT'].getint('keepalive', 60))
except:
    print_line('MQTT connection error. Please check your settings in the configuration file "config.ini"',
               error=True, sd_notify=True)
    sys.exit(1)
else:
    mqtt_client.publish(lwt_sensor_topic, payload=lwt_online_val, retain=False)
    mqtt_client.publish(lwt_command_topic, payload=lwt_online_val, retain=False)
    mqtt_client.loop_start()

    while not mqtt_client_connected:  # wait in loop
        print_line(
            '* Wait on mqtt_client_connected=[{}]'.format(mqtt_client_connected), debug=True)
        sleep(1.0)  # some slack to establish the connection

    start_alive_timer()

sd_notifier.notify('READY=1')

# -----------------------------------------------------------------------------
#  Perform our MQTT Discovery Announcement...
# -----------------------------------------------------------------------------

# what RPi device are we on?
# get our hostnames so we can set up MQTT
get_network_ifs()  # this will fill in rpi_mac

mac_basic = rpi_mac.lower().replace(":", "")
mac_left = mac_basic[:6]
mac_right = mac_basic[6:]
print_line('mac lt=[{}], rt=[{}], mac=[{}]'.format(
    mac_left, mac_right, mac_basic), debug=True)
uniq_id = "RPi-{}Mon{}".format(mac_left, mac_right)

# our RPi Reporter device
# KeyError: 'home310/sensor/rpi-pi3plus/values' let's not use this 'values' as topic
K_LD_MONITOR = "monitor"
K_LD_SYS_TEMP = "temperature"
K_LD_FS_USED = "disk_used"
K_LD_PAYLOAD_NAME = "info"
K_LD_CPU_USE = "cpu_load"
K_LD_MEM_USED = "mem_used"

if interval_in_minutes < 5:
    K_LD_CPU_USE_JSON = "cpu.load_1min_prcnt"
elif interval_in_minutes < 15:
    K_LD_CPU_USE_JSON = "cpu.load_5min_prcnt"
else:
    K_LD_CPU_USE_JSON = "cpu.load_15min_prcnt"

# determine CPU model
if len(rpi_cpu_tuple) > 0:
    cpu_model = rpi_cpu_tuple[1]
else:
    cpu_model = ''

if cpu_model.find("ARMv7") >= 0 or cpu_model.find("ARMv6") >= 0:
    cpu_use_icon = "mdi:cpu-32-bit"
else:
    cpu_use_icon = "mdi:cpu-64-bit"

print_line('Announcing RPi Monitoring device to MQTT broker for auto-discovery ...')

# Publish our MQTT auto discovery
#  table of key items to publish:
detector_values = OrderedDict([
    (K_LD_MONITOR, dict(
        title="RPi Monitor {}".format(rpi_hostname),
        topic_category="sensor",
        device_class="timestamp",
        device_ident="RPi-{}".format(rpi_fqdn),
        no_title_prefix="yes",
        icon='mdi:raspberry-pi',
        json_attr="yes",
        json_value="timestamp",
    )),
    (K_LD_SYS_TEMP, dict(
        title="RPi Temp {}".format(rpi_hostname),
        topic_category="sensor",
        device_class="temperature",
        no_title_prefix="yes",
        unit="°C",
        icon='mdi:thermometer',
        json_value="temperature_c",
    )),
    (K_LD_FS_USED, dict(
        title="RPi Disk Used {}".format(rpi_hostname),
        topic_category="sensor",
        no_title_prefix="yes",
        unit="%",
        icon='mdi:sd',
        json_value="fs_used_prcnt",
    )),
    (K_LD_CPU_USE, dict(
        title="RPi CPU Use {}".format(rpi_hostname),
        topic_category="sensor",
        no_title_prefix="yes",
        unit="%",
        icon=cpu_use_icon,
        json_value=K_LD_CPU_USE_JSON,
    )),
    (K_LD_MEM_USED, dict(
        title="RPi Mem Used {}".format(rpi_hostname),
        topic_category="sensor",
        no_title_prefix="yes",
        json_value="mem_used_prcnt",
        unit="%",
        icon='mdi:memory'
    ))
])

for [command, _] in commands.items():
    # print_line('- REGISTER command: [{}]'.format(command), debug=True)
    iconName = 'mdi:gesture-tap'
    if 'reboot' in command:
        iconName = 'mdi:restart'
    elif 'shutdown' in command:
        iconName = 'mdi:power-sleep'
    elif 'service' in command:
        iconName = 'mdi:cog-counterclockwise'
    detector_values.update({
        command: dict(
            title='RPi {} {} Command'.format(command, rpi_hostname),
            topic_category='button',
            no_title_prefix='yes',
            icon=iconName,
            command=command,
            command_topic='{}/{}'.format(command_base_topic, command)
        )
    })

# print_line('- detectorValues=[{}]'.format(detectorValues), debug=True)

sensor_base_topic = '{}/sensor/{}'.format(base_topic, sensor_name.lower())
values_topic_rel = '{}/{}'.format('~', K_LD_MONITOR)
values_topic = '{}/{}'.format(sensor_base_topic, K_LD_MONITOR)
activity_topic_rel = '{}/status'.format('~')  # vs. LWT
activity_topic = '{}/status'.format(sensor_base_topic)  # vs. LWT

command_topic_rel = '~/set'

# discovery_topic = '{}/sensor/{}/{}/config'.format(discovery_prefix, sensor_name.lower(), sensor)
for [sensor, params] in detector_values.items():
    discovery_topic = '{}/{}/{}/{}/config'.format(discovery_prefix, params['topic_category'], sensor_name.lower(),
                                                  sensor)
    payload = OrderedDict()
    if 'no_title_prefix' in params:
        payload['name'] = "{}".format(params['title'].title())
    else:
        payload['name'] = "{} {}".format(
            sensor_name.title(), params['title'].title())
    payload['uniq_id'] = "{}_{}".format(uniq_id, sensor.lower())
    if 'device_class' in params:
        payload['dev_cla'] = params['device_class']
    if 'unit' in params:
        payload['unit_of_measurement'] = params['unit']
    if 'json_value' in params:
        payload['stat_t'] = values_topic_rel
        payload['val_tpl'] = "{{{{ value_json.{}.{} }}}}".format(K_LD_PAYLOAD_NAME, params['json_value'])
    if 'command' in params:
        payload['~'] = command_base_topic
        payload['cmd_t'] = '~/{}'.format(params['command'])
        payload['json_attr_t'] = '~/{}/attributes'.format(params['command'])
    else:
        payload['~'] = sensor_base_topic
    payload['avty_t'] = activity_topic_rel
    payload['pl_avail'] = lwt_online_val
    payload['pl_not_avail'] = lwt_offline_val
    if 'trigger_type' in params:
        payload['type'] = params['trigger_type']
    if 'trigger_subtype' in params:
        payload['subtype'] = params['trigger_subtype']
    if 'icon' in params:
        payload['ic'] = params['icon']
    if 'json_attr' in params:
        payload['json_attr_t'] = values_topic_rel
        payload['json_attr_tpl'] = '{{{{ value_json.{} | tojson }}}}'.format(K_LD_PAYLOAD_NAME)
    if 'device_ident' in params:
        payload['dev'] = {
            'identifiers': ["{}".format(uniq_id)],
            'manufacturer': 'Raspberry Pi (Trading) Ltd.',
            'name': params['device_ident'],
            'model': '{}'.format(rpi_model),
            'sw_version': "{} {}".format(rpi_linux_release, rpi_linux_version)
        }
    else:
        payload['dev'] = {
            'identifiers': ["{}".format(uniq_id)],
        }
    mqtt_client.publish(discovery_topic, json.dumps(payload), 1, retain=True)

    # remove connections as test:                  'connections' : [["mac", mac.lower()], [interface, ipaddr]],

# -----------------------------------------------------------------------------
#  timer and timer funcs for period handling
# -----------------------------------------------------------------------------

TIMER_INTERRUPT = (-1)
TEST_INTERRUPT = (-2)


def period_timeout_handler():
    print_line('- PERIOD TIMER INTERRUPT -', debug=True)
    handle_interrupt(TIMER_INTERRUPT)  # '0' means we have a timer interrupt!!!
    start_period_timer()


def start_period_timer():
    global end_period_timer
    global period_time_running_status
    stop_period_timer()
    end_period_timer = threading.Timer(interval_in_minutes * 60.0, period_timeout_handler)
    end_period_timer.start()
    period_time_running_status = True
    print_line('- started PERIOD timer - every {} seconds'.format(interval_in_minutes * 60.0), debug=True)


def stop_period_timer():
    global end_period_timer
    global period_time_running_status
    end_period_timer.cancel()
    period_time_running_status = False
    print_line('- stopped PERIOD timer', debug=True)


def is_period_timer_running():
    global period_time_running_status
    return period_time_running_status


# our TIMER
end_period_timer = threading.Timer(interval_in_minutes * 60.0, period_timeout_handler)
# our BOOL tracking state of TIMER
period_time_running_status = False
reported_first_time = False

# -----------------------------------------------------------------------------
#  MQTT Transmit Helper Routines
# -----------------------------------------------------------------------------
SCRIPT_TIMESTAMP = "timestamp"
K_RPI_MODEL = "rpi_model"
K_RPI_CONNECTIONS = "ifaces"
K_RPI_HOSTNAME = "host_name"
K_RPI_FQDN = "fqdn"
K_RPI_LINUX_RELEASE = "ux_release"
K_RPI_LINUX_VERSION = "ux_version"
K_RPI_LINUX_AVAIL_UPD = "ux_updates"
K_RPI_UPTIME = "up_time"
K_RPI_UPTIME_SECONDS = "up_time_secs"
K_RPI_DATE_LAST_UPDATE = "last_update"
K_RPI_FS_SPACE = 'fs_total_gb'  # "fs_space_gbytes"
K_RPI_FS_AVAIL = 'fs_free_prcnt'  # "fs_available_prcnt"
K_RPI_FS_USED = 'fs_used_prcnt'  # "fs_used_prcnt"
K_RPI_RAM_USED = 'mem_used_prcnt'  # "mem_used_prcnt"
K_RPI_SYSTEM_TEMP = "temperature_c"
K_RPI_GPU_TEMP = "temp_gpu_c"
K_RPI_CPU_TEMP = "temp_cpu_c"
K_RPI_SCRIPT = "reporter"
K_RPI_SCRIPT_VERSIONS = "reporter_releases"
K_RPI_NETWORK = "networking"
K_RPI_INTERFACE = "interface"
SCRIPT_REPORT_INTERVAL = "report_interval"
# new drives dictionary
K_RPI_DRIVES = "drives"
K_RPI_DRV_BLOCKS = "size_gb"
K_RPI_DRV_USED = "used_prcnt"
K_RPI_DRV_MOUNT = "mount_pt"
K_RPI_DRV_DEVICE = "device"
K_RPI_DRV_NFS = "device-nfs"
K_RPI_DVC_IP = "ip"
K_RPI_DVC_PATH = "dvc"
# new memory dictionary
K_RPI_MEMORY = "memory"
K_RPI_MEM_TOTAL = "size_mb"
K_RPI_MEM_FREE = "free_mb"
K_RPI_SWAP_TOTAL = "size_swap"
K_RPI_SWAP_FREE = "free_swap"
# Tuple (Hardware, Model Name, NbrCores, BogoMIPS, Serial)
K_RPI_CPU = "cpu"
K_RPI_CPU_HARDWARE = "hardware"
K_RPI_CPU_MODEL = "model"
K_RPI_CPU_CORES = "number_cores"
K_RPI_CPU_BOGOMIPS = "bogo_mips"
K_RPI_CPU_SERIAL = "serial"
#  add new CPU Load
K_RPI_CPU_LOAD1 = "load_1min_prcnt"
K_RPI_CPU_LOAD5 = "load_5min_prcnt"
K_RPI_CPU_LOAD15 = "load_15min_prcnt"
# list of throttle status
K_RPI_THROTTLE = "throttle"


def send_status(timestamp, _):
    rpi_data = OrderedDict()
    rpi_data[SCRIPT_TIMESTAMP] = timestamp.astimezone().replace(microsecond=0).isoformat()
    rpi_data[K_RPI_MODEL] = rpi_model
    rpi_data[K_RPI_CONNECTIONS] = rpi_connections
    rpi_data[K_RPI_HOSTNAME] = rpi_hostname
    rpi_data[K_RPI_FQDN] = rpi_fqdn
    rpi_data[K_RPI_LINUX_RELEASE] = rpi_linux_release
    rpi_data[K_RPI_LINUX_VERSION] = rpi_linux_version
    rpi_data[K_RPI_LINUX_AVAIL_UPD] = rpi_update_count
    rpi_data[K_RPI_UPTIME] = rpi_uptime
    rpi_data[K_RPI_UPTIME_SECONDS] = rpi_uptime_sec

    #  DON'T use V1 form of getting date (my dashbord mech)
    # actualDate = datetime.strptime(rpi_last_update_date, '%y%m%d%H%M%S')
    # actualDate.replace(tzinfo=local_tz)
    # rpi_data[K_RPI_DATE_LAST_UPDATE] = actualDate.astimezone().replace(microsecond=0).isoformat()
    # also don't use V2 form...
    # if rpi_last_update_date_v2 != datetime.min:
    #    rpi_data[K_RPI_DATE_LAST_UPDATE] = rpi_last_update_date_v2.astimezone().replace(microsecond=0).isoformat()
    # else:
    #    rpi_data[K_RPI_DATE_LAST_UPDATE] = ''
    if rpi_last_update_date != datetime.min:
        rpi_data[K_RPI_DATE_LAST_UPDATE] = rpi_last_update_date.astimezone().replace(
            microsecond=0).isoformat()
    else:
        rpi_data[K_RPI_DATE_LAST_UPDATE] = ''
    rpi_data[K_RPI_FS_SPACE] = int(rpi_filesystem_space.replace('GB', ''), 10)
    # TODO: consider eliminating K_RPI_FS_AVAIL/fs_free_prcnt as used is needed but free is not... (can be calculated)
    rpi_data[K_RPI_FS_AVAIL] = 100 - int(rpi_filesystem_percent, 10)
    rpi_data[K_RPI_FS_USED] = int(rpi_filesystem_percent, 10)

    rpi_data[K_RPI_NETWORK] = get_network_dictionary()

    rpi_drives = get_drives_dictionary()
    if len(rpi_drives) > 0:
        rpi_data[K_RPI_DRIVES] = rpi_drives

    rpi_ram = get_memory_dictionary()
    if len(rpi_ram) > 0:
        rpi_data[K_RPI_MEMORY] = rpi_ram
        ram_size_mb = int('{:.0f}'.format(rpi_memory_tuple[0], 10))  # "mem_space_mbytes"
        # used is total - free
        ram_used_mb = int('{:.0f}'.format(rpi_memory_tuple[0] - rpi_memory_tuple[2]), 10)
        ram_used_percent = int((ram_used_mb / ram_size_mb) * 100)
        rpi_data[K_RPI_RAM_USED] = ram_used_percent  # "mem_used_prcnt"

    rpi_cpu = get_cpu_dictionary()
    if len(rpi_cpu) > 0:
        rpi_data[K_RPI_CPU] = rpi_cpu

    if len(rpi_throttle_status) > 0:
        rpi_data[K_RPI_THROTTLE] = rpi_throttle_status

    rpi_data[K_RPI_SYSTEM_TEMP] = force_single_digit(rpi_system_temp)
    rpi_data[K_RPI_GPU_TEMP] = force_single_digit(rpi_gpu_temp)
    rpi_data[K_RPI_CPU_TEMP] = force_single_digit(rpi_cpu_temp)

    rpi_data[K_RPI_SCRIPT] = rpi_mqtt_script.replace('.py', '')
    rpi_data[K_RPI_SCRIPT_VERSIONS] = ','.join(daemon_version_list)
    rpi_data[SCRIPT_REPORT_INTERVAL] = interval_in_minutes

    rpi_top_dict = OrderedDict()
    rpi_top_dict[K_LD_PAYLOAD_NAME] = rpi_data

    threading.Thread(target=publish_monitor_data, args=(rpi_top_dict, values_topic)).start()


def force_single_digit(temperature):
    temp_interp = '{:.1f}'.format(temperature)
    return float(temp_interp)


def get_drives_dictionary():
    global rpi_filesystem
    rpi_drives = OrderedDict()

    # tuple { total blocks, used%, mountPoint, device }
    for drive_tuple in rpi_filesystem:
        rpi_single_drive = OrderedDict()
        rpi_single_drive[K_RPI_DRV_BLOCKS] = int(drive_tuple[0])
        rpi_single_drive[K_RPI_DRV_USED] = int(drive_tuple[1])
        device = drive_tuple[3]
        if ':' in device:
            rpi_device = OrderedDict()
            line_parts = device.split(':')
            rpi_device[K_RPI_DVC_IP] = line_parts[0]
            rpi_device[K_RPI_DVC_PATH] = line_parts[1]
            rpi_single_drive[K_RPI_DRV_NFS] = rpi_device
        else:
            rpi_single_drive[K_RPI_DRV_DEVICE] = device
            # rpiTest = OrderedDict()
            # rpiTest[K_RPI_DVC_IP] = '255.255.255.255'
            # rpiTest[K_RPI_DVC_PATH] = '/srv/c2db7b94'
            # rpi_single_drive[K_RPI_DRV_NFS] = rpiTest
        rpi_single_drive[K_RPI_DRV_MOUNT] = drive_tuple[2]
        drive_key = drive_tuple[2].replace('/', '-').replace('-', '', 1)
        if len(drive_key) == 0:
            drive_key = "root"
        rpi_drives[drive_key] = rpi_single_drive

        # TEST NFS
    return rpi_drives


def get_network_dictionary():
    global rpi_interfaces
    # TYPICAL:
    # rpi_interfaces=[[
    #   ('eth0', 'mac', 'b8:27:eb:1a:f3:bc'),
    #   ('wlan0', 'IP', '192.168.100.189'),
    #   ('wlan0', 'mac', 'b8:27:eb:4f:a6:e9')
    # ]]
    network_data = OrderedDict()

    prior_if_key = ''
    tmp_data = OrderedDict()
    for currTuple in rpi_interfaces:
        curr_if_key = currTuple[0]
        if prior_if_key == '':
            prior_if_key = curr_if_key
        if curr_if_key != prior_if_key:
            # save off prior if exists
            if prior_if_key != '':
                network_data[prior_if_key] = tmp_data
                tmp_data = OrderedDict()
                prior_if_key = curr_if_key
        sub_key = currTuple[1]
        sub_value = currTuple[2]
        tmp_data[sub_key] = sub_value
    network_data[prior_if_key] = tmp_data
    print_line('network_data:{}"'.format(network_data), debug=True)
    return network_data


def get_memory_dictionary():
    # TYPICAL:
    #   Tuple (Total, Free, Avail.)
    memory_data = OrderedDict()
    if rpi_memory_tuple:
        # TODO: remove free fr
        memory_data[K_RPI_MEM_TOTAL] = round(rpi_memory_tuple[0])
        memory_data[K_RPI_MEM_FREE] = round(rpi_memory_tuple[2])
        memory_data[K_RPI_SWAP_TOTAL] = round(rpi_memory_tuple[3])
        memory_data[K_RPI_SWAP_FREE] = round(rpi_memory_tuple[4])
    # print_line('memory_data:{}"'.format(memory_data), debug=True)
    return memory_data


def get_cpu_dictionary():
    # TYPICAL:
    #   Tuple (Hardware, Model Name, NbrCores, BogoMIPS, Serial)
    cpu_dict = OrderedDict()
    # print_line('rpi_cpu_tuple:{}"'.format(rpi_cpu_tuple), debug=True)
    if rpi_cpu_tuple != '':
        cpu_dict[K_RPI_CPU_HARDWARE] = rpi_cpu_tuple[0]
        cpu_dict[K_RPI_CPU_MODEL] = rpi_cpu_tuple[1]
        cpu_dict[K_RPI_CPU_CORES] = rpi_cpu_tuple[2]
        cpu_dict[K_RPI_CPU_BOGOMIPS] = '{:.2f}'.format(rpi_cpu_tuple[3])
        cpu_dict[K_RPI_CPU_SERIAL] = rpi_cpu_tuple[4]
        cpu_dict[K_RPI_CPU_LOAD1] = rpi_cpu_tuple[5]
        cpu_dict[K_RPI_CPU_LOAD5] = rpi_cpu_tuple[6]
        cpu_dict[K_RPI_CPU_LOAD15] = rpi_cpu_tuple[7]
    print_line('cpu_dict:{}"'.format(cpu_dict), debug=True)
    return cpu_dict


def publish_monitor_data(latest_data, topic):
    print_line('Publishing to MQTT topic "{}, Data:{}"'.format(
        topic, json.dumps(latest_data)))
    mqtt_client.publish('{}'.format(topic), json.dumps(
        latest_data), 1, retain=False)
    sleep(0.5)  # some slack for the publish roundtrip and callback function


def update_values():
    # run get latest values for all
    get_device_cpu_info()
    get_uptime()
    get_file_system_drives()
    get_system_temperature()
    get_system_thermal_status()
    get_last_update_date()
    get_device_memory()
    get_network_ifs()


# -----------------------------------------------------------------------------
# Interrupt handler
# -----------------------------------------------------------------------------


def handle_interrupt(channel):
    global reported_first_time
    source_id = "<< INTR(" + str(channel) + ")"
    current_timestamp = datetime.now(local_tz)
    print_line(source_id + " >> Time to report! (%s)" %
               current_timestamp.strftime('%H:%M:%S - %Y/%m/%d'), verbose=True)
    # ----------------------------------
    # have PERIOD interrupt!
    update_values()

    if opt_stall is False or reported_first_time is False and opt_stall is True:
        # ok, report our new detection to MQTT
        threading.Thread(target=send_status, args=(current_timestamp, '')).start()

        reported_first_time = True
    else:
        print_line(source_id + " >> Time to report! (%s) but SKIPPED (TEST: stall)" %
                   current_timestamp.strftime('%H:%M:%S - %Y/%m/%d'), verbose=True)


def after_mqtt_connect():
    print_line('* afterMQTTConnect()', verbose=True)
    #  NOTE: this is run after MQTT connects
    # start our interval timer
    start_period_timer()
    # do our first report
    handle_interrupt(0)


# TESTING AGAIN
# get_network_ifs()
# get_last_update_date()
#
# TESTING, early abort
# stop_alive_timer()
# exit(0)

after_mqtt_connect()  # now instead of after?

# check every 12 hours (twice a day) = 12 hours * 60 minutes * 60 seconds
k_version_check_interval_in_seconds = (12 * 60 * 60)
# check every 4 hours (6 times a day) = 4 hours * 60 minutes * 60 seconds
k_update_check_interval_in_seconds = (check_interval_in_hours * 60 * 60)

# now just hang in forever loop until script is stopped externally
try:
    while True:
        #  our INTERVAL timer does the work
        sleep(10000)

        time_now = time()
        if time_now > daemon_last_fetch_time + k_version_check_interval_in_seconds:
            get_daemon_releases()  # and load them!

        if apt_available:
            if time_now > update_last_fetch_time + k_update_check_interval_in_seconds:
                get_number_of_available_updates()  # and count them!

finally:
    # cleanup used pins... just because we like cleaning up after us
    publish_shutting_down_status()
    stop_period_timer()  # don't leave our timers running!
    stop_alive_timer()
    mqtt_client.disconnect()
    print_line('* MQTT Disconnect()', verbose=True)
