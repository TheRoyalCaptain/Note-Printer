#!/bin/sh
set -eu
mkdir -p /run/cups /var/spool/cups /var/log/cups
cupsd
exec gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 --timeout 45 app:app
