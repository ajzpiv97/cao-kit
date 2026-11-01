#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' 'Starting CAO server with the tmux backend.'
printf '%s\n' 'Leave this terminal running. Press Ctrl-C to stop the server.'
exec cao-server --terminal tmux
