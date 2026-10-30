# Funções comuns dos instaladores (control-plane.sh, app-server.sh). Idempotentes; sem segredo na saída.

step() { printf '\n== %s\n' "$*"; }
ok()   { printf '  [ok] %s\n' "$*"; }
warn() { printf '  [aviso] %s\n' "$*"; }
die()  { printf '  [erro] %s\n' "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" = 0 ] || die "rodar como root"; }

# SSH só com chave; root só por chave (o Coolify entra como root).
harden_ssh() {
  local c=/etc/ssh/sshd_config.d/10-cp.conf
  if [ ! -f $c ]; then
    mkdir -p /etc/ssh/sshd_config.d
    printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' > $c
    if command -v systemctl >/dev/null && systemctl is-active -q ssh 2>/dev/null; then systemctl reload ssh; fi
    ok "sshd: só chave"
  fi
}

authorize_key() {
  mkdir -p /root/.ssh && chmod 700 /root/.ssh
  touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
  grep -qF "$1" /root/.ssh/authorized_keys || { echo "$1" >> /root/.ssh/authorized_keys; ok "chave autorizada: ${1##* }"; }
}

# Docker Engine pelo repositório oficial (apt + chave assinada), sem `curl | sh`.
ensure_docker() {
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then return; fi
  command -v docker >/dev/null || {
    apt-get update -qq && apt-get install -y -qq ca-certificates curl >/dev/null
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq && apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null
  }
  systemctl enable --now docker >/dev/null 2>&1 || true
  docker info >/dev/null 2>&1 || die "docker não respondeu"
  ok "docker $(docker version --format '{{.Server.Version}}')"
}

ensure_unattended_upgrades() {
  dpkg -s unattended-upgrades >/dev/null 2>&1 || apt-get install -y -qq unattended-upgrades >/dev/null
  printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > /etc/apt/apt.conf.d/20auto-upgrades
  ok "atualizações de segurança automáticas"
}

# Tailscale pelo repositório oficial; entra na tailnet só se TS_AUTHKEY vier (chave efêmera/pré-aprovada com a tag).
ensure_tailscale() {
  local tag=$1
  if ! command -v tailscale >/dev/null; then
    . /etc/os-release
    curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/$VERSION_CODENAME.noarmor.gpg" -o /usr/share/keyrings/tailscale-archive-keyring.gpg
    curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/$VERSION_CODENAME.tailscale-keyring.list" -o /etc/apt/sources.list.d/tailscale.list
    apt-get update -qq && apt-get install -y -qq tailscale >/dev/null
  fi
  if tailscale status >/dev/null 2>&1; then ok "tailscale: $(tailscale ip -4 | head -1)"; return; fi
  [ -n "${TS_AUTHKEY:-}" ] || { warn "tailscale instalado, fora da tailnet (definir TS_AUTHKEY ou rodar tailscale up)"; return; }
  tailscale up --authkey "$TS_AUTHKEY" --advertise-tags="tag:$tag" --ssh=false >/dev/null
  ok "tailscale: $(tailscale ip -4 | head -1) (tag:$tag)"
}

# Entrada só pela tailnet (+ portas públicas pedidas, ex. "80 443" numa VPS de app com proxy).
# Atenção: portas publicadas pelo Docker passam por fora do ufw — publicar no IP da tailnet ou via proxy.
ensure_ufw_tailnet_only() {
  # Sem tailnet ativa, fechar a entrada trancaria o próprio SSH pelo IP público.
  tailscale status >/dev/null 2>&1 || { warn "ufw não aplicado: tailnet inativa (rodar de novo depois do tailscale up)"; return; }
  dpkg -s ufw >/dev/null 2>&1 || apt-get install -y -qq ufw >/dev/null
  ufw --force reset >/dev/null
  ufw default deny incoming >/dev/null && ufw default allow outgoing >/dev/null
  ufw allow in on tailscale0 >/dev/null
  for p in ${PUBLIC_PORTS:-}; do ufw allow "$p/tcp" >/dev/null; done
  ufw --force enable >/dev/null
  ok "ufw: entrada só pela tailnet${PUBLIC_PORTS:+ + públicas $PUBLIC_PORTS}"
}

ensure_packages() {
  local miss=()
  for p in "$@"; do dpkg -s "$p" >/dev/null 2>&1 || miss+=("$p"); done
  [ ${#miss[@]} -eq 0 ] || { apt-get update -qq && apt-get install -y -qq "${miss[@]}" >/dev/null && ok "pacotes: ${miss[*]}"; }
}
