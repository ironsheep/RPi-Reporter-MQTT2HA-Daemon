#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import _thread
from datetime import datetime
from tzlocal import get_localzone
import threading
import socket
import os
import subprocess
import uuid
import ssl
import sys
import re
import json
import os.path
import argparse
from time import time, sleep, localtime, strftime
from collections import OrderedDict
from colorama import init as colorama_init
from colorama import Fore, Back, Style
from configparser import ConfigParser
from unidecode import unidecode
import paho.mqtt.client as mqtt
import sdnotify
from signal import signal, SIGPIPE, SIG_DFL
signal(SIGPIPE,SIG_DFL)

script_version = "1.3.1"
script_name = 'ISP-RPi-mqtt-daemon.py'
script_info = '{} v{}'.format(script_name, script_version)
project_name = 'RPi Reporter MQTT2HA Daemon'
project_url = 'https://github.com/ironsheep/RPi-Reporter-MQTT2HA-Daemon'

# we'll use this throughout
local_tz = get_localzone()

# TODO:
#  - add announcement of free-space and temperatore endpoints

if False:
    # will be caught by python 2.7 to be illegal syntax
    print_line('Sorry, this script requires a python3 runtime environment.', file=sys.stderr)

# Argparse
opt_debug = False
opt_verbose = False

# Systemd Service Notifications - https://github.com/bb4242/sdnotify
sd_notifier = sdnotify.SystemdNotifier()

