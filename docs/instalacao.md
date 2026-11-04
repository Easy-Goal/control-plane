# Instalação: control plane e VPS de app (ADR 064)

Os mesmos scripts no laboratório e na VPS real (Ubuntu 24.04, root). Idempotentes: rodar de novo só corrige.

## Sumário

- [Scripts](#scripts)
- [install/control-plane.sh](#installcontrol-planesh)
- [install/app-server.sh](#installapp-serversh)
- [Pós-instalação do Coolify](#pós-instalação-do-coolify)
- [Roteiro na VPS real (fase F)](#roteiro-na-vps-real-fase-f)
- [Laboratório](#laboratório)
- [Gotchas](#gotchas)

## Scripts

| Script | Onde roda | O que faz |
|---|---|---|
| `install/control-plane.sh` | VPS do control plane | sshd só chave, docker (repo oficial), unattended-upgrades, Tailscale (`TS_AUTHKEY`), ufw só tailnet; Coolify 4.5.3 com arquivos fixados por sha256; pós-instalação (`coolify-post.php`); OpenBao com TLS (CA própria em `/data/cp/ca`); observabilidade |
| `install/coolify-sync-token.sh` | VPS do control plane | token novo do usuário de serviço `cp-sync` (revoga os anteriores) **só no stdout** → `provider set ... --stdin token` |
| `install/observability-cred.sh` | VPS do control plane | senha de admin do OpenObserve ou do Umami **só no stdout** → `provider set easygoal openobserve\|umami ... --stdin password` |
| `install/app-server.sh` | cada VPS de app | sshd só chave, docker, chave do Coolify (`COOLIFY_PUBKEY`), Tailscale com tag, ufw |
| `scripts/cp-coolify` | máquina do operador | `key`, `server add`, `servers`, `service ensure`, `s3 ensure`, `db ensure`, `backup ensure\|now`, `db restore` |
| `scripts/cp-secrets restore <snap>` | máquina do operador | migração do cofre: snapshot do principal → OpenBao novo → abre com as chaves originais |

## install/control-plane.sh

```bash
CP_ADDR=<ip da tailnet> CP_ADMIN_EMAIL=contato@easygoal.com.br bash control-plane.sh
```

| Variável | Obrigatória | O que é |
|---|---|---|
| `CP_ADDR` | sim | endereço pelo qual as VPS de app alcançam o control plane (IP da tailnet; no lab `172.30.50.10`). Vira o IP da instância no Coolify → URL do Sentinel de todo servidor novo |
| `CP_ADMIN_EMAIL` | sim | e-mail do root do Coolify e do admin do OpenObserve |
| `TS_AUTHKEY` | VPS real | entra na tailnet com `tag:control-plane` |
| `BAO_TLS_SANS` | não | SANs extras do certificado do OpenBao, ex.: `DNS:cp.tail1234.ts.net` |
| `GW_BIND` | não | onde o gateway escuta; padrão `127.0.0.1` (o Funnel publica). No lab: `CP_ADDR` |
| `CP_SIM=1` | lab | ensaio em container: pula firewall, unattended-upgrades e Tailscale |

Passos: 1/7 sistema base · 2/7 Coolify · 3/7 pós-instalação · 4/7 OpenBao (TLS) · 5/7 observabilidade · 6/7
conferência · 7/7 próximos passos (impressos no fim, com os comandos prontos).

## install/app-server.sh

```bash
COOLIFY_PUBKEY="ssh-ed25519 AAAA... coolify-cp" SERVER_TAG=app-prd bash app-server.sh
```

| Variável | O que é |
|---|---|
| `COOLIFY_PUBKEY` | chave pública que o Coolify usa para entrar (`scripts/cp-coolify key`) |
| `SERVER_TAG` | tag na tailnet: `app-dev`, `app-prd`, `cliente-<x>`. A ACL decide quem fala com quem |
| `PUBLIC_PORTS` | portas abertas para a internet (ex.: `"80 443"` se a VPS serve tráfego público pelo proxy) |
| `TS_AUTHKEY` | (VPS real) entra na tailnet |
| `CP_SIM=1` | ensaio em container |

O resto (proxy, redes, Sentinel) o próprio Coolify instala ao validar o servidor. O script cria a rede Docker
`coolify` (sem ela o start do banco gerenciado falha antes do proxy existir).

## Pós-instalação do Coolify

O que o ensaio ensinou (automatizado no `coolify-post.php`):

- root criado direto (o seeder valida e-mail por DNS) e com e-mail verificado;
- usuário de serviço `cp-sync` para o token do sync (trocar a senha de um usuário revoga todos os tokens dele);
- onboarding desligado (o time fica em cache por 1h);
- registro fechado; API ligada;
- **IP da instância = endereço na tailnet** (vira a URL do Sentinel de todo servidor remoto).

Senha do root: nunca gerada em claro. Defina com `root:reset-password` (ver [acesso](acesso.md#coolify)).

## Roteiro na VPS real (fase F)

Versão resumida. O roteiro completo, com passos manuais e critério de pronto, está nas
[fases do go-live](go-live-vps-principal.md#fases-do-go-live).

```bash
# 1. na VPS, como root (pasta install/ copiada para /opt/cp-install)
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --authkey=<auth key> --advertise-tags=tag:control-plane
CP_ADDR=$(tailscale ip -4) CP_ADMIN_EMAIL=contato@easygoal.com.br TS_AUTHKEY=<auth key> \
  BAO_TLS_SANS="DNS:<nome>.<tailnet>.ts.net" bash /opt/cp-install/control-plane.sh
```

```bash
# 2. sua máquina: CA + migração do cofre
scp root@<cp>:/data/cp/ca/ca.crt openbao/tls/prod-ca.crt
scripts/cp-secrets backup
CP_BAO_ADDR=https://<cp>:8200 CP_BAO_CACERT=openbao/tls/prod-ca.crt \
  scripts/cp-secrets restore openbao/backups/<snap>      # pede as chaves de unseal digitadas
```

```bash
# 3. daqui em diante, o cofre principal é o da VPS
export CP_BAO_ADDR=https://<cp>:8200 CP_BAO_CACERT=$HOME/projects/easy/control-plane/openbao/tls/prod-ca.crt
scripts/cp-secrets status
```

```bash
# 4. token do sync para o Coolify real
ssh root@<cp> bash -s < install/coolify-sync-token.sh \
  | scripts/cp-secrets provider set easygoal coolify url=http://<cp>:8000 --stdin token --expires "$(date -u -d '+90 days' +%F)"
```

```bash
# 5. cada VPS de app (na VPS) e o cadastro (na sua máquina)
COOLIFY_PUBKEY="<saída de scripts/cp-coolify key>" SERVER_TAG=app-prd TS_AUTHKEY=<auth key> bash /opt/cp-install/app-server.sh
scripts/cp-coolify server add <nome> <ip tailnet>
```

```bash
# 6. services + sync
scripts/cp-coolify service ensure <projeto> <ambiente> <servidor> <nome> <compose.yml>
scripts/cp-secrets sync apply
```

7. Observabilidade: [credenciais de admin](observabilidade.md#credenciais-de-admin-no-cofre), ACL da tailnet e Funnel
   ([contenção](observabilidade.md#contenção-do-token-de-ingestão)).

## Laboratório

`sim/lab.sh up` faz o equivalente aos passos 1, 2, 4, 5 e 6 com `CP_SIM=1` (sem firewall/Tailscale; a rede Docker `172.30.50.0/24` faz o papel
da tailnet) e o `verify` confere servidores, cofre do CP, sync, valor no container e Sentinel.

| Máquina | IP no lab | Porta na sua máquina | Papel |
|---|---|---|---|
| `sim-cp` | `172.30.50.10` | Coolify `8000`, OpenBao `8210`, OpenObserve `5080`, Umami `3300`, gateway `8280` | control plane |
| `sim-vps-dev` | `172.30.50.20` | API staging `3101` | VPS dev compartilhada |
| `sim-vps-prd` | `172.30.50.21` | API prod `3102` | VPS prd do Health Stay |
| `sim-registry` | `172.30.50.30` | `5001` | imagens (no lugar do GHCR até a fase C) |
| `sim-s3` | `172.30.50.40` | — | S3 dos backups (SeaweedFS; o MinIO saiu do Docker Hub) |

Comandos: [comandos.md](comandos.md#laboratório). `sim/lab.sh down` **apaga** o lab (volumes inclusive); o cofre
principal não é tocado.

## Gotchas

- Docker publica portas **por fora do ufw**: publicar no IP da tailnet (`CP_ADDR`) ou atrás do proxy, nunca em `0.0.0.0`.
- O ufw só é aplicado com a tailnet ativa (senão trancaria o SSH pelo IP público).
- Restore de snapshot de outro cluster exige **reiniciar o OpenBao** (a config de selo temporária fica em memória) e
  esperar o estado estável. O `cp-secrets restore` já faz isso.
- O Coolify cria as variáveis do compose vazias (o sync trata como placeholder).
- O Coolify recusa destino S3 em IP privado (proteção SSRF): só o lab libera o IP do S3 dele.
- Num pipe, o `$(...)` do lado direito roda junto com o lado esquerdo: calcule datas antes.
- Imagens fixadas por digest (Coolify por sha256 dos arquivos, OpenBao, OpenObserve, Umami, Caddy): atualizar de
  propósito, conferindo o changelog e com `cp-secrets backup` antes.
