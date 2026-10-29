# OpenBao do control plane (ADR 062). Nó único com storage raft; HA/multi-nó só se precisar.
ui            = true
disable_mlock = true   # recomendado com raft; o container não precisa de IPC_LOCK

storage "raft" {
  path    = "/openbao/file"
  node_id = "cp-1"
}

# Só HTTP porque a porta é publicada apenas em 127.0.0.1. Na VPS: atrás da tailnet com TLS.
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr     = "http://127.0.0.1:8200"
cluster_addr = "http://127.0.0.1:8201"

# Audit declarativo (o OpenBao 2.x não habilita audit pela API). JSON por linha, valores em HMAC.
# Etapa 5: um coletor (Alloy/Promtail) lê este volume e manda para o Loki.
audit "file" "file" {
  options {
    file_path = "/openbao/logs/audit.log"
  }
}