# Logging function
def print_line(text, error=False, warning=False, info=False, verbose=False, debug=False, console=True, sd_notify=False):
    timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
    if console:
        if error:
            print(Fore.RED + Style.BRIGHT + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL, file=sys.stderr)
        elif warning:
            print(Fore.YELLOW + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
        elif info or verbose:
            if opt_verbose:
                print(Fore.GREEN + '[{}] '.format(timestamp) + Fore.YELLOW  + '- ' + '{}'.format(text) + Style.RESET_ALL)
        elif debug:
            if opt_debug:
                print(Fore.CYAN + '[{}] '.format(timestamp) + '- (DBG): ' + '{}'.format(text) + Style.RESET_ALL)
        else:
            print(Fore.GREEN + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)

    timestamp_sd = strftime('%b %d %H:%M:%S', localtime())
    if sd_notify:
        sd_notifier.notify('STATUS={} - {}.'.format(timestamp_sd, unidecode(text)))

# Identifier cleanup
def clean_identifier(name):
    clean = name.strip()
    for this, that in [[' ', '-'], ['ä', 'ae'], ['Ä', 'Ae'], ['ö', 'oe'], ['Ö', 'Oe'], ['ü', 'ue'], ['Ü', 'Ue'], ['ß', 'ss']]:
        clean = clean.replace(this, that)
    clean = unidecode(clean)
    return clean

# Argparse            
parser = argparse.ArgumentParser(description=project_name, epilog='For further details see: ' + project_url)
parser.add_argument("-v", "--verbose", help="increase output verbosity", action="store_true")
parser.add_argument("-d", "--debug", help="show debug output", action="store_true")
parser.add_argument("-s", "--stall", help="TEST: report only the first time", action="store_true")
parser.add_argument("-c", '--config_dir', help='set directory where config.ini is located', default=sys.path[0])
parse_args = parser.parse_args()

config_dir = parse_args.config_dir
opt_debug = parse_args.debug
opt_verbose = parse_args.verbose
opt_stall = parse_args.stall

print_line(script_info, info=True)
if opt_verbose:
    print_line('Verbose enabled', info=True)
if opt_debug:
    print_line('Debug enabled', debug=True)
if opt_stall:
    print_line('TEST: Stall (no-re-reporting) enabled', debug=True)

# Eclipse Paho callbacks - http://www.eclipse.org/paho/clients/python/docs/#callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print_line('* MQTT connection established', console=True, sd_notify=True)
        print_line('')  # blank line?!
        #_thread.start_new_thread(afterMQTTConnect, ())
    else:
        print_line('! Connection error with result code {} - {}'.format(str(rc), mqtt.connack_string(rc)), error=True)
        #kill main thread
        os._exit(1)

def on_publish(client, userdata, mid):
    #print_line('* Data successfully published.')
    pass

# Load configuration file
config = ConfigParser(delimiters=('=', ), inline_comment_prefixes=('#'))
config.optionxform = str
try:
    with open(os.path.join(config_dir, 'config.ini')) as config_file:
        config.read_file(config_file)
except IOError:
    print_line('No configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

daemon_enabled = config['Daemon'].getboolean('enabled', True)

# This script uses a flag file containing a date/timestamp of when the system was last updated
default_update_flag_filespec = '/home/pi/bin/lastupd.date'
update_flag_filespec = config['Daemon'].get('update_flag_filespec', default_update_flag_filespec)

default_base_topic = 'home/nodes'
base_topic = config['MQTT'].get('base_topic', default_base_topic).lower()

default_sensor_name = 'rpi-reporter'
sensor_name = config['MQTT'].get('sensor_name', default_sensor_name).lower()

# by default Home Assistant listens to the /homeassistant but it can be changed for a given installation
default_discovery_prefix = 'homeassistant'
discovery_prefix = config['MQTT'].get('discovery_prefix', default_discovery_prefix).lower()

# report our RPi values every 5min 
min_interval_in_minutes = 2
max_interval_in_minutes = 30
default_interval_in_minutes = 5
interval_in_minutes = config['Daemon'].getint('interval_in_minutes', default_interval_in_minutes)

# default domain when hostname -f doesn't return it
default_domain = ''
fallback_domain = config['Daemon'].get('fallback_domain', default_domain).lower()


# Check configuration
#
if (interval_in_minutes < min_interval_in_minutes) or (interval_in_minutes > max_interval_in_minutes):
    print_line('ERROR: Invalid "interval_in_minutes" found in configuration file: "config.ini"! Must be [{}-{}] Fix and try again... Aborting'.format(min_interval_in_minutes, max_interval_in_minutes), error=True, sd_notify=True)
    sys.exit(1)    

### Ensure required values within sections of our config are present
if not config['MQTT']:
    print_line('ERROR: No MQTT settings found in configuration file "config.ini"! Fix and try again... Aborting', error=True, sd_notify=True)
    sys.exit(1)

print_line('Configuration accepted', console=False, sd_notify=True)

# -----------------------------------------------------------------------------
#  RPi variables monitored 
# -----------------------------------------------------------------------------

rpi_model_raw = ''
rpi_model = ''
rpi_connections = ''
rpi_hostname = ''
rpi_fqdn = ''
rpi_linux_release = ''
rpi_linux_version = ''
rpi_uptime_raw = ''
rpi_uptime = ''
rpi_last_update_date = ''
rpi_last_update_date_v2 = datetime.min
rpi_filesystem_space_raw = ''
rpi_filesystem_space = ''
rpi_filesystem_percent = ''
rpi_system_temp = ''
rpi_gpu_temp = ''
rpi_cpu_temp = ''
rpi_mqtt_script = script_info
rpi_interfaces = []

# -----------------------------------------------------------------------------
#  monitor variable fetch routines
#
def getDeviceModel():
    global rpi_model
    global rpi_model_raw
    global rpi_connections
    out = subprocess.Popen("/bin/cat /proc/device-tree/model | /bin/sed -e 's/\\x0//g'", 
           shell=True,
           stdout=subprocess.PIPE, 
           stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_model_raw = stdout.decode('utf-8')
    # now reduce string length (just more compact, same info)
    rpi_model = rpi_model_raw.replace('Raspberry ', 'R').replace('i Model ', 'i 1 Model').replace('Rev ', 'r').replace(' Plus ', '+')

    # now decode interfaces
    rpi_connections = 'e,w,b' # default
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

def getLinuxRelease():
    global rpi_linux_release
    out = subprocess.Popen("/bin/cat /etc/apt/sources.list | /bin/egrep -v '#' | /usr/bin/awk '{ print $3 }' | /bin/grep . | /usr/bin/sort -u", 
           shell=True,
           stdout=subprocess.PIPE, 
           stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_linux_release = stdout.decode('utf-8').rstrip()
    print_line('rpi_linux_release=[{}]'.format(rpi_linux_release), debug=True)

def getLinuxVersion():
    global rpi_linux_version
    out = subprocess.Popen("/bin/uname -r", 
           shell=True,
           stdout=subprocess.PIPE, 
           stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_linux_version = stdout.decode('utf-8').rstrip()
    print_line('rpi_linux_version=[{}]'.format(rpi_linux_version), debug=True)
    
def getHostnames():
    global rpi_hostname
    global rpi_fqdn
    out = subprocess.Popen("/bin/hostname -f", 
           shell=True,
           stdout=subprocess.PIPE, 
           stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
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
        else 
            rpi_fqdn = rpi_hostname

    print_line('rpi_fqdn=[{}]'.format(rpi_fqdn), debug=True)
    print_line('rpi_hostname=[{}]'.format(rpi_hostname), debug=True)

def getUptime():
    global rpi_uptime_raw
    global rpi_uptime
    out = subprocess.Popen("/usr/bin/uptime", 
           shell=True,
           stdout=subprocess.PIPE, 
           stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_uptime_raw = stdout.decode('utf-8').rstrip().lstrip()
    print_line('rpi_uptime_raw=[{}]'.format(rpi_uptime_raw), debug=True)
    basicParts = rpi_uptime_raw.split()
    timeStamp = basicParts[0]
    lineParts = rpi_uptime_raw.split(',')
    if('user' in lineParts[1]):
        rpi_uptime_raw = lineParts[0]
    else:
        rpi_uptime_raw = '{}, {}'.format(lineParts[0], lineParts[1])
    rpi_uptime = rpi_uptime_raw.replace(timeStamp, '').lstrip().replace('up ', '')
    print_line('rpi_uptime=[{}]'.format(rpi_uptime), debug=True)

def getNetworkIFs():
    global rpi_interfaces
    global rpi_mac
    out = subprocess.Popen('/sbin/ifconfig | egrep "Link|flags|inet|ether" | egrep -v -i "lo:|loopback|inet6|\:\:1|127\.0\.0\.1"', 
           shell=True,
           stdout=subprocess.PIPE, 
           stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    lines = stdout.decode('utf-8').split("\n")
    trimmedLines = []
    for currLine in lines:
        trimmedLine = currLine.lstrip().rstrip()
        trimmedLines.append(trimmedLine)

    print_line('trimmedLines=[{}]'.format(trimmedLines), debug=True)
    #
    # OLDER SYSTEMS
    #  eth0      Link encap:Ethernet  HWaddr b8:27:eb:c8:81:f2  
    #    inet addr:192.168.100.41  Bcast:192.168.100.255  Mask:255.255.255.0
    #  wlan0     Link encap:Ethernet  HWaddr 00:0f:60:03:e6:dd  
    # NEWER SYSTEMS
    #  The following means eth0 (wired is NOT connected, and WiFi is connected)
    #  eth0: flags=4099<UP,BROADCAST,MULTICAST>  mtu 1500
    #    ether b8:27:eb:1a:f3:bc  txqueuelen 1000  (Ethernet)
    #  wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
    #    inet 192.168.100.189  netmask 255.255.255.0  broadcast 192.168.100.255
    #    ether b8:27:eb:4f:a6:e9  txqueuelen 1000  (Ethernet)
    #
    tmpInterfaces = []
    haveIF = False
    imterfc = ''
    rpi_mac = ''
    for currLine in trimmedLines:
        lineParts = currLine.split()
        print_line('- currLine=[{}]'.format(currLine), debug=True)
        print_line('- lineParts=[{}]'.format(lineParts), debug=True)
        if len(lineParts) > 0:
            if 'flags' in currLine:  # NEWER ONLY
                haveIF = True
                imterfc = lineParts[0].replace(':', '')
                print_line('newIF=[{}]'.format(imterfc), debug=True)
            elif 'Link' in currLine:  # OLDER ONLY
                haveIF = True
                imterfc = lineParts[0].replace(':', '')
                newTuple = (imterfc, 'mac', lineParts[4])
                if rpi_mac == '':
                    rpi_mac = lineParts[4]
                print_line('newIF=[{}]'.format(imterfc), debug=True)
                tmpInterfaces.append(newTuple)
                print_line('newTuple=[{}]'.format(newTuple), debug=True)
            elif haveIF == True:
                print_line('IF=[{}], lineParts=[{}]'.format(imterfc, lineParts), debug=True)
                if 'ether' in currLine: # NEWER ONLY
                    newTuple = (imterfc, 'mac', lineParts[1])
                    tmpInterfaces.append(newTuple)
                    print_line('newTuple=[{}]'.format(newTuple), debug=True)
                elif 'inet' in currLine:  # OLDER & NEWER
                    newTuple = (imterfc, 'IP', lineParts[1].replace('addr:',''))
                    tmpInterfaces.append(newTuple)
                    print_line('newTuple=[{}]'.format(newTuple), debug=True)

    rpi_interfaces = tmpInterfaces
    print_line('rpi_interfaces=[{}]'.format(rpi_interfaces), debug=True)

def getFileSystemSpace():
    global rpi_filesystem_space_raw
    global rpi_filesystem_space
    global rpi_filesystem_percent
    out = subprocess.Popen("/bin/df -m | /bin/grep root", 
            shell=True,
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_filesystem_space_raw = stdout.decode('utf-8').rstrip()
    print_line('rpi_filesystem_space_raw=[{}]'.format(rpi_filesystem_space_raw), debug=True)
    lineParts = rpi_filesystem_space_raw.split()
    print_line('lineParts=[{}]'.format(lineParts), debug=True)
    filesystem_1GBlocks = int(lineParts[1],10) / 1024
    if filesystem_1GBlocks > 32:
        rpi_filesystem_space = '64GB'
    elif filesystem_1GBlocks > 16:
        rpi_filesystem_space = '32GB'
    elif filesystem_1GBlocks > 8:
        rpi_filesystem_space = '16GB'
    elif filesystem_1GBlocks > 4:
        rpi_filesystem_space = '8GB'
    elif filesystem_1GBlocks > 2:
        rpi_filesystem_space = '4GB'
    elif filesystem_1GBlocks > 1:
        rpi_filesystem_space = '2GB'
    else:
        rpi_filesystem_space = '1GB'
    print_line('rpi_filesystem_space=[{}]'.format(rpi_filesystem_space), debug=True)
    rpi_filesystem_percent = lineParts[4].replace('%', '')
    print_line('rpi_filesystem_percent=[{}]'.format(rpi_filesystem_percent), debug=True)

def getSystemTemperature():
    global rpi_system_temp
    global rpi_gpu_temp
    global rpi_cpu_temp
    rpi_gpu_temp_raw = 'failed'
    retry_count = 3
    while retry_count > 0 and 'failed' in rpi_gpu_temp_raw:
        out = subprocess.Popen("/opt/vc/bin/vcgencmd measure_temp | /bin/sed -e 's/\\x0//g'", 
                shell=True,
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT)
        stdout,stderr = out.communicate()
        rpi_gpu_temp_raw = stdout.decode('utf-8').rstrip().replace('temp=', '').replace('\'C', '')
        retry_count -= 1
        sleep(1)

    if 'failed' in rpi_gpu_temp_raw:
        interpretedTemp = float('-1.0')
    else:
        interpretedTemp = float(rpi_gpu_temp_raw)
    rpi_gpu_temp = interpretedTemp
    print_line('rpi_gpu_temp=[{}]'.format(rpi_gpu_temp), debug=True)

    out = subprocess.Popen("/bin/cat /sys/class/thermal/thermal_zone0/temp", 
                shell=True,
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_cpu_temp_raw = stdout.decode('utf-8').rstrip()
    rpi_cpu_temp = float(rpi_cpu_temp_raw) / 1000.0
    print_line('rpi_cpu_temp=[{}]'.format(rpi_cpu_temp), debug=True)

    # fallback to CPU temp is GPU not available
    rpi_system_temp = rpi_gpu_temp
    if rpi_gpu_temp == -1.0:
        rpi_system_temp = rpi_cpu_temp
    

def getLastUpdateDateV2():
    global rpi_last_update_date_v2
    apt_log_filespec = '/var/log/dpkg.log'
    try:
        mtime = os.path.getmtime(apt_log_filespec)
    except OSError:
        mtime = 0
    last_modified_date = datetime.fromtimestamp(mtime, tz=local_tz)
    rpi_last_update_date_v2  = last_modified_date
    print_line('rpi_last_update_date_v2=[{}]'.format(rpi_last_update_date_v2), debug=True)

# get our hostnames so we can setup MQTT
getHostnames()
if(sensor_name == default_sensor_name):
    sensor_name = 'rpi-{}'.format(rpi_hostname)
# get model so we can use it too in MQTT
getDeviceModel()
getLinuxRelease()
getLinuxVersion()

# -----------------------------------------------------------------------------
#  timer and timer funcs for ALIVE MQTT Notices handling
# -----------------------------------------------------------------------------

ALIVE_TIMOUT_IN_SECONDS = 60

def publishAliveStatus():
    print_line('- SEND: yes, still alive -', debug=True)
    mqtt_client.publish(lwt_topic, payload=lwt_online_val, retain=False)

def aliveTimeoutHandler():
    print_line('- MQTT TIMER INTERRUPT -', debug=True)
    _thread.start_new_thread(publishAliveStatus, ())
    startAliveTimer()

def startAliveTimer():
    global aliveTimer
    global aliveTimerRunningStatus
    stopAliveTimer()
    aliveTimer = threading.Timer(ALIVE_TIMOUT_IN_SECONDS, aliveTimeoutHandler) 
    aliveTimer.start()
    aliveTimerRunningStatus = True
    print_line('- started MQTT timer - every {} seconds'.format(ALIVE_TIMOUT_IN_SECONDS), debug=True)

def stopAliveTimer():
    global aliveTimer
    global aliveTimerRunningStatus
    aliveTimer.cancel()
    aliveTimerRunningStatus = False
    print_line('- stopped MQTT timer', debug=True)

def isAliveTimerRunning():
    global aliveTimerRunningStatus
    return aliveTimerRunningStatus

# our ALIVE TIMER
aliveTimer = threading.Timer(ALIVE_TIMOUT_IN_SECONDS, aliveTimeoutHandler) 
# our BOOL tracking state of ALIVE TIMER
aliveTimerRunningStatus = False



# -----------------------------------------------------------------------------
#  MQTT setup and startup
# -----------------------------------------------------------------------------

# MQTT connection
lwt_topic = '{}/sensor/{}/status'.format(base_topic, sensor_name.lower())
lwt_online_val = 'online'
lwt_offline_val = 'offline'

print_line('Connecting to MQTT broker ...', verbose=True)
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_publish = on_publish

mqtt_client.will_set(lwt_topic, payload=lwt_offline_val, retain=True)

if config['MQTT'].getboolean('tls', False):
    # According to the docs, setting PROTOCOL_SSLv23 "Selects the highest protocol version
    # that both the client and server support. Despite the name, this option can select
    # “TLS” protocols as well as “SSL”" - so this seems like a resonable default
    mqtt_client.tls_set(
        ca_certs=config['MQTT'].get('tls_ca_cert', None),
        keyfile=config['MQTT'].get('tls_keyfile', None),
        certfile=config['MQTT'].get('tls_certfile', None),
        tls_version=ssl.PROTOCOL_SSLv23
    )

mqtt_username = os.environ.get("MQTT_USERNAME", config['MQTT'].get('username'))
mqtt_password = os.environ.get("MQTT_PASSWORD", config['MQTT'].get('password', None))

if mqtt_username:
    mqtt_client.username_pw_set(mqtt_username, mqtt_password)
try:
    mqtt_client.connect(os.environ.get('MQTT_HOSTNAME', config['MQTT'].get('hostname', 'localhost')),
                        port=int(os.environ.get('MQTT_PORT', config['MQTT'].get('port', '1883'))),
                        keepalive=config['MQTT'].getint('keepalive', 60))
except:
    print_line('MQTT connection error. Please check your settings in the configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)
else:
    mqtt_client.publish(lwt_topic, payload=lwt_online_val, retain=False)
    mqtt_client.loop_start()
    sleep(1.0) # some slack to establish the connection
    startAliveTimer()

sd_notifier.notify('READY=1')




# -----------------------------------------------------------------------------
#  Perform our MQTT Discovery Announcement...
# -----------------------------------------------------------------------------

# what RPi device are we on?
rpi_mac = ''
# get our hostnames so we can setup MQTT
getNetworkIFs() # this will fill-in rpi_mac

mac_basic = rpi_mac.lower().replace(":", "")
mac_left = mac_basic[:6]
mac_right = mac_basic[6:]
print_line('mac lt=[{}], rt=[{}], mac=[{}]'.format(mac_left, mac_right, mac_basic), debug=True)
uniqID = "RPi-{}Mon{}".format(mac_left, mac_right)

# our RPi Reporter device
LD_MONITOR = "monitor" # KeyError: 'home310/sensor/rpi-pi3plus/values' let's not use this 'values' as topic
LD_SYS_TEMP= "temperature"
LD_FS_USED = "disk_used"
LDS_PAYLOAD_NAME = "info"

# Publish our MQTT auto discovery
#  table of key items to publish:
detectorValues = OrderedDict([
    (LD_MONITOR, dict(title="RPi Monitor {}".format(rpi_hostname), device_class="timestamp", no_title_prefix="yes", json_value="timestamp", json_attr="yes", icon='mdi:raspberry-pi', device_ident="RPi-{}".format(rpi_fqdn))),
    (LD_SYS_TEMP, dict(title="RPi Temp {}".format(rpi_hostname), device_class="temperature", no_title_prefix="yes", unit="C", json_value="temperature_c", icon='mdi:thermometer')),
    (LD_FS_USED, dict(title="RPi Used {}".format(rpi_hostname), no_title_prefix="yes", json_value="fs_free_prcnt", unit="%", icon='mdi:sd')),
])

print_line('Announcing RPi Monitoring device to MQTT broker for auto-discovery ...')

base_topic = '{}/sensor/{}'.format(base_topic, sensor_name.lower())
values_topic_rel = '{}/{}'.format('~', LD_MONITOR)
values_topic = '{}/{}'.format(base_topic, LD_MONITOR) 
activity_topic_rel = '{}/status'.format('~')     # vs. LWT
activity_topic = '{}/status'.format(base_topic)    # vs. LWT

command_topic_rel = '~/set'

for [sensor, params] in detectorValues.items():
    discovery_topic = '{}/sensor/{}/{}/config'.format(discovery_prefix, sensor_name.lower(), sensor)
    payload = OrderedDict()
    if 'no_title_prefix' in params:
        payload['name'] = "{}".format(params['title'].title())
    else:
        payload['name'] = "{} {}".format(sensor_name.title(), params['title'].title())
    payload['uniq_id'] = "{}_{}".format(uniqID, sensor.lower())
    if 'device_class' in params:
        payload['dev_cla'] = params['device_class']
    if 'unit' in params:
        payload['unit_of_measurement'] = params['unit']
    if 'json_value' in params:
        payload['stat_t'] = values_topic_rel
        payload['val_tpl'] = "{{{{ value_json.{}.{} }}}}".format(LDS_PAYLOAD_NAME, params['json_value'])
    payload['~'] = base_topic
    payload['pl_avail'] = lwt_online_val
    payload['pl_not_avail'] = lwt_offline_val
    if 'icon' in params:
        payload['ic'] = params['icon']
    payload['avty_t'] = activity_topic_rel
    if 'json_attr' in params:
        payload['json_attr_t'] = values_topic_rel
        payload['json_attr_tpl'] = '{{{{ value_json.{} | tojson }}}}'.format(LDS_PAYLOAD_NAME)
    if 'device_ident' in params:
        payload['dev'] = {
                'identifiers' : ["{}".format(uniqID)],
                'manufacturer' : 'Raspberry Pi (Trading) Ltd.',
                'name' : params['device_ident'],
                'model' : '{}'.format(rpi_model),
                'sw_version': "{} {}".format(rpi_linux_release, rpi_linux_version)
        }
    else:
         payload['dev'] = {
                'identifiers' : ["{}".format(uniqID)],
         }
    mqtt_client.publish(discovery_topic, json.dumps(payload), 1, retain=True)

    # remove connections as test:                  'connections' : [["mac", mac.lower()], [interface, ipaddr]],

# -----------------------------------------------------------------------------
#  timer and timer funcs for period handling
# -----------------------------------------------------------------------------

TIMER_INTERRUPT = (-1)
TEST_INTERRUPT = (-2)

def periodTimeoutHandler():
    print_line('- PERIOD TIMER INTERRUPT -', debug=True)
    handle_interrupt(TIMER_INTERRUPT) # '0' means we have a timer interrupt!!!
    startPeriodTimer()

def startPeriodTimer():
    global endPeriodTimer
    global periodTimeRunningStatus
    stopPeriodTimer()
    endPeriodTimer = threading.Timer(interval_in_minutes * 60.0, periodTimeoutHandler) 
    endPeriodTimer.start()
    periodTimeRunningStatus = True
    print_line('- started PERIOD timer - every {} seconds'.format(interval_in_minutes * 60.0), debug=True)

def stopPeriodTimer():
    global endPeriodTimer
    global periodTimeRunningStatus
    endPeriodTimer.cancel()
    periodTimeRunningStatus = False
    print_line('- stopped PERIOD timer', debug=True)

def isPeriodTimerRunning():
    global periodTimeRunningStatus
    return periodTimeRunningStatus



# our TIMER
endPeriodTimer = threading.Timer(interval_in_minutes * 60.0, periodTimeoutHandler) 
# our BOOL tracking state of TIMER
periodTimeRunningStatus = False
reported_first_time = False

# -----------------------------------------------------------------------------
#  MQTT Transmit Helper Routines
# -----------------------------------------------------------------------------
SCRIPT_TIMESTAMP = "timestamp"
RPI_MODEL = "rpi_model"
RPI_CONNECTIONS = "ifaces"
RPI_HOSTNAME = "host_name"
RPI_FQDN = "fqdn"
RPI_LINUX_RELEASE = "ux_release" 
RPI_LINUX_VERSION = "ux_version" 
RPI_UPTIME = "up_time"
RPI_DATE_LAST_UPDATE = "last_update"
RPI_FS_SPACE = 'fs_total_gb' # "fs_space_gbytes"
RPI_FS_AVAIL = 'fs_free_prcnt' # "fs_available_prcnt"
RPI_SYSTEM_TEMP = "temperature_c"
RPI_GPU_TEMP = "temp_gpu_c"
RPI_CPU_TEMP = "temp_cpu_c"
RPI_SCRIPT = "reporter"
RPI_NETWORK = "networking"
RPI_INTERFACE = "interface"
SCRIPT_REPORT_INTERVAL = "report_interval"

def send_status(timestamp, nothing):
    global rpi_model
    global rpi_connections
    global rpi_hostname
    global rpi_fqdn
    global rpi_linux_release
    global rpi_linux_version
    global rpi_uptime
    global rpi_last_update_date
    global rpi_filesystem_space
    global rpi_filesystem_percent
    global rpi_system_temp
    global rpi_gpu_temp
    global rpi_cpu_temp
    global rpi_mqtt_script

    rpiData = OrderedDict()
    rpiData[SCRIPT_TIMESTAMP] = timestamp.astimezone().replace(microsecond=0).isoformat()
    rpiData[RPI_MODEL] = rpi_model
    rpiData[RPI_CONNECTIONS] = rpi_connections
    rpiData[RPI_HOSTNAME] = rpi_hostname
    rpiData[RPI_FQDN] = rpi_fqdn
    rpiData[RPI_LINUX_RELEASE] = rpi_linux_release
    rpiData[RPI_LINUX_VERSION] = rpi_linux_version
    rpiData[RPI_UPTIME] = rpi_uptime

    #  DON'T use V1 form of getting date (my dashbord mech)
    #actualDate = datetime.strptime(rpi_last_update_date, '%y%m%d%H%M%S')
    #actualDate.replace(tzinfo=local_tz)
    #rpiData[RPI_DATE_LAST_UPDATE] = actualDate.astimezone().replace(microsecond=0).isoformat()
    if rpi_last_update_date_v2 != datetime.min:
        rpiData[RPI_DATE_LAST_UPDATE] = rpi_last_update_date_v2.astimezone().replace(microsecond=0).isoformat()
    else:
        rpiData[RPI_DATE_LAST_UPDATE] = ''
    rpiData[RPI_FS_SPACE] = int(rpi_filesystem_space.replace('GB', ''),10)
    rpiData[RPI_FS_AVAIL] = int(rpi_filesystem_percent,10)

    rpiData[RPI_NETWORK] = getNetworkDictionary()

    rpiData[RPI_SYSTEM_TEMP] = forceSingleDigit(rpi_system_temp)
    rpiData[RPI_GPU_TEMP] = forceSingleDigit(rpi_gpu_temp)
    rpiData[RPI_CPU_TEMP] = forceSingleDigit(rpi_cpu_temp)

    rpiData[RPI_SCRIPT] = rpi_mqtt_script.replace('.py', '')
    rpiData[SCRIPT_REPORT_INTERVAL] = interval_in_minutes

    rpiTopDict = OrderedDict()
    rpiTopDict[LDS_PAYLOAD_NAME] = rpiData

    _thread.start_new_thread(publishMonitorData, (rpiTopDict, values_topic))

def forceSingleDigit(temperature):
    tempInterp = '{:.1f}'.format(temperature)
    return float(tempInterp)


def getNetworkDictionary():
    global rpi_interfaces
    # TYPICAL:
    # rpi_interfaces=[[
    #   ('eth0', 'mac', 'b8:27:eb:1a:f3:bc'), 
    #   ('wlan0', 'IP', '192.168.100.189'), 
    #   ('wlan0', 'mac', 'b8:27:eb:4f:a6:e9')
    # ]]
    networkData = OrderedDict()

    priorIFKey = ''
    tmpData = OrderedDict()
    for currTuple in rpi_interfaces:
        currIFKey = currTuple[0]
        if priorIFKey == '':
            priorIFKey = currIFKey
        if currIFKey != priorIFKey:
            # save off prior if exists
            if priorIFKey != '':
                networkData[priorIFKey] = tmpData
                tmpData = OrderedDict()
                priorIFKey = currIFKey
        subKey = currTuple[1]
        subValue = currTuple[2]
        tmpData[subKey] = subValue
    networkData[priorIFKey] = tmpData
    print_line('networkData:{}"'.format(networkData), debug=True)
    return networkData

def publishMonitorData(latestData, topic):
    print_line('Publishing to MQTT topic "{}, Data:{}"'.format(topic, json.dumps(latestData)))
    mqtt_client.publish('{}'.format(topic), json.dumps(latestData), 1, retain=False)
    sleep(0.5) # some slack for the publish roundtrip and callback function  


def update_values():
    # nothing here yet
    getUptime()
    getFileSystemSpace()
    getSystemTemperature()
    getLastUpdateDateV2()

# -----------------------------------------------------------------------------

# Interrupt handler
def handle_interrupt(channel):
    global reported_first_time
    sourceID = "<< INTR(" + str(channel) + ")"
    current_timestamp = datetime.now(local_tz)
    print_line(sourceID + " >> Time to report! (%s)" % current_timestamp.strftime('%H:%M:%S - %Y/%m/%d'), verbose=True)
    # ----------------------------------
    # have PERIOD interrupt!
    update_values()

    if (opt_stall == False or reported_first_time == False and opt_stall == True):
        # ok, report our new detection to MQTT
        _thread.start_new_thread(send_status, (current_timestamp, ''))
        reported_first_time = True
    else:
        print_line(sourceID + " >> Time to report! (%s) but SKIPPED (TEST: stall)" % current_timestamp.strftime('%H:%M:%S - %Y/%m/%d'), verbose=True)
    
def afterMQTTConnect():
    print_line('* afterMQTTConnect()', verbose=True)
    #  NOTE: this is run after MQTT connects
    # start our interval timer
    startPeriodTimer()
    # do our first report
    handle_interrupt(0)

# TESTING AGAIN
getNetworkIFs()
#getLastUpdateDateV2()

# TESTING, early abort
#stopAliveTimer()
#exit(0)

afterMQTTConnect()  # now instead of after?

# now just hang in forever loop until script is stopped externally
try:
    while True:
        #  our INTERVAL timer does the work
        sleep(10000)
        
finally:
    # cleanup used pins... just because we like cleaning up after us
    stopPeriodTimer()   # don't leave our timers running!
    stopAliveTimer()

