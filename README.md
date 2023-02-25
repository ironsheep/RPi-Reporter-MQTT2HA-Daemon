# RPi Reporter MQTT2HA Daemon

![Project Maintenance][maintenance-shield]

[![GitHub Activity][commits-shield]][commits]

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

[![GitHub Release][releases-shield]][releases]

A simple Linux python script to query the Raspberry Pi on which it is running for various configuration and status values which it then reports via via [MQTT](https://projects.eclipse.org/projects/iot.mosquitto) to your [Home Assistant](https://www.home-assistant.io/) installation. This allows you to install and run this on each of your RPi's so you can track them all via your own Home Assistant Dashboard.

![Discovery image](./Docs/images/DiscoveryV4.png)

This script should be configured to be run in **daemon mode** continously in the background as a systemd service (or optionally as a SysV init script). Instructions are provided below.


## Table of Contents

On this Page:

- [Features](#features)- key features of this reporter
- [Prerequisites](#prerequisites) 
- [Installation](#installation) - install prerequisites and the daemon project
- [Configuration](#configuration) - configuring the script to talk with your MQTT broker
- [Execution](#execution) - initial run by hand, then setup to run from boot
- [Integration](#integration) - a quick look at what's reported to MQTT about this RPi
- [Troubleshooting](#troubleshooting) - having start up issues?  Check here for common problems

Additional pages:

- [Controlling your RPi from Home Assistant](./RMTECTRL.md) - (Optional) Set up to allow remote control from HA
- [The Associated Lovelace RPi Monitor Card](https://github.com/ironsheep/lovelace-rpi-monitor-card) - This is our companion Custom Lovelace Card that makes displaying this RPi Monitor data very easy.
- [ChangeLog](./ChangeLog) - We've been repairing or adding features to this script as users report issues or wishes. This is our list of changes.


## Features

- Tested on Raspberry Pi's 2/3/4 with Jessie, Stretch and Buster
- Tested with Home Assistant v0.111.0 -> 2021.11.5
- Tested with Mosquitto broker v5.1 - v6.0.1
- Data is published via MQTT
- MQTT discovery messages are sent so RPi's are automatically registered with Home Assistant (if MQTT discovery is enabled in your HA installation)
- MQTT authentication support
- No special/root privileges are required by this mechanism (unless you activate remote commanding from HA)
- Linux daemon / systemd service, sd_notify messages generated

### RPi Device

Each RPi device is reported as:

| Name           | Description                                  |
| -------------- | -------------------------------------------- |
| `Manufacturer` | Raspberry Pi (Trading) Ltd.                  |
| `Model`        | RPi 4 Model B v1.1                           |
| `Name`         | (fqdn) pimon1.home                           |
| `sofware ver`  | OS Name, Version (e.g., Buster v4.19.75v7l+) |

### RPi MQTT Topics

Each RPi device is reported as five topics:

| Name            | Device Class  | Units       | Description                                                                                                                                                                    |
| --------------- | ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `~/monitor`     | 'timestamp'   | n/a         | Is a timestamp which shows when the RPi last sent information, carries a template payload conveying all monitored values (**attach the lovelace custom card to this sensor!**) |
| `~/temperature` | 'temperature' | degrees C   | Shows the latest system temperature                                                                                                                                            |
| `~/disk_used`   | none          | percent (%) | Shows the percent of root file system used                                                                                                                                     |
| `~/cpu_load`    | none          | percent (%) | Shows CPU load % over the last 5 minutes                                                                                                                                       |
| `~/mem_used`    | none          | percent (%) | Shows the percent of RAM used                                                                                                                                                  |

### RPi Monitor Topic

The monitored topic reports the following information:

| Name                | Sub-name           | Description                                                                                                             |
| ------------------- | ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `rpi_model`         |                    | tinyfied hardware version string                                                                                        |
| `ifaces`            |                    | comma sep list of interfaces on board [w,e,b]                                                                           |
| `temperature_c`     |                    | System temperature, in [°C] (0.1°C resolution) Note: this is GPU temp. if available, else CPU temp. (used by HA sensor) |
| `temp_gpu_c`        |                    | GPU temperature, in [°C] (0.1°C resolution)                                                                             |
| `temp_cpu_c`        |                    | CPU temperature, in [°C] (0.1°C resolution)                                                                             |
| `up_time`           |                    | duration since last booted, as [days]                                                                                   |
| `last_update`       |                    | updates last applied, as [date]                                                                                         |
| `fs_total_gb`       |                    | / (root) total space in [GBytes]                                                                                        |
| `fs_free_prcnt`     |                    | / (root) available space [%]                                                                                            |
| `fs_used_prcnt`     |                    | / (root) used space [%] (used by HA sensor)                                                                             |
| `host_name`         |                    | hostname                                                                                                                |
| `fqdn`              |                    | hostname.domain                                                                                                         |
| `ux_release`        |                    | os release name (e.g., buster)                                                                                          |
| `ux_version`        |                    | os version (e.g., 4.19.66-v7+)                                                                                          |
| `reporter`          |                    | script name, version running on RPi                                                                                     |
| `networking`        |                    | lists for each interface: interface name, mac address (and IP if the interface is connected)                            |
| `drives`            |                    | lists for each drive mounted: size in GB, % used, device and mount point                                                |
| `cpu`               |                    | lists the model of cpu, number of cores, etc.                                                                           |
|                     | `hardware`         | - typically the Broadcom chip ID (e.g. BCM2835)                                                                         |
|                     | `model`            | - model description string (e.g., ARMv7 Processor rev 4 (v7l))                                                          |
|                     | `number_cores`     | - number of cpu cores [1,4]                                                                                             |
|                     | `bogo_mips`        | - reported performance of this RPi                                                                                      |
|                     | `serial`           | - serial number of this RPi                                                                                             |
|                     | `load_1min_prcnt`  | - average % cpu load during prior minute (avg per core)                                                                 |
|                     | `load_5min_prcnt`  | - average % cpu load during prior 5 minutes (avg per core)                                                              |
|                     | `load_15min_prcnt` | - average % cpu load during prior 15 minutes (avg per core)                                                             |
| `memory`            |                    | shows the RAM configuration in MB for this RPi                                                                          |
|                     | `size_mb`          | - total memory Size in MBytes                                                                                           |
|                     | `free_mb`          | - available memory in MBytes                                                                                            |
| `mem_used_prcnt`    |                    | shows the amount of RAM currently in use (used by HA sensor)                                                            |
| `reporter`          |                    | name and version of the script reporting these values                                                                   |
| `reporter_releases` |                    | list of latest reporter formal versions                                                                                 |
| `report_interval`   |                    | interval in minutes between reports from this script                                                                    |
| `throttle`          |                    | reports the throttle status value plus interpretation thereof                                                           |
| `timestamp`         |                    | date, time when this report was generated                                                                               |

_NOTE: cpu load averages are divided by the number of cores_

## Prerequisites

An MQTT broker is needed as the counterpart for this daemon.

MQTT is huge help in connecting different parts of your smart home and setting up of a broker is quick and easy. In many cases you've already set one up when you installed Home Assistant.

## Installation

On a modern Linux system just a few steps are needed to get the daemon working.
The following example shows the installation under Debian/Raspbian below the `/opt` directory:

First install extra packages the script needs (select one of the two following commands)

### Packages for Ubuntu, Raspberry pi OS, and the like

```shell
sudo apt-get install git python3 python3-pip python3-tzlocal python3-sdnotify python3-colorama python3-unidecode python3-apt python3-paho-mqtt
```

### Packages for pure Ubuntu

**NOTE** if you are running a **pure Ubuntu** not Raspberry pi OS then you may need to install additional packages to get the binary we use to get the core temperatures and tools to inspec the network interfaces. (_If you are NOT seeing temperatures in your Lovelace RPI Monitor Card this is likely the cause. Or if some of your RPis don't show up in Home Assistant_) Do the following in this case:

```shell
sudo apt-get install libraspberrypi-bin net-tools
```

### Packages for Arch Linux

```shell
sudo pacman -S python python-pip python-tzlocal python-notify2 python-colorama python-unidecode python-paho-mqtt python-requests inetutils 
```

**NOTE**: *for users of Arch Linux the number of updates available will NOT be reported (will always show as '-1'.) This is due to Arch Linux not using the apt package manager.*

### With these extra packages installed, verify access to network information

The Daemon script needs access to information about how your RPi connects to the network. It uses `ifconfig(8)` to look up connection names and get the RPi IP address, etc.

Let's run `ifconfig` to insure you have it installed.

```shell
# run ifconfig(8) to see your RPi networking info
ifconfig
eth0: flags=4099<UP,BROADCAST,MULTICAST>  mtu 1500
        ether xx:xx:xx:xx:xx:xx  txqueuelen 1000  (Ethernet)
        RX packets 0  bytes 0 (0.0 B)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 0  bytes 0 (0.0 B)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0
        inet6 ::1  prefixlen 128  scopeid 0x10<host>
        loop  txqueuelen 1000  (Local Loopback)
        RX packets 41342  bytes 2175319 (2.0 MiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 41342  bytes 2175319 (2.0 MiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet xxx.xxx.xxx.xxx  netmask 255.255.255.0  broadcast xxx.xxx.xxx.xxx
        inet6 ... {omitted} ...
        inet6 ... {omitted} ...
        ether xx:xx:xx:xx:xx:xx  txqueuelen 1000  (Ethernet)
        RX packets 1458134  bytes 344599963 (328.6 MiB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 299694  bytes 51281531 (48.9 MiB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

```

If you are seeing output from the `ifconfig` tool then continue on with the following steps.  If you don't you may have missed installing `net-utils` in an earlier step.

### Now finish with the script install

Now that the extra packages are installed let's install our script and any remaining supporting python modules.

```shell
sudo git clone https://github.com/ironsheep/RPi-Reporter-MQTT2HA-Daemon.git /opt/RPi-Reporter-MQTT2HA-Daemon

cd /opt/RPi-Reporter-MQTT2HA-Daemon
sudo pip3 install -r requirements.txt
```

**WARNING:** If you choose to install these files in a location other than `/opt/RPi-Reporter-MQTT2HA-Daemon`, you will need to modify some of the control files which are used when setting up to run this script automatically. The following files:

- **rpi-reporter** - Sys V init script
- **isp-rpi-reporter.service** - Systemd Daemon / Service description file

... need to have any mention of `/opt/RPi-Reporter-MQTT2HA-Daemon` changed to your install location **before you can run this script as a service.**

## Configuration

To match personal needs, all operational details can be configured by modifying entries within the file [`config.ini`](config.ini.dist).
The file needs to be created first: (_in the following: if you don't have vim installed you might try nano_)

```shell
sudo cp /opt/RPi-Reporter-MQTT2HA-Daemon/config.{ini.dist,ini}
sudo vim /opt/RPi-Reporter-MQTT2HA-Daemon/config.ini
```

You will likely want to locate and configure the following (at a minimum) in your config.ini:

```shell
fallback_domain = {if you have older RPis that dont report their fqdn correctly}
# ...
hostname = {your-mqtt-broker}
# ...
discovery_prefix = {if you use something other than 'homeassistant'}
# ...
base_topic = {your home-assistant base topic}

# ...
username = {your mqtt username if your setup requires one}
password = {your mqtt password if your setup requires one}

```

Now that your config.ini is setup let's test!

## Execution

### Initial Test

A first test run is as easy as:

```shell
python3 /opt/RPi-Reporter-MQTT2HA-Daemon/ISP-RPi-mqtt-daemon.py
```

**NOTE:** _it is a good idea to execute this script by hand this way each time you modify the config.ini. By running after each modification the script can tell you through error messages if it had any problems with any values in the config.ini file, or any missing values. etc._``

Using the command line argument `--config`, a directory where to read the config.ini file from can be specified, e.g.

```shell
python3 /opt/RPi-Reporter-MQTT2HA-Daemon/ISP-RPi-mqtt-daemon.py --config /opt/RPi-Reporter-MQTT2HA-Daemon
```

### Preparing to run full time

In order to have your HA system know if your RPi is online/offline and when it last reported-in then you must set up this script to run as a system service.

**NOTE:** Daemon mode must be enabled in the configuration file (default).

But first, we need to grant access to some hardware for the user account under which the sevice will run.

### Set up daemon account to allow access to temperature values

By default this script is run as user:group **daemon:daemon**. As this script requires access to the GPU you'll want to add access to it for the daemon user as follows:

```shell
# list current groups
groups daemon
$ daemon : daemon

# add video if not present
sudo usermod daemon -a -G video

# list current groups
groups daemon
$ daemon : daemon video
#                 ^^^^^ now it is present
```

### Choose Run Style

You can choose to run this script as a `systemd service` or as a `Sys V init script`. If you are on a newer OS than `Jessie` or if as a system admin you are just more comfortable with Sys V init scripts then you can use the latter style.

Let's look at how to set up each of these forms:

#### Run as Systemd Daemon / Service (_for Raspian/Raspberry pi OS newer than 'jessie'_)

(**Heads Up** _We've learned the hard way that RPi's running `jessie` won't restart the script on reboot if setup this way, Please set up these RPi's using the init script form shown in the next section._)

Set up the script to be run as a system service as follows:

```shell
sudo ln -s /opt/RPi-Reporter-MQTT2HA-Daemon/isp-rpi-reporter.service /etc/systemd/system/isp-rpi-reporter.service

sudo systemctl daemon-reload

# tell system that it can start our script at system startup during boot
sudo systemctl enable isp-rpi-reporter.service

# start the script running
sudo systemctl start isp-rpi-reporter.service

# check to make sure all is ok with the start up
sudo systemctl status isp-rpi-reporter.service
```

**NOTE:** _Please remember to run the 'systemctl enable ...' once at first install, if you want your script to start up every time your RPi reboots!_

#### Run as Sys V init script (_your RPi is running 'jessie' or you just like this form_)

In this form our wrapper script located in the /etc/init.d directory and is run according to symbolic links in the `/etc/rc.x` directories.

Set up the script to be run as a Sys V init script as follows:

```shell
sudo ln -s /opt/RPi-Reporter-MQTT2HA-Daemon/rpi-reporter /etc/init.d/rpi-reporter

# configure system to start this script at boot time
sudo update-rc.d rpi-reporter defaults

# let's start the script now, too so we don't have to reboot
sudo /etc/init.d/rpi-reporter start

# check to make sure all is ok with the start up
sudo /etc/init.d/rpi-reporter status
```

### Update to latest

Like most active developers, we periodically upgrade our script. Use one of the following list of update steps based upon how you are set up.

#### Systemd commands to perform update

If you are setup in the systemd form, you can update to the latest we've published by following these steps:

```shell
# go to local repo
cd /opt/RPi-Reporter-MQTT2HA-Daemon

# stop the service
sudo systemctl stop isp-rpi-reporter.service

# get the latest version
sudo git pull

# reload the systemd configuration (in case it changed)
sudo systemctl daemon-reload

# restart the service with your new version
sudo systemctl start isp-rpi-reporter.service

# if you want, check status of the running script
systemctl status isp-rpi-reporter.service

```

#### SysV init script commands to perform update

If you are setup in the Sys V init script form, you can update to the latest we've published by following these steps:

```shell
# go to local repo
cd /opt/RPi-Reporter-MQTT2HA-Daemon

# stop the service
sudo /etc/init.d/rpi-reporter stop

# get the latest version
sudo git pull

# restart the service with your new version
sudo /etc/init.d/rpi-reporter start

# if you want, check status of the running script
sudo /etc/init.d/rpi-reporter status

```

## Integration

When this script is running data will be published to the (configured) MQTT broker topic "`raspberrypi/{hostname}/...`" (e.g. `raspberrypi/picam01/...`).

An example:

```json
{
  "info": {
    "timestamp": "2023-02-23T15:38:43-07:00",
    "rpi_model": "RPi 4 Model B r1.5",
    "ifaces": "e,w,b",
    "host_name": "pip2iotgw",
    "fqdn": "pip2iotgw.home",
    "ux_release": "bullseye",
    "ux_version": "5.15.84-v8+",
    "up_time": "10 days,  35 min",
    "last_update": "2023-02-23T15:04:15-07:00",
    "fs_total_gb": 32,
    "fs_free_prcnt": 81,
    "fs_used_prcnt": 19,
    "networking": {
      "eth0": {
        "mac": "e4:5f:01:f8:18:01",
        "rx_data": 0,
        "tx_data": 0
      },
      "wlan0": {
        "IP": "192.168.100.196",
        "mac": "e4:5f:01:f8:18:02",
        "rx_data": 6948,
        "tx_data": 977
      }
    },
    "drives": {
      "root": {
        "size_gb": 32,
        "used_prcnt": 19,
        "device": "/dev/root",
        "mount_pt": "/"
      }
    },
    "memory": {
      "size_mb": 1849,
      "free_mb": 806
    },
    "mem_used_prcnt": 56,
    "cpu": {
      "hardware": "BCM2835",
      "model": "",
      "number_cores": 4,
      "bogo_mips": "432.00",
      "serial": "1000000081ae88c7",``
      "load_1min_prcnt": 0.5,
      "load_5min_prcnt": 0.8,
      "load_15min_prcnt": 3.8
    },
    "throttle": [
      "throttled = 0x0",
      "Not throttled"
    ],
    "temperature_c": 28.2,
    "temp_gpu_c": 28.2,
    "temp_cpu_c": 29.2,
    "reporter": "ISP-RPi-mqtt-daemon v1.7.5",
    "reporter_releases": "v1.7.5,v1.7.2,v1.7.3,v1.7.4",
    "report_interval": 5
  }
}
```

**NOTE:** Where there's an IP address that interface is connected.  Also, there are new `tx_data` and `rx_data` values which show traffic in bytes for this reporting interval for each network interface.

This data can be subscribed to and processed by your home assistant installation. How you build your RPi dashboard from here is up to you!


## Troubleshooting

### Issue: Some of my RPi's don't show up in HA

Most often fix: _install the missing package._

We occasionaly have reports of users with more than one RPi on their network but only one shows up in Home Assistant. This is most often caused when this script generats a non-unique id for the RPi's. This in turn is most often caused by an inability to get network interface details. I've just updated the install to ensure that we have net-tools package installed. On Raspberry Pi OS this package is already present while on Ubuntu this is not installed by default. If you can successfully run ifconfig(8) then you have what's needed. If not then simply run `sudo apt-get install net-tools`.

### Issue: I removed the RPi sensor from HA now the RPi won't come back

Most often fix: _reboot the missing RPi._

When you remove a sensor from Home Assistant it tells the MQTT broker to 'forget' everything it knows about the RPi.  Some of the information is actually `stored by the MQTT broker` so it is available while the RPi is offline.  Our Daemon script only broadcasts this `stored` information when it is first started.  As a result the RPi will not re-appear after delete from Home Assistant until you reboot the RPi in question. (or, alternatively, stop then restart the script.). You may find reboot easier to do.

To reboot:

```bash
sudo shutdown -r now
```

To, instead, restart the Daemon:

```bash
sudo systemctl stop isp-rpi-reporter.service
sudo systemctl start isp-rpi-reporter.service

```

### General debug

The deamon script can be run my hand while enabling debug and verbose messaging:

```shell
# first stop the running daemon
sudo systemctl stop isp-rpi-reporter.service

# now run the daemon with Debug and Verbose options enabled
python3 /opt/RPi-Reporter-MQTT2HA-Daemon/ISP-RPi-mqtt-daemon.py -d -v
```

This let's you inspect many of the values the script is going to use and to see the data being sent to the MQTT broker.

Then remember to restart the daemon when you are done:

```shell
# now restart the daemon
sudo systemctl start isp-rpi-reporter.service
```

#### Exploring MQTT state

I find [MQTT Explorer](http://mqtt-explorer.com/) to be an excellent tool to use when trying to see what's going on the MQTT messaging any MQTT enabled device.

Alternatively I also use **MQTTBox** when I want to send messages by hand to interact via MQTT. it is affered as a web extension or a native application.


#### Viewing the Daemon logs

When your script is being run as a Daemon it is logging. You can view the log output since last reboot with:

```bash
$ journalctl -b --no-pager -u isp-rpi-reporter.service
```

Alternatively you can create a simple script which you can run any time you want to see the log. Here's my show Daemon log script `showRpiLog`:

```bash
#!/bin/bash

(set -x;journalctl -b --no-pager -u isp-rpi-reporter.service)
```

**NOTE**: *the -b says 'since last boot' the --no-pager says just show it all without breaking it up into pages and requiring the enter key press for each page.*

---

> If you like my work and/or this has helped you in some way then feel free to help me out for a couple of :coffee:'s or :pizza: slices!
>
> [![coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/ironsheep) &nbsp;&nbsp; -OR- &nbsp;&nbsp; [![Patreon](./Docs/images/patreon.png)](https://www.patreon.com/IronSheep?fan_landing=true)[Patreon.com/IronSheep](https://www.patreon.com/IronSheep?fan_landing=true)

---

## Contributors

This project is enjoyed by users in many countries. A number of these users have taken the time so submit **pull requests** which contribute changes/fixes to this project.

Thank you to the following github users for taking the time to help make this project function better for all of us!:

- [hobbypunk90](https://github.com/hobbypunk90) - add commanding of RPi from HA
- [OasisOfChaos](https://github.com/OasisOfChaos) - adjust temp. reporting so can work on non-RPi devices like Orange Pi
- [nabeelmoeen](https://github.com/nabeelmoeen) - add memory usage as addiitonal sensor
- [mcarlosro](https://github.com/mcarlosro) - add ip traffic rate for network interfaces
- [Henry-Sir](https://github.com/Henry-Sir) - add cpu usage as addiitonal sensor
- [woodmj74](https://github.com/woodmj74) - changes to reporting correct temperature units
- [dflvunoooooo](https://github.com/dflvunoooooo) - changes to getting last update date

## Credits

Thank you to Thomas Dietrich for providing a wonderful pattern for this project. His project, which I use and heartily recommend, is [miflora-mqtt-deamon](https://github.com/ThomDietrich/miflora-mqtt-daemon)

Thanks to [synoniem](https://github.com/synoniem) for working through the issues with startup as a SystemV init script and for providing 'rpi-reporter' script itself and for identifying the need for support of other boot device forms.

---

## Disclaimer and Legal

> _Raspberry Pi_ is registered trademark of _Raspberry Pi (Trading) Ltd._
>
> This project is a community project not for commercial use.
> The authors will not be held responsible in the event of device failure or simply errant reporting of your RPi status.
>
> This project is in no way affiliated with, authorized, maintained, sponsored or endorsed by _Raspberry Pi (Trading) Ltd._ or any of its affiliates or subsidiaries.

---

### [Copyright](copyright) | [License](LICENSE)

[commits-shield]: https://img.shields.io/github/commit-activity/y/ironsheep/RPi-Reporter-MQTT2HA-Daemon.svg?style=for-the-badge
[commits]: https://github.com/ironsheep/RPi-Reporter-MQTT2HA-Daemon/commits/master
[maintenance-shield]: https://img.shields.io/badge/maintainer-stephen%40ironsheep.biz-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/ironsheep/RPi-Reporter-MQTT2HA-Daemon.svg?style=for-the-badge
[releases]: https://github.com/ironsheep/RPi-Reporter-MQTT2HA-Daemon/releases
