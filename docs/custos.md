# Custos: o que é grátis, o que tem free tier e o que é pago

Conferido em **2026-11-04** nas páginas oficiais (link em cada linha). Preço de nuvem muda: confira de novo antes de
contratar. "Não confirmado" = não consegui ver o número na fonte oficial.

## Sumário

- [Resumo](#resumo)
- [100% grátis (self-hosted, open source)](#100-grátis-self-hosted-open-source)
- [Free tier (com limites)](#free-tier-com-limites)
- [Pago](#pago)
- [VPS](#vps)
- [Pontos de atenção](#pontos-de-atenção)

## Resumo

- Tudo o que roda **dentro** do control plane é open source e grátis. O custo é a VPS.
- **Vercel Hobby** e **Tailscale Personal** são grátis, mas a página oficial de cada um diz **uso não comercial**.
  A Easy Goal é empresa: considere Vercel Pro e Tailscale Standard no orçamento do go-live (ver
  [Pontos de atenção](#pontos-de-atenção)).
- Estimativa mínima do go-live: 1 VPS de 2 vCPU/4 GB (US$ 24–30/mês) + Vercel Pro (a partir de US$ 20/mês) +
  Tailscale (US$ 0 se o uso couber no Personal; US$ 8/usuário/mês no Standard).

## 100% grátis (self-hosted, open source)

Licença conferida no repositório oficial (API do GitHub) em 2026-11-04. Custo = só a máquina onde roda.

| Ferramenta | Licença | Observação | Fonte |
|---|---|---|---|
| OpenBao | MPL-2.0 | audit e policy por caminho grátis (no Infisical são Enterprise, ADR 062) | [github.com/openbao/openbao](https://github.com/openbao/openbao) |
| Coolify (self-hosted) | Apache-2.0 | sem limite de servidores | [github.com/coollabsio/coolify](https://github.com/coollabsio/coolify) |
| OpenObserve OSS | AGPL-3.0 | "Free without limits". Sem RBAC, SSO ou audit completo (só no Enterprise). AGPL: rever antes de oferecer como serviço a cliente | [openobserve.ai/downloads](https://openobserve.ai/downloads/) |
| Umami | MIT | sem cookie | [github.com/umami-software/umami](https://github.com/umami-software/umami) |
| Caddy (gateway) | Apache-2.0 | | [github.com/caddyserver/caddy](https://github.com/caddyserver/caddy) |
| Uptime Kuma | MIT | ainda não instalado (ADR 064 fase D) | [github.com/louislam/uptime-kuma](https://github.com/louislam/uptime-kuma) |
| CrowdSec (Security Engine) | MIT | o motor é grátis; o console tem plano Community grátis (limites não informados na página); listas premium são pagas | [github.com/crowdsecurity/crowdsec](https://github.com/crowdsecurity/crowdsec), [crowdsec.net/pricing](https://www.crowdsec.net/pricing) |
| Trivy, gitleaks | Apache-2.0 / MIT | CI (ADR 064 fase C). Licença não reconferida nesta revisão | não confirmado |

## Free tier (com limites)

| Serviço | O que o grátis dá | Limite que importa para nós | Próximo plano | Fonte |
|---|---|---|---|---|
| Tailscale Personal | até 6 usuários, devices ilimitados; Funnel em todos os planos | **"only suitable for non-commercial use"**; Funnel só nas portas 443, 8443 e 10000, banda com limite não informado | Standard US$ 8/usuário/mês; Premium US$ 18 | [tailscale.com/pricing](https://tailscale.com/pricing), [kb/1223/funnel](https://tailscale.com/kb/1223/funnel) |
| Vercel Hobby | US$ 0: 1M requisições CDN, 100 GB de transferência, 1M invocações, 4h de CPU ativa, 1 developer seat, logs de 1h | **"for personal, non-commercial use"** (FAQ); não dá para comprar uso extra | Pro US$ 20/mês, developer seat US$ 20/mês | [vercel.com/pricing](https://vercel.com/pricing) |
| Railway Free | US$ 1/mês de crédito, 1 vCPU/0,5 GB por serviço, logs de 3 dias (trial: US$ 5 únicos por 30 dias) | não serve para produção | Hobby US$ 5/mês (inclui US$ 5 de uso); Pro US$ 20/mês por workspace | [railway.com/pricing](https://railway.com/pricing) |
| Supabase Free | 2 projetos ativos, 500 MB de banco por projeto | **pausa depois de 1 semana sem atividade** | Pro a partir de US$ 25/mês | [supabase.com/pricing](https://supabase.com/pricing) |
| Neon Free | 100 projetos, 100 CU-hora/projeto/mês, 1 GB por projeto (20 GB no total), escala a zero | permanente, sem cartão | Launch: pago por uso (~US$ 15/mês num banco pequeno, segundo a página) | [neon.com/pricing](https://neon.com/pricing) |
| Cloudflare R2 | 10 GB-mês, 1M operações classe A, 10M classe B; **download grátis** | só a classe Standard entra no grátis | US$ 0,015/GB-mês | [developers.cloudflare.com/r2/pricing](https://developers.cloudflare.com/r2/pricing/) |
| Bitwarden | Password Manager individual grátis (senhas e devices ilimitados); existe organização grátis | limites da organização grátis não aparecem na página | Teams US$ 4/usuário/mês; Families US$ 3,99/mês (6 pessoas) | [bitwarden.com/pricing/business](https://bitwarden.com/pricing/business/) |
| GitHub Free (org) | Actions: US$ 12/mês de compute incluído em repo privado (~2.000 min Linux 2-core); repo público e runner self-hosted grátis; 500 MB de Packages; Dependabot security e version updates | sem forma de pagamento, o Actions para quando acaba a cota | Team US$ 4/usuário/mês; minuto extra Linux 2-core US$ 0,006 | [docs.github.com (Actions billing)](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [github.com/pricing](https://github.com/pricing) |
| OpenObserve Enterprise | grátis até 50 GB/dia de ingestão (licença EULA), com RBAC e SSO | não é open source; avaliar se o RBAC justificar | — | [openobserve.ai/downloads](https://openobserve.ai/downloads/) |
| Oracle Cloud Always Free | Ampere A1: 2 OCPU + 12 GB (1.500 OCPU-hora e 9.000 GB-hora/mês) | **só na home region**; instância ociosa por 7 dias (CPU, rede e memória < 20%) pode ser recuperada | pago por uso | [docs.oracle.com (Always Free)](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) |
| AWS Lightsail | a página diz que dá para começar grátis pelo AWS Free Tier | quantos meses e quais planos: **não confirmado** | ver [VPS](#vps) | [aws.amazon.com/lightsail/pricing](https://aws.amazon.com/lightsail/pricing/) |
| Discord | webhooks de canal (alertas) sem custo | não conferido em página de preço | — | não confirmado |

## Pago

| Serviço | Quando passa a custar | Preço conferido |
|---|---|---|
| VPS do control plane | desde o go-live | US$ 24–30/mês (2 vCPU/4 GB), ver [vps.md](vps.md) |
| VPS dev compartilhada e VPS prd por projeto | na migração da Railway | idem, por VPS |
| Vercel Pro | uso comercial dos fronts | US$ 20/mês; developer seat US$ 20/mês (se o plano já inclui 1 seat: não confirmado) |
| Tailscale Standard | uso comercial ou mais de 6 usuários | US$ 8/usuário/mês |
| Railway | até desligar (etapa 4 do go-live) | Hobby US$ 5 / Pro US$ 20 + uso |
| Supabase Pro | projetos de produção que não podem pausar | a partir de US$ 25/mês |
| GitHub Actions extra | passar dos ~2.000 min/mês em repo privado | US$ 0,006/min (Linux 2-core) |

## VPS

Preço do plano 2 vCPU / 4 GB em cada provedor: tabela completa em [vps.md](vps.md#comparação-2-vcpu--4-gb).

## Pontos de atenção

1. **Vercel Hobby não é comercial.** Fronts de produto com receita (app-front, vaygo-web, LPs de venda) precisam do
   Pro para ficar dentro dos termos. Confira em que plano está cada time hoje.
2. **Tailscale Personal não é comercial.** O Funnel funciona no Personal, mas a tailnet da Easy Goal operando
   clientes é uso comercial. Orçar o Standard (US$ 8 por usuário humano; servidores com tag não são usuários).
   Confirmar com o suporte da Tailscale se só o fundador como usuário cabe em algum plano grátis comercial: **não
   confirmado**.
3. **OpenObserve AGPL:** uso interno sem problema. Oferecer o OpenObserve modificado como serviço a cliente (painel
   white-label) pede revisão de licença.
4. **Supabase Free pausa** depois de 1 semana sem atividade: nada de produção nele.
5. **Oracle Always Free** pode recuperar a instância ociosa, e o control plane fica ocioso quase sempre: não usar para
   o cofre.
