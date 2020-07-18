#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import _thread
from datetime import datetime
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

script_version = "0.8.0"
script_name = 'ISP-RPi-mqtt-daemon.py'
script_info = '{} v{}'.format(script_name, script_version)
project_name = 'RPi Reporter MQTT2HA Daemon'
project_url = 'https://github.com/ironsheep/RPi-Reporter-MQTT2HA-Daemon'

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
parser.add_argument("-c", '--config_dir', help='set directory where config.ini is located', default=sys.path[0])
parse_args = parser.parse_args()

config_dir = parse_args.config_dir
opt_debug = parse_args.debug
opt_verbose = parse_args.verbose

print_line(script_info, info=True)
if opt_verbose:
    print_line('Verbose enabled', info=True)
if opt_debug:
    print_line('Debug enabled', debug=True)


# Eclipse Paho callbacks - http://www.eclipse.org/paho/clients/python/docs/#callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print_line('MQTT connection established', console=True, sd_notify=True)
        print_line('')  # blank line?!
    else:
        print_line('Connection error with result code {} - {}'.format(str(rc), mqtt.connack_string(rc)), error=True)
        #kill main thread
        os._exit(1)

def on_publish(client, userdata, mid):
    #print_line('Data successfully published.')
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
default_sensor_name = 'rpi-reporter'

base_topic = config['MQTT'].get('base_topic', default_base_topic).lower()
sensor_name = config['MQTT'].get('sensor_name', default_sensor_name).lower()

# report our RPi values every 5min 
min_interval_in_minutes = 2
max_interval_in_minutes = 30
default_interval_in_minutes = 5
interval_in_minutes = config['Daemon'].getint('interval_in_minutes', default_interval_in_minutes)

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

rpi_model = ''
rpi_connections = ''
rpi_hostname = ''
rpi_fqdn = ''
rpi_linux_release = ''
rpi_linux_version = ''
rpi_uptime_raw = ''
rpi_uptime = ''
rpi_last_update_date = ''
rpi_filesystem_space_raw = ''
rpi_filesystem_space = ''
rpi_filesystem_percent = ''
rpi_system_temp = ''

