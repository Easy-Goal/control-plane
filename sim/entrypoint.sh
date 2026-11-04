#!/bin/sh
# Sem systemd no container: sshd + dockerd em primeiro plano. Registry do laboratório aceito sem TLS.
set -e
# cgroup v2 aninhado (mesmo passo do entrypoint oficial docker:dind): move os processos para um subgrupo e
# habilita os controladores, senão containers com limites de recurso (ex.: bancos do Coolify) não sobem.
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
  mkdir -p /sys/fs/cgroup/init
  xargs -rn1 < /sys/fs/cgroup/cgroup.procs > /sys/fs/cgroup/init/cgroup.procs 2>/dev/null || :
  sed -e 's/ / +/g' -e 's/^/+/' < /sys/fs/cgroup/cgroup.controllers > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null || :
fi
# Reinício do Docker Desktop: o container volta com o pid do dockerd anterior em /var/run e o novo recusa subir.
rm -f /var/run/docker.pid /var/run/docker/containerd/containerd.pid
ssh-keygen -A >/dev/null
/usr/sbin/sshd
exec dockerd --insecure-registry 172.30.50.30:5000 --host unix:///var/run/docker.sock
