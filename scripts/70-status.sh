#!/usr/bin/env bash
set -euo pipefail

cao session list
printf '\nDetailed prototype status:\n'
cao session status cao-agent-company --workers
