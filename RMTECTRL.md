# Setting up RPi Control from Home Assistant

![Project Maintenance][maintenance-shield]

[![GitHub Activity][commits-shield]][commits]

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

[![GitHub Release][releases-shield]][releases]

## RPi Reporter MQTT2HA Daemon

The RPi Reporter Daemon is a simple Linux python script which queries the Raspberry Pi on which it is running for various configuration and status values which it then reports via via [MQTT](https://projects.eclipse.org/projects/iot.mosquitto) to your [Home Assistant](https://www.home-assistant.io/) installation. 

This page describes how to enable control features over your RPi which would allow you to shutdown or reboot your RPi from within Home Assistant.  Enabling this feature allows you to add buttons to your RPi display in HA (e.g., press a button to reboot your RPi) and it also activates the MQTT listening features so that the RPi can hear the request and run the associated script (e.g., reboot)

In order for this to work you need to make a few adjustments on each RPi you wish to control:

- Enable optional settings in your `config.ini`
- Add permissions to run each command for the user underwhich the Daemon script runs
- Add a card on Home Assistant which displays the control button

This page will walk you through each of these steps.

## Table of Contents

On this Page:

- [Updates to MQTT Interface](#mqtt-interface-when-commanding-is-enabled) - shows what changes when the commanding interface is exposed
- [Script Configuration](#configuring-the-daemon) - configuring the Daemon to offer the commanding interface
- [Permissions Configuration](#enabling-the-daemon-to-run-external-commands) - allow the Daemon to run the new commands
- [Add initial card to HA]() - create your first button in Home Assistant allowing you to reboot your RPi

Additional pages:

- [Overall Daemon Instructions](/README.md) - This project top level README
- [The Associated Lovelace RPi Monitor Card](https://github.com/ironsheep/lovelace-rpi-monitor-card) - This is our companion Custom Lovelace Card that makes displaying this RPi Monitor data very easy.
- [ChangeLog](./ChangeLog) - We've been repairing or adding features to this script as users report issues or wishes. This is our list of changes.

## MQTT Interface when commanding is enabled

### RPi Device

The Daemon already reports each RPi device as:

| Name           | Description                                  |
| -------------- | -------------------------------------------- |
| `Manufacturer` | Raspberry Pi (Trading) Ltd.                  |
| `Model`        | RPi 4 Model B v1.1                           |
| `Name`         | (fqdn) pimon1.home                           |
| `sofware ver`  | OS Name, Version (e.g., Buster v4.19.75v7l+) |

### RPi MQTT Topics

The Daemon also reports five topics for each RPi device:

| Name            | Device Class  | Units       | Description                                                                                                                                                                    |
| --------------- | ------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `~/monitor`     | 'timestamp'   | n/a         | Is a timestamp which shows when the RPi last sent information, carries a template payload conveying all monitored values (**attach the lovelace custom card to this sensor!**) |
| `~/temperature` | 'temperature' | degrees C   | Shows the latest system temperature                                                                                                                                            |
| `~/disk_used`   | none          | percent (%) | Shows the percent of root file system used                                                                                                                                     |
| `~/cpu_load`    | none          | percent (%) | Shows CPU load % over the last 5 minutes                                                                                                                                       |
| `~/mem_used`    | none          | percent (%) | Shows the percent of RAM used                                                                                                                                                  |

### RPi MQTT Command Topics

Once the commanding is enable then the Daemon also reports the commanding interface for the RPi. By default we've provided examples for enabling three commands (See `config.ini.dist`.) This is what the commanding interface looks like when all threee are enabled:

| Name            | Device Class  |  Description                                                                                                                                                                    |
| --------------- |  ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `~/shutdown` | button |  Send request to this endpoint to shut the RPi down                                                                                                                                          |
| `~/reboot`   | button          | Send request to this endpoint to reboot the RPi                                                                                                                                    |
| `~/restart_service`    | button          |  Send request to this endpoint to restart the Daemon service                                                     

## Configuring the Daemon

By adding more information to your configuration `config.ini` you will now be able to add and execute commands in the monitored Raspberry Pis using MQTT, meaning yes, from buttons in your Home Assistant interface!

We've provided examples in `config.ini.dist` in the `[Commands]` section

### New configuration options

Added the new `[Commands]` section to `config.ini`.
An example to reboot or shutdown the Pi:

```shell
[Commands]
shutdown = /usr/bin/sudo /sbin/shutdown -h now 'shutdown rqst via MQTT'
reboot = /usr/bin/sudo /sbin/shutdown -r now 'reboot rqst via MQTT'
restart_service = /usr/bin/sudo systemctl restart {}
```

*NOTE* the message in the `{action} rqst via MQTT` message is logged in `/var/log/auth.log` so one can keep track of when commands are executed via MQTT.
  
*If you wish, you can simply add all three that we provide in the examples.*


## Enabling the Daemon to run external commands

By default we want to keep our RPi security very tight. To that end we actually specify each command that we want the Daemon to be able to execute.  We do this my making changes to the sudo(8) control file `/etc/sudoers`

The "daemon" user proposed to start the daemon in the installation instructions doesn't have enough privileges to reboot or 
power down the computer. A possible workaround is to give permissions to daemon to the commands we want to execute using
the sudoers configuration file:

  ```shell
  # edit sudoers file
  sudo vim /etc/sudoers
  
  # add the following lines at the bottom.
  # note that every service that we want to allow to restart must be specified here
  daemon <raspberrypihostname> =NOPASSWD: /usr/bin/systemctl restart isp-rpi-reporter,/sbin/shutdown
  ```

NOTE: In some systems the path for `systemctl` / `reboot` / `shutdown` can be different.  Make sure the path you specify is correct for your system.

You can do a quick check of what the actual path is by using the `type` command:

```bash
$ type shutdown
shutdown is /sbin/shutdown
```

Additionally, the daemon user needs permission to execute the shell script referenced in the run-script command (and any command referenced there/access to the directories specified). If the script has been created by the standard pi user, a simple workaround could be:

```shell
chown daemon RPi-mqtt-daemon-script.sh
```


## Verifying your configuration

After getting this configured you'll want to verify that everying is configured correctly.  I recommend the following steps (it's what I do...):

- Restart the daemon
- Use a tool like [MQTT Explorer](http://mqtt-explorer.com/) to verifiy that the new MQTT command interface appeared
- Build a quick card to test a command from HA
- Ensure the action occurred, if you were logged in did you see a 'wall message'?
- Verify the message appeared in the logs

Let's go into a bit more detail for some of these steps.

### Restart the daemon

You'll need to restart the Daemon or reboot the RPi to get your changes to take effect.
Then you'll want to see if the new control interface is exposed.  I check out what's appearing in MQTT by using a tool like [MQTT Explorer](http://mqtt-explorer.com/).

### Build a quick card to test a command from HA

Refer to the [Lovelace RPi Monitor Card](https://github.com/ironsheep/lovelace-rpi-monitor-card) page for details but there is a [specific example button card](https://github.com/ironsheep/lovelace-rpi-monitor-card#example-control-of-your-rpi-avail-in-daemon-v180-and-later)

This was originally built by copying the card suggested by looking at the RPi Device as discovered by home assistant.  In that display it shows an example interface card and allows you to copy the suggestion to your clipboard.  I then pasted this card into the page yaml where I wanted the card to be shown. I then overrode the names with simple more direct names than the default button names.  That's it. It just worked.

### Ensure the action occurred

Next I pressed the reboot button on the new interface. I was logged into the RPi at the time so when the reboot occurred it kicked me off which told me it was working well.

### Verify the message appeared in the logs

Lastly I wanted to ensure the action was logged so I did a simple grep for "via" in the `/var/log/augh.log` file and sure enough there was the entry.

With this finding i've verified that this is all working for me!
(*now you can do the same!*)


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
