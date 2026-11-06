# Observabilidade: OpenObserve + Umami (`scripts/cp-obs`, ADR 066)

Logs, traces e métricas das apps (OpenObserve) e analytics de produto sem cookie (Umami), no control plane.

## Sumário

- [Serviços](#serviços)
- [Fluxo](#fluxo)
- [Credenciais de admin no cofre](#credenciais-de-admin-no-cofre)
- [Comandos](#comandos)
- [Nas apps: pacote de observabilidade](#nas-apps-pacote-de-observabilidade)
- [Contenção do token de ingestão](#contenção-do-token-de-ingestão)
- [O que o ensaio ensinou](#o-que-o-ensaio-ensinou)
- [Fases](#fases)

## Serviços

Sobem no control plane pelo `install/control-plane.sh` (passo 5/7), com imagem fixada por digest e limite de memória
em tudo (`install/observability/compose.yml`).

| Serviço | Para quê | Acesso | Memória |
|---|---|---|---|
| OpenObserve v1.1.2 | logs OTLP das apps (1 **org por cliente e ambiente**, 1 stream por serviço), painéis, alertas, SQL | UI/API só tailnet (`:5080`) | 1 GB |
| Umami 3.4.1 (+ Postgres 16) | analytics de produto sem cookie (1 site por app/ambiente) | painel só tailnet (`:3300`) | 512 MB + 256 MB |
| gateway (Caddy 2.11.7) | **único ponto público** (Tailscale Funnel → `:8280`): só `POST /api/<org>/v1/{logs,traces,metrics}`, `GET /script.js` e `POST /api/send`. Consulta, login e painéis dão 404 | público | 64 MB |

- Retenção padrão: 30 dias (`OBS_RETENTION_DAYS`).
- Storage local no volume `oo_data`. Para S3/R2 (decisão D3): descomentar o bloco `ZO_S3_*` no compose e preencher no
  `.env` da VPS.
- Endereços no lab e na VPS: [acesso.md](acesso.md#tabela-de-endereços).

## Fluxo

```
 app ── o pacote de observabilidade ── OTLP/HTTP + OBS_OTLP_AUTHORIZATION
   │
   ▼
 gateway (Funnel, público) ── só envio ──▶ OpenObserve org <cliente>_<ambiente>, stream <serviço>
                                    └───▶ Umami /api/send (site <cliente>/<projeto>/<ambiente>)

 operador (tailnet) ──▶ OpenObserve :5080 (SQL, painéis) · Umami :3300
 cp-obs ingest ──▶ cria org + service account ──▶ grava OBS_* em kv/<cli>/<proj>/<env> ──▶ cp-secrets sync
```

## Credenciais de admin no cofre

Depois do 1º install, leve as senhas de admin para o cofre (o `cp-obs` usa elas). O script na VPS escreve **só** a
senha no stdout, direto para o `provider set`.

```bash
ssh root@<cp> bash -s openobserve < install/observability-cred.sh \
  | scripts/cp-secrets provider set <conta> openobserve url=http://<cp>:5080 \
      email=<seu e-mail> ingest_url=https://<cp>.<tailnet>.ts.net --stdin password

ssh root@<cp> bash -s umami < install/observability-cred.sh \
  | scripts/cp-secrets provider set <conta> umami url=http://<cp>:3300 \
      username=admin ingest_url=https://<cp>.<tailnet>.ts.net --stdin password
```

No laboratório, os provedores são `openobserve-sim` e `umami-sim` (no cofre principal) e o `cp-obs` os usa com
`CP_OBS_PROVIDER=openobserve-sim CP_UMAMI_PROVIDER=umami-sim`.

## Comandos

```bash
scripts/cp-obs status                                        # saúde, orgs, streams, service accounts, sites
scripts/cp-obs ingest <cliente>/<projeto>/staging           # org + service account + OBS_* no cofre
scripts/cp-obs ingest <cliente>/<projeto>/staging --rotate  # token novo (o antigo para na hora → sync)
scripts/cp-obs analytics <cliente>/<projeto>/prod --domain seudominio.com.br   # site no Umami
scripts/cp-obs revoke <cliente>                              # offboarding (plan)
scripts/cp-obs revoke <cliente> --apply                      # corta a ingestão e apaga os sites
```

O `ingest` grava em `kv/<cli>/<proj>/<env>`: `OBS_OTLP_ENDPOINT`, `OBS_OTLP_AUTHORIZATION`, `OBS_SERVICE`, `OBS_ENV`
e `OBS_IP_SALT` (os dois últimos só se faltarem). O `analytics` grava `NEXT_PUBLIC_UMAMI_WEBSITE_ID` e
`NEXT_PUBLIC_UMAMI_SRC`. Depois: chaves na allowlist do target e `cp-secrets sync`. Passo a passo em
[Ligar logs num app novo](comandos.md#ligar-logs-num-app-novo).

O `revoke` apaga as service accounts das orgs do cliente (ingestão para na hora) e os sites dele no Umami. Os dados
ficam até a retenção (ou exportar antes, pela UI).

## Nas apps: pacote de observabilidade

Pacote do monorepo (branch `feat/observability`, ainda sem push), sem dependências, Node e Edge.

- Sem variáveis: só escreve JSON no stdout (já melhora os logs da Vercel/Railway).
- Com `OBS_OTLP_*`: envia em lote ao gateway, sem atrasar a resposta.
- Evento `http.request`: método, host, caminho sem query, status, latência, IP conforme o modo, geo, `device`,
  `is_bot`/`bot`, `scan`, `referer_host`, `request_id`, `user_id`. Segredos redigidos.
- Adaptadores: Next (middleware com `waitUntil`, `withObservability`) e Node/Nest (`requestLogger`, `flushOnShutdown`).
- **IP e LGPD:** `OBS_IP_MODE=hash` por padrão (SHA-256 com `OBS_IP_SALT` + prefixo /24 ou /48); `full` só com motivo.
  Header de IP ou geo só é aceito da plataforma configurada (`OBS_PLATFORM`), porque é forjável. Dado de saúde e
  outros dados sensíveis nunca vão para o log.

## Contenção do token de ingestão

Sem RBAC no OpenObserve OSS, o token de ingestão também **lê** a própria org pela API direta. Contenção em 3 camadas:

1. O gateway público só deixa passar envio.
2. **1 org por cliente e ambiente** (`<cli>_<env>`): token de dev vazado não lê prod, e outra org responde 401.
3. **ACL da tailnet:** só o operador alcança `:5080` e `:3300`. As VPS de app falam com o control plane só no que
   precisam (Sentinel `:8000`). Na política do Tailscale:

   ```json
   {"action": "accept", "src": ["group:operadores"], "dst": ["tag:control-plane:5080,3300,8000,8200"]},
   {"action": "accept", "src": ["tag:app-dev", "tag:app-prd"], "dst": ["tag:control-plane:8000"]}
   ```

   **Sem essa ACL, não ligar o Funnel.** O Funnel também exige o atributo `funnel` no `nodeAttrs` da política,
   MagicDNS e HTTPS ligados na tailnet, e só usa as portas 443, 8443 ou 10000.

Ligar o Funnel (na VPS):

```bash
tailscale funnel --bg --https=443 http://127.0.0.1:8280
```

Flood de ingestão é contido pela auth do OpenObserve antes de gravar, `max_size 5MB` no gateway e limite de memória.
Rate limit fica para a O3 (Caddy sem plugin não tem).

## O que o ensaio ensinou

- O token de service account **só sai na criação ou na rotação**; a listagem devolve ele mascarado. Por isso o
  `ingest` reemite quando o cofre não tem o token.
- O identificador da org é aleatório (com maiúsculas): o endpoint guardado no cofre já leva ele.
- O OpenObserve recusa hífen no nome da org: o separador é `_` (`<cliente>_staging`).
- Stream com hífen vira underscore (`minha-api` → `minha_api`) na consulta SQL.
- A senha do root precisa de maiúscula, minúscula, dígito e símbolo (senão o OpenObserve não sobe).
- O Caddyfile é montado como arquivo: o instalador reinicia o gateway quando a regra muda.
- O Umami nasce com `admin/umami`: o instalador troca pela senha do `.env` e falha fechado se a do `.env` não entrar.

## Fases

| Fase | O quê | Estado |
|---|---|---|
| O1 | stack no instalador + gateway + `cp-obs` + pacote | ✅ no lab (instalador do zero e idempotente, allowlist, envio pelo pacote → SQL, `cp-obs` testado) |
| O2 | adoção nos apps da conta | próximo |
| O3 | painéis e alertas em código, audit do OpenBao/sync/rotate → OpenObserve, rate limit no gateway | depois da O2 |
| O4 | access log do Traefik + GeoIP/ASN + CrowdSec nas VPS | depende do go-live |
| O5 | cruzar `user_id` com o CRM da conta | depois |
