# VPS: opções, o que roda em cada uma e recomendação

Preços conferidos em **2026-11-04** (link em cada linha). Confira de novo antes de contratar.

## Sumário

- [Quantas VPS e para quê](#quantas-vps-e-para-quê)
- [O que roda no control plane e quanta RAM](#o-que-roda-no-control-plane-e-quanta-ram)
- [Comparação 2 vCPU / 4 GB](#comparação-2-vcpu--4-gb)
- [LGPD e região](#lgpd-e-região)
- [Recomendação (decisões D1 e D2)](#recomendação-decisões-d1-e-d2)
- [Requisitos de qualquer VPS](#requisitos-de-qualquer-vps)

## Quantas VPS e para quê

Topologia do ADR 064. O Coolify gerencia qualquer servidor com SSH e Docker, então dá para misturar provedores.

```
                    ┌──────────────────────────────────────────┐
                    │ VPS do control plane (sua conta)        │
                    │ Coolify · OpenBao · OpenObserve · Umami  │
                    │ gateway de ingestão                      │
                    └──────┬───────────────┬───────────────┬───┘
                           │ SSH/tailnet   │               │
              ┌────────────▼───┐  ┌────────▼───────┐  ┌────▼──────────────────┐
              │ VPS dev        │  │ VPS prd        │  │ VPS do cliente        │
              │ compartilhada  │  │ por projeto EG │  │ (conta dele, ADR 063) │
              │ dev + staging  │  │ uma por app    │  │ conta do cliente      │
              │ de todos       │  │ Stay, api-     │  │                       │
              │                │  │ backend        │  │                       │
              └────────────────┘  └────────────────┘  └───────────────────────┘
```

| VPS | Conta | O que roda | Tamanho inicial |
|---|---|---|---|
| Control plane | sua conta | Coolify, OpenBao, OpenObserve, Umami, gateway. No máximo apps internas e leves, em rede separada | 2 vCPU / 4 GB |
| Dev compartilhada | sua conta | dev e staging de todos os seus projetos, um container e uma rede por app | 2 vCPU / 4 GB (subir se o Ollama vier para cá) |
| Prd por projeto | sua conta | produção de um projeto com receita | 2 vCPU / 4 GB, conforme o projeto |
| Do cliente | cliente | produção do cliente (quando ele já tem VPS própria) | o que o cliente já tem |

Prd de apps com receita e qualquer app de cliente **nunca** ficam no control plane.

## O que roda no control plane e quanta RAM

Limites de memória de `install/observability/compose.yml` e uso medido no laboratório em 2026-11-04 (ocioso,
`docker stats` dentro do `sim-cp`):

| Container | Limite (`mem_limit`) | Uso medido (ocioso) |
|---|---|---|
| OpenObserve | 1 GB (`OPENOBSERVE_MEM`) | 263 MB |
| Umami | 512 MB | 168 MB |
| Postgres do Umami | 256 MB | 36 MB |
| Gateway (Caddy) | 64 MB | 11 MB |
| Coolify (app + db + redis + proxy + sentinel) | sem limite | ~470 MB |
| OpenBao | sem limite | 28 MB |
| **Total** | **1,83 GB** só com limite + Coolify/OpenBao | **~1 GB** |

Leitura: ocioso cabe em 2 GB, mas o OpenObserve cresce com a ingestão até o limite de 1 GB, e o Coolify usa mais
durante builds. Com o sistema (~0,4 GB), o pior caso fica perto de 3–3,5 GB. **4 GB é o mínimo confortável**; 8 GB se
o control plane também for hospedar apps internas.

## Comparação 2 vCPU / 4 GB

| Provedor | Plano | Preço/mês | Região no Brasil | API para automação | Fonte |
|---|---|---|---|---|---|
| DigitalOcean | Droplet Basic 2 vCPU / 4 GB | **US$ 24** | **não** (nenhuma na América do Sul) | sim (API, `doctl`) | [digitalocean.com/pricing/droplets](https://www.digitalocean.com/pricing/droplets) |
| Vultr | Cloud Compute Regular `vc2-2c-4gb` (80 GB, 3 TB) | US$ 20 base; **US$ 30 em São Paulo** | **sim**, São Paulo (`sao`) | sim (API v2) | API pública [api.vultr.com/v2/plans](https://api.vultr.com/v2/plans?type=vc2), campo `location_cost.sao` |
| AWS Lightsail | Linux 2 vCPU / 4 GB (80 GB, IPv4 incluído) | **US$ 24** (a página não mostra preço diferente em SP; transferência cai pela metade, ~2 TB) | **sim**, São Paulo | sim (API/CLI da AWS) | [aws.amazon.com/lightsail/pricing](https://aws.amazon.com/lightsail/pricing/) |
| Magalu Cloud | VM 2 vCPU / 4 GB | **não confirmado** (calculadora não carregou) | **sim** (empresa brasileira) | não confirmado | [magalu.cloud/precos](https://magalu.cloud/precos/) |
| Oracle Cloud | Always Free Ampere A1 (até 2 OCPU / 12 GB) | **US$ 0** | sim (São Paulo e Vinhedo), mas grátis só na home region | sim (OCI API) | [docs.oracle.com (Always Free)](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) |
| Hetzner | CX23 (2 vCPU / 4 GB) | **não confirmado** (página oficial só mostra "a partir de €5,99"; terceiros divergem) | **não** (Alemanha, Finlândia, Singapura, EUA) | sim (API, `hcloud`) | [hetzner.com/cloud](https://www.hetzner.com/cloud) |

Observações:
- **Oracle Always Free:** ARM (as imagens precisam ser multi-arch) e a instância ociosa por 7 dias pode ser
  recuperada. Bom para ensaio, ruim para o cofre.
- **Hetzner** é o mais barato, mas sem Brasil e com latência alta para usuário brasileiro.

## LGPD e região

- Aplicação com dado de saúde trata dado sensível na LGPD. Banco e API de produção dela devem ficar **no
  Brasil**.
- Os logs não levam dado de saúde (o `o pacote de observabilidade` grava IP só como hash por padrão), mas carregam dado
  pessoal (`user_id`, hash de IP). Manter o control plane no Brasil também simplifica a conversa com clientes.
- Latência não importa para o control plane (só operador e sync falam com ele), mas importa para as APIs.

## Recomendação (decisões D1 e D2)

Recomendação (decida no roteiro de go-live da sua conta):

- **D1, control plane:** DigitalOcean, Droplet Basic 2 vCPU / 4 GB, Ubuntu 24.04 (US$ 24/mês). API, firewall e
  Spaces; latência não importa.
- **D2, APIs que saem da Railway:** São Paulo, por LGPD e latência: **Vultr SP** (US$ 30), **Lightsail sa-east-1**
  (US$ 24), **Magalu Cloud** ou **Oracle SP**. O Coolify gerencia qualquer uma.

Ponto novo desta revisão (para o fundador decidir): o Lightsail em São Paulo custa o mesmo que a DO (US$ 24) e
deixaria **tudo** no Brasil, inclusive o control plane. A DO continua válida se a preferência for o painel e o
firewall dela.

## Requisitos de qualquer VPS

- Ubuntu 24.04, acesso root por chave SSH.
- Firewall do provedor só com 22/tcp do seu IP **até** o Tailscale subir; depois, remover (tudo pela tailnet).
- VPS de app que serve tráfego público direto (sem Vercel na frente): `PUBLIC_PORTS="80 443"` no `app-server.sh`.
- Instalação: [instalacao.md](instalacao.md).
