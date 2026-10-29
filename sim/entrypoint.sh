#!/bin/sh
# sshd + dockerd em primeiro plano (sem systemd). Registry local do ensaio aceito sem TLS.
set -e
/usr/sbin/sshd
exec dockerd --insecure-registry 172.30.50.30:5000 --host unix:///var/run/docker.sock
