# OpenBao do control plane (VPS / ensaio). Igual ao cofre local, com TLS (CA própria ou `tailscale cert`).
ui            = true
disable_mlock = true

storage "raft" {
  path    = "/openbao/file"
  node_id = "cp-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/openbao/tls/server.crt"
  tls_key_file  = "/openbao/tls/server.key"
}

api_addr     = "https://127.0.0.1:8200"
cluster_addr = "https://127.0.0.1:8201"

audit "file" "file" {
  options {
    file_path = "/openbao/logs/audit.log"
  }
}
