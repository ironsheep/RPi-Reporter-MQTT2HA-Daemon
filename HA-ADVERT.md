# RPi Reporter advertisements to Home Assistant

![Project Maintenance][maintenance-shield]

[![GitHub Activity][commits-shield]][commits]

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

[![GitHub Release][releases-shield]][releases]

## RPi Reporter MQTT2HA Daemon

The RPi Reporter Daemon is a simple Linux python script which queries the Raspberry Pi on which it is running for various configuration and status values which it then reports via via [MQTT](https://projects.eclipse.org/projects/iot.mosquitto) to your [Home Assistant](https://www.home-assistant.io/) installation.

This page describes what is being advertised to Home Assistant.

## Table of Contents

On this Page:

- [Status Endpoints](#mqtt-rpi-status-topics) - shows what changes when the commanding interface is exposed
- [Control Endpoints](#mqtt-rpi-command-topics) - configuring the Daemon to offer the commanding interface

Additional pages:

- [Overall Daemon Instructions](/README.md) - This project top level README
- [The Associated Lovelace RPi Monitor Card](https://github.com/ironsheep/lovelace-rpi-monitor-card) - This is our companion Custom Lovelace Card that makes displaying this RPi Monitor data very easy.
- [ChangeLog](./ChangeLog) - We've been repairing or adding features to this script as users report issues or wishes. This is our list of changes.

## RPi Device

The Daemon already reports each RPi device as:

| Name           | Description                                  |
| -------------- | -------------------------------------------- |
| `Manufacturer` | Raspberry Pi (Trading) Ltd.                  |
| `Model`        | RPi 4 Model B v1.1                           |
| `Name`         | (fqdn) pimon1.home                           |
| `sofware ver`  | OS Name, Version (e.g., Buster v4.19.75v7l+) |

## RPi Daemon config.ini settings

There are a number of settings in our `config.ini` that affect the details of the advertisements to Home Assistant. They are all found in the `[MQTT]` section of the `config.ini`. The following are used for this purpose:

| Name          | Default                 | Description                                      |
| ------------- | ----------------------- | ------------------------------------------------ |
| `hostname`    | configured hostname     | The host name of the RPi                         |
| `base_topic`  | {no default}            | Set this as desired for your installation        |
| `sensor_name` | default "{SENSOR_NAME}" | If you prefer to use some other form set it here |

For the purpose of this document we'll use the following to indicate where these appear in the advertisements.

- placeholders used herein: `{HOSTNAME}`, `{BASE_TOPIC}`, and `{SENSOR_NAME}`.

## MQTT RPi Status Topics

The Daemon also reports five topics for each RPi device:

| Name            | Device Class  | Units       | Description                                                                                                                                                                    |
| --------------- | ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `~/monitor`     | 'timestamp'   | n/a         | Is a timestamp which shows when the RPi last sent information, carries a template payload conveying all monitored values (**attach the lovelace custom card to this sensor!**) |
| `~/temperature` | 'temperature' | degrees C   | Shows the latest system temperature                                                                                                                                            |
| `~/disk_used`   | none          | percent (%) | Shows the percent of root file system used                                                                                                                                     |
| `~/cpu_load`    | none          | percent (%) | Shows CPU load % over the last 5 minutes                                                                                                                                       |
| `~/mem_used`    | none          | percent (%) | Shows the percent of RAM used                                                                                                                                                  |

### The Monitor endpoint

The `~/monitor` advertisement:

```json
{
  "name": "Rpi Monitor {HOSTNAME}",
  "uniq_id": "RPi-e45f01Monf81801_monitor",
  "dev_cla": "timestamp",
  "stat_t": "~/monitor",
  "val_tpl": "{{ value_json.info.timestamp }}",
  "~": "{BASE_TOPIC}/sensor/{SENSOR_NAME}",
  "avty_t": "~/status",
  "pl_avail": "online",
  "pl_not_avail": "offline",
  "ic": "mdi:raspberry-pi",
  "json_attr_t": "~/monitor",
  "json_attr_tpl": "{{ value_json.info | tojson }}",
  "dev": {
    "identifiers": ["RPi-e45f01Monf81801"],
    "manufacturer": "Raspberry Pi (Trading) Ltd.",
    "name": "RPi-{HOSTNAME}.home",
    "model": "RPi 4 Model B r1.5",
    "sw_version": "bullseye 5.15.84-v8+"
  }
}
```

### The Temperature endpoint

The `~/temperature` advertisement:

```json
{
  "name": "Rpi Temp {HOSTNAME}",
  "uniq_id": "RPi-e45f01Monf81801_temperature",
  "dev_cla": "temperature",
  "unit_of_measurement": "°C",
  "stat_t": "~/monitor",
  "val_tpl": "{{ value_json.info.temperature_c }}",
  "~": "{BASE_TOPIC}/sensor/{SENSOR_NAME}",
  "avty_t": "~/status",
  "pl_avail": "online",
  "pl_not_avail": "offline",
  "ic": "mdi:thermometer",
  "dev": {
    "identifiers": ["RPi-e45f01Monf81801"]
  }
}
```

### The Disk Used endpoint

The `~/disk_used` advertisement:

```json
{
  "name": "Rpi Disk Used {HOSTNAME}",
  "uniq_id": "RPi-e45f01Monf81801_disk_used",
  "unit_of_measurement": "%",
  "stat_t": "~/monitor",
  "val_tpl": "{{ value_json.info.fs_used_prcnt }}",
  "~": "{BASE_TOPIC}/sensor/{SENSOR_NAME}",
  "avty_t": "~/status",
  "pl_avail": "online",
  "pl_not_avail": "offline",
  "ic": "mdi:sd",
  "dev": {
    "identifiers": ["RPi-e45f01Monf81801"]
  }
}
```

### The CPU Load endpoint

The `~/cpu_load` advertisement:

```json
{
  "name": "Rpi Cpu Use {HOSTNAME}",
  "uniq_id": "RPi-e45f01Monf81801_cpu_load",
  "unit_of_measurement": "%",
  "stat_t": "~/monitor",
  "val_tpl": "{{ value_json.info.cpu.load_5min_prcnt }}",
  "~": "{BASE_TOPIC}/sensor/{SENSOR_NAME}",
  "avty_t": "~/status",
  "pl_avail": "online",
  "pl_not_avail": "offline",
  "ic": "mdi:cpu-64-bit",
  "dev": {
    "identifiers": ["RPi-e45f01Monf81801"]
  }
}
```

### The Memory Used endpoint

The `~/mem_used` advertisement:

```json
{
  "name": "Rpi Mem Used {HOSTNAME}",
  "uniq_id": "RPi-e45f01Monf81801_mem_used",
  "unit_of_measurement": "%",
  "stat_t": "~/monitor",
  "val_tpl": "{{ value_json.info.mem_used_prcnt }}",
  "~": "{BASE_TOPIC}/sensor/{SENSOR_NAME}",
  "avty_t": "~/status",
  "pl_avail": "online",
  "pl_not_avail": "offline",
  "ic": "mdi:memory",
  "dev": {
    "identifiers": ["RPi-e45f01Monf81801"]
  }
}
```

## MQTT RPi Command Topics

Once the commanding is enabled then the Daemon also reports the commanding interface for the RPi. By default we've provided examples for enabling three commands (See `config.ini.dist`.) This is what the commanding interface looks like when all threee are enabled:

| Name                | Device Class | Description                                                 |
| ------------------- | ------------ | ----------------------------------------------------------- |
| `~/shutdown`        | button       | Send request to this endpoint to shut the RPi down          |
| `~/reboot`          | button       | Send request to this endpoint to reboot the RPi             |
| `~/restart_service` | button       | Send request to this endpoint to restart the Daemon service |

### The shutdown endpoint

The `~/shutdown` Command advertisement:

```json
{
  "name": "Rpi Command {HOSTNAME} Shutdown",
  "uniq_id": "RPi-e45f01Monf81801_shutdown",
  "~": "{BASE_TOPIC}/command/{SENSOR_NAME}",
  "cmd_t": "~/shutdown",
  "json_attr_t": "~/shutdown/attributes",
  "pl_avail": "online",
  "pl_not_avail": "offline",
  "ic": "mdi:power-sleep",
  "dev": {
    "identifiers": ["RPi-e45f01Monf81801"]
  }
}
```

### The Reboot RPi endpoint

The `~/reboot` Command advertisement:

```json
{
  "name": "Rpi Command {HOSTNAME} Reboot",
  "uniq_id": "RPi-e45f01Monf81801_reboot",
  "~": "{BASE_TOPIC}/command/{SENSOR_NAME}",
  "cmd_t": "~/reboot",
  "json_attr_t": "~/reboot/attributes",
  "pl_avail": "online",
  "pl_not_avail": "offline",
  "ic": "mdi:restart",
  "dev": {
    "identifiers": ["RPi-e45f01Monf81801"]
  }
}
```

### The Restart Service endpoint

The `~/restart_service` Command advertisement:

```json
{
  "name": "Rpi Command {HOSTNAME} Restart_Service",
  "uniq_id": "RPi-e45f01Monf81801_restart_service",
  "~": "{BASE_TOPIC}/command/{SENSOR_NAME}",
  "cmd_t": "~/restart_service",
  "json_attr_t": "~/restart_service/attributes",
  "pl_avail": "online",
  "pl_not_avail": "offline",
  "ic": "mdi:cog-counterclockwise",
  "dev": {
    "identifiers": ["RPi-e45f01Monf81801"]
  }
}
```

---

> If you like my work and/or this has helped you in some way then feel free to help me out for a couple of :coffee:'s or :pizza: slices!
>
> [![coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/ironsheep) &nbsp;&nbsp; -OR- &nbsp;&nbsp; [![Patreon](./Docs/images/patreon.png)](https://www.patreon.com/IronSheep?fan_landing=true)[Patreon.com/IronSheep](https://www.patreon.com/IronSheep?fan_landing=true)

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


