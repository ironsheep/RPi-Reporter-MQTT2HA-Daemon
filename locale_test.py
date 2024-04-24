#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import locale
import sys
from time import time, sleep, localtime, strftime
import argparse

from colorama import init as colorama_init
from colorama import Fore, Back, Style

script_version = "1.0.0"
script_name = 'locale_test.py'
script_info = '{} v{}'.format(script_name, script_version)
project_name = 'RPi Reporter MQTT2HA Daemon'
project_url = 'https://github.com/ironsheep/RPi-Reporter-MQTT2HA-Daemon'

def print_line(text, error=False, warning=False, info=False, verbose=False, debug=False, console=True):
    timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
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

if False:
    # will be caught by python 2.7 to be illegal syntax
    print_line(
        'Sorry, this script requires a python3 runtime environment.', file=sys.stderr)
    os._exit(1)

# Argparse
opt_debug = False
opt_verbose = False

# Argparse
parser = argparse.ArgumentParser(
    description=project_name, epilog='For further details see: ' + project_url)
parser.add_argument("-v", "--verbose",
                    help="increase output verbosity", action="store_true")
parser.add_argument(
    "-d", "--debug", help="show debug output", action="store_true")
parse_args = parser.parse_args()

opt_debug = parse_args.debug
opt_verbose = parse_args.verbose

print_line('--------------------------------------------------------------------', debug=True)
print_line(script_info, info=True)
if opt_verbose:
    print_line('Verbose enabled', info=True)
if opt_debug:
    print_line('Debug enabled', debug=True)



response = locale.getpreferredencoding()
print_line('* locale.getpreferredencoding()=[{}]'.format(response), warning=True)

response = sys.getfilesystemencoding()
print_line('* sys.getfilesystemencoding()=[{}]'.format(response), warning=True)

print_line('* Done', warning=True)