# -----------------------------------------------------------------------------
#  monitor variable fetch routines
#
def getDeviceModel():
    global rpi_model
    global rpi_connections
    out = subprocess.Popen("/bin/cat /proc/device-tree/model | /bin/sed -e 's/\\x0//g'", 
           shell=True,
           stdout=subprocess.PIPE, 
           stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_model = stdout.decode('utf-8').replace('Raspberry ', 'R').replace('i Model ', 'i 1 Model').replace('Rev ', 'r').replace(' Plus ', '+')
    # now decode interfaces
    rpi_connections = '[e,w,b]' # default
    if 'Pi 3 ' in rpi_model:
        if ' A ' in rpi_model:
            rpi_connections = '[w,b]'
        else:
            rpi_connections = '[e,w,b]'
    elif 'Pi 2 ' in rpi_model:
        rpi_connections = '[e]'
    elif 'Pi 1 ' in rpi_model:
        if ' A ' in rpi_model:
            rpi_connections = ''
        else:
            rpi_connections = '[e]'
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
    rpi_fqdn = stdout.decode('utf-8').rstrip()
    print_line('rpi_fqdn=[{}]'.format(rpi_fqdn), debug=True)
    nameParts = rpi_fqdn.split('.')
    rpi_hostname = nameParts[0]
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
    lineParts = rpi_uptime_raw.split(',')
    rpi_uptime = lineParts[0]
    print_line('rpi_uptime=[{}]'.format(rpi_uptime), debug=True)

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
    rpi_filesystem_percent = lineParts[4]
    print_line('rpi_filesystem_percent=[{}]'.format(rpi_filesystem_percent), debug=True)

def getSystemTemperature():
    global rpi_system_temp
    out = subprocess.Popen("/opt/vc/bin/vcgencmd measure_temp | /bin/sed -e 's/\\x0//g'", 
            shell=True,
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_system_temp = stdout.decode('utf-8').rstrip().replace('temp=', '').replace('\'C', '')
    print_line('rpi_system_temp=[{}]'.format(rpi_system_temp), debug=True)

def getLastUpdateDate():
    global rpi_last_update_date
    cmd_string = '/bin/cat {}'.format(update_flag_filespec)
    out = subprocess.Popen(cmd_string, 
            shell=True,
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT)
    stdout,stderr = out.communicate()
    rpi_last_update_date = stdout.decode('utf-8').rstrip()
    if 'No such file' in rpi_last_update_date:
        rpi_last_update_date = 'unknown'
    print_line('rpi_last_update_date=[{}]'.format(rpi_last_update_date), debug=True)

# get our hostnames so we can setup MQTT
getHostnames()
if(sensor_name == default_sensor_name):
    sensor_name = 'rpi-{}'.format(rpi_hostname)

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
lwt_online_val = 'Online'
lwt_offline_val = 'Offline'

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
gw = os.popen("ip -4 route show default").read().split()
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect((gw[2], 0))
ipaddr = s.getsockname()[0]
interface = gw[4]
ether = os.popen("ifconfig " + interface + "| grep ether").read().split()
mac = ether[1]
fqdn = socket.getfqdn()

uniqID = "RPiMon-{}".format(mac.lower().replace(":", ""))

# our RPi Reporter device
LD_MONITOR = "values"

# Publish our MQTT auto discovery
#  table of key items to publish:
detectorValues = OrderedDict([
    (LD_MONITOR, dict(title="RPi Monitor {}".format(rpi_hostname), device_class="timestamp", no_title_prefix="yes", json_values="yes", device_ident="RPi-{}".format(rpi_fqdn)),
])

print_line('Announcing Lightning Detection device to MQTT broker for auto-discovery ...')

base_topic = '{}/sensor/{}'.format(base_topic, sensor_name.lower())
values_topic_rel = '{}/values'.format('~')
values_topic = '{}/values'.format(base_topic) 
activity_topic_rel = '{}/status'.format('~')     # vs. LWT
activity_topic = '{}/status'.format(base_topic)    # vs. LWT

command_topic_rel = '~/set'

for [sensor, params] in detectorValues.items():
    discovery_topic = 'homeassistant/sensor/{}/{}/config'.format(sensor_name.lower(), sensor)
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
    if 'json_values' in params:
        payload['stat_t'] = "~/{}".format(sensor)
        payload['val_tpl'] = "{{{{ value_json.{}.timestamp }}}}".format(sensor)
    payload['~'] = base_topic
    payload['pl_avail'] = lwt_online_val
    payload['pl_not_avail'] = lwt_offline_val
    payload['avty_t'] = activity_topic_rel
    if 'json_values' in params:
        payload['json_attr_t'] = "~/{}".format(sensor)
        payload['json_attr_tpl'] = '{{{{ value_json.{} | tojson }}}}'.format(sensor)
    if 'device_ident' in params:
        payload['dev'] = {
                'identifiers' : ["{}".format(uniqID)],
                'connections' : [["mac", mac.lower()], [interface, ipaddr]],
                'manufacturer' : 'Raspberry Pi (Trading) Ltd.',
                'name' : params['device_ident'],
                'model' : 'Raspberry Pi',
                'sw_version': "v{}".format(script_version)
        }
    else:
         payload['dev'] = {
                'identifiers' : ["{}".format(uniqID)],
         }
    mqtt_client.publish(discovery_topic, json.dumps(payload), 1, retain=True)


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


# -----------------------------------------------------------------------------
#  MQTT Transmit Helper Routines
# -----------------------------------------------------------------------------
SCRIPT_TIMESTAMP = "timestamp"
RPI_MODEL = "model"
RPI_CONNECTIONS = "connections"
RPI_HOSTNAME = "hostname"
RPI_FQDN = "fqdn"
RPI_LINUX_RELEASE = "linux_release" 
RPI_LINUX_VERSION = "linux_version" 
RPI_UPTIME = "uptime"
RPI_DATE_LAST_UPDATE = "update"
RPI_FS_SPACE = "fs_space"
RPI_FS_AVAIL = "fs_available"
RPI_TEMP = "temperature_c"


def send_status(timestamp, nothing):
    rpiData = OrderedDict()
    rpiData[SCRIPT_TIMESTAMP] = timestamp.astimezone().replace(microsecond=0).isoformat()
    rpiData[RPI_MODEL] = rpi_model
    rpiData[RPI_HOSTNAME] = rpi_hostname
    rpiData[RPI_FQDN] = rpi_fqdn
    rpiData[RPI_LINUX_RELEASE] = rpi_linux_release
    rpiData[RPI_LINUX_VERSION] = rpi_linux_version
    rpiData[RPI_UPTIME] = rpi_uptime
    rpiData[RPI_DATE_LAST_UPDATE] = rpi_last_update_date
    rpiData[RPI_FS_SPACE] = rpi_filesystem_space
    rpiData[RPI_FS_AVAIL] = rpi_filesystem_percent
    rpiData[RPI_TEMP] = rpi_system_temp

    _thread.start_new_thread(publishMonitorData, (rpiData, values_topic))

def publishMonitorData(latestData, topic):
    print_line('Publishing to MQTT topic "{}, Data:{}"'.format(topic, json.dumps(latestData)))
    mqtt_client.publish('{}'.format(topic), json.dumps(latestData), 1, retain=False)
    sleep(0.5) # some slack for the publish roundtrip and callback function  


def update_values():
    # nothing here yet
    getUptime()
    getFileSystemSpace()
    getSystemTemperature()
    getLastUpdateDate()

    

# -----------------------------------------------------------------------------

# Interrupt handler
def handle_interrupt(channel):
    sourceID = "<< INTR(" + str(channel) + ")"
    current_timestamp = datetime.now()
    print_line(sourceID + " >> Time to report! (%s)" % current_timestamp.strftime('%H:%M:%S - %Y/%m/%d'), verbose=True)
    # ----------------------------------
    # have PERIOD interrupt!
    update_values()
    # ok, report our new detection to MQTT
    _thread.start_new_thread(send_status, (current_timestamp, ''))
    


getDeviceModel()
getLinuxRelease()
getLinuxVersion()

#stopAliveTimer()
#exit(0)

# start our interval timer
startPeriodTimer()
# do our first report
handle_interrupt(0)

# now just hang in forever loop until script is stopped externally
try:
    while True:
        #  our INTERVAL timer does the work
        sleep(10000)
        
finally:
    # cleanup used pins... just because we like cleaning up after us
    stopPeriodTimer()   # don't leave our timers running!
    stopAliveTimer()

