#!/bin/sh
# Sem systemd no container: sshd + dockerd em primeiro plano. Registry do laboratório aceito sem TLS.
set -e
ssh-keygen -A >/dev/null
/usr/sbin/sshd
exec dockerd --insecure-registry 172.30.50.30:5000 --host unix:///var/run/docker.sock
