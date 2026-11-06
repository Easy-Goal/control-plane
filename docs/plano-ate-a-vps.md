# Plano até contratar a VPS

O que você faz manualmente e o que o Claude executa em paralelo. Criado em 2026-11-04 (s354).

**Regras em todos os passos:**
- Nunca cole chave, senha ou token no chat. Só a saída dos comandos, que não mostra valores.
- Rode os comandos em um terminal separado, a partir daqui:

```bash
cd ~/projects/easy/control-plane
```

- Cole em prompt oculto com **botão direito** ou **Ctrl+Shift+V**. O Ctrl+V pode falhar.

**Mudança de 2026-11-05 (ADR 067):** o painel operacional passou a anteceder a contratação da VPS. Veja as fases em
[painel.md](painel.md#do-exemplo-ao-real). Os passos abaixo continuam valendo.

## Visão geral

| # | Você faz | Tempo aproximado | Libera |
|---|---|---|---|
| 1 | Testar o restore do snapshot | 2 min | passos 2 a 4 |
| 2 | Enviar o snapshot ao Drive | 2 min | passo 4 |
| 3 | Copiar as chaves em papel | 5 min | passo 4 |
| 4 | Apagar o `.init.json` | 1 min | fim da proteção do cofre |
| 5 | Token da Vercel | 5 min | import da Vercel |
| 6 | Token da Railway | 3 min | conferência da Railway |
| 7 | Instalar o `gitleaks` | 2 min | varredura dos repos |
| 8 | Abrir os PRs da chave dupla | 10 min | rotação depois da VPS |
| 9 | Decidir os 3 pontos dos logs | 5 min | PR da observabilidade |
| 10 | Tailscale no celular | 5 min | teste de acesso de qualquer device |

- **Só o 2 e o 3 dependem do 1, e o 4 depende dos três.** Do 5 ao 10, a ordem é livre e nada depende de você terminar os anteriores.
- Avise o Claude ao terminar cada passo, com a saída quando houver.

## Parte 1: proteger o cofre

### Passo 1. Testar o restore

Prova que o snapshot abre em um cofre novo. O cofre real não é tocado.

```bash
CP_BAO_ADDR=http://127.0.0.1:8299 CP_BAO_RESTART_CMD="docker restart cp-bao-teste-bao-1" \
  scripts/cp-secrets restore openbao/backups/raft-20261104T223936Z.snap
CP_BAO_ADDR=http://127.0.0.1:8299 scripts/cp-secrets keys easygoal/health-stay/dev | head -5
```

1. O comando pede 2 chaves: cole das notas do Bitwarden.
2. **Esperado:** `restaurado e aberto`, seguido dos nomes de algumas chaves, sem valores.
3. Envie a saída ao Claude. Ele apaga o cofre descartável (`:8299`).

**Se der erro:** não apague nada e envie a saída.

### Passo 2. Enviar o snapshot ao Drive

```bash
cd openbao/backups && explorer.exe . ; cd ../..
```

1. Na pasta que abrir, localize `raft-20261104T223936Z.snap`.
2. Arraste o arquivo para uma pasta do Google Drive, por exemplo `Easy Goal/control-plane-backups`.

O snapshot é cifrado: sem as chaves, ele não abre. **Nunca coloque as chaves nessa mesma conta.**

Repita este envio sempre que importar muitos segredos: `scripts/cp-secrets backup` cria um snapshot novo.

### Passo 3. Copiar as chaves em papel

1. Abra as 3 notas `Control plane — unseal` no Bitwarden.
2. Copie à mão ou imprima, sem salvar o PDF. Confira letra por letra: `l`, `I`, `O` e `0` confundem.
3. Guarde em local físico seguro, longe do computador.

É a saída caso você perca o acesso ao Bitwarden. Sem as chaves, o cofre não abre mais.

Confira também se o código de recuperação do 2FA do Bitwarden está guardado.

### Passo 4. Apagar o `.init.json`

**Só depois dos passos 1, 2 e 3.**

```bash
shred -u ~/projects/.init.json
ls ~/projects/.init.json
```

**Esperado:** `No such file or directory`. A partir daqui, as chaves ficam só no Bitwarden e no papel.

## Parte 2: liberar o import

### Passo 5. Token da Vercel

1. Entre em `https://vercel.com/account/settings/tokens`.
2. Crie um token: nome `control-plane`, escopo no time da Easy Goal, validade de 90 dias.
3. Copie o token. Ele só aparece uma vez.
4. No painel do time, abra **Settings → General** e localize o **Team ID**.
5. Rode o comando abaixo e cole cada valor quando for pedido:

```bash
scripts/cp-secrets provider set easygoal vercel --expires "$(date -u -d '+90 days' +%F)"
```

**Esperado:** nenhuma mensagem de erro. Para conferir: `scripts/cp-secrets status | grep vercel`, com `vence` em vez de `VENCEU`.

### Passo 6. Token da Railway

1. Entre em `https://railway.com/account/tokens`.
2. Crie um token: nome `control-plane`, workspace da Easy Goal. Não deixe como token pessoal.
3. Rode o comando abaixo e cole o token:

```bash
scripts/cp-secrets provider set easygoal railway --expires "$(date -u -d '+90 days' +%F)"
```

**Esperado:** `scripts/cp-secrets status | grep railway` mostra a validade.

**Não apague nada na Railway:** ela segue em produção até a Fase 7.

Se algum menu estiver com outro nome, avise o Claude dizendo o número do passo.

### Passo 7. Instalar o `gitleaks`

```bash
sudo apt update && sudo apt install -y gitleaks
gitleaks version
```

Se o apt não encontrar o pacote, avise o Claude. O download direto foi bloqueado por segurança e precisa da sua aprovação.

### Passo 8. Abrir os PRs da chave dupla

Abra cada link, clique em **Create pull request** e revise. **Merge e deploy nesta ordem**, com o `sso` sempre por último:

1. [easygoal-monorepo](https://github.com/Easy-Goal/easygoal-monorepo/compare/main...feat/sso-jwt-chave-dupla?expand=1)
2. [app-front](https://github.com/Easy-Goal/app-front/compare/main...feat/sso-jwt-chave-dupla?expand=1)
3. [api-backend](https://github.com/Easy-Goal/api-backend/compare/main...feat/sso-jwt-chave-dupla?expand=1)
4. [easyai-crm](https://github.com/Easy-Goal/easyai-crm/compare/main...feat/sso-jwt-chave-dupla?expand=1)
5. [vaygo-api](https://github.com/VayGO-App/vaygo-api/compare/main...feat/sso-jwt-chave-dupla?expand=1) (deploy com aprovação manual na Railway)
6. [vaygo-web](https://github.com/VayGO-App/vaygo-web/compare/main...feat/sso-jwt-chave-dupla?expand=1)
7. [sso](https://github.com/Easy-Goal/sso/compare/main...feat/sso-jwt-chave-dupla?expand=1)

Este passo não bloqueia a contratação da VPS, só a rotação geral. Pode ficar por último.

### Passo 9. Decidir os 3 pontos dos logs

Responda ao Claude. As recomendações estão entre parênteses.

1. Manter `user_id` nos logs do Health Stay, junto com a rota acessada? (Sim, com retenção de 30 dias, confirmando com quem cuida de LGPD antes do go-live.)
2. Manter as mensagens de erro fora dos logs? (Sim: a mensagem do Prisma pode trazer valores da query.)
3. Atualizar o `PLAN.md` antes do PR, como pede o `.clinerules` do repo? (Sim.)

## Parte 3: testar de outro device

### Passo 10. Tailscale no celular

1. Instale o app **Tailscale** no celular e entre com a mesma conta desta máquina.
2. No terminal:

```bash
sudo service tailscaled start
tailscale status
```

3. **Esperado:** a lista mostra esta máquina e o celular. Avise o Claude, que prepara o acesso aos painéis de logs e analytics.

O cofre continua fora desse teste até haver login por pessoa.

## O que o Claude executa em paralelo

| Frente | O quê | Depende de | Estado |
|---|---|---|---|
| **B1** | Rascunho `openbao/secrets.draft.toml` com todos os repos, a partir do código, sem ler `.env`. O `cp-secrets` não lê esse arquivo | nada | ✅ 22 projetos e 32 targets; faltam 35 ids |
| **B2** | Conferir nomes e IDs dos projetos na Vercel e na Railway | passos 5 e 6 | aguardando |
| **B3** | Importar os valores para o cofre, com relatório só de nomes | B2 | aguardando |
| **E** | `gitleaks --redact` em todos os repos, com relatório sem valores | passo 7 | aguardando |
| **C** | Fechar a observabilidade: `PLAN.md`, e2e e `docker build` | passo 9 | aguardando |
| **G5** | Revalidar a API de prod no laboratório | nada | a fazer |
| **Celular** | `tailscale serve` para logs e analytics | passo 10 | aguardando |
| **Pesquisa** | MFA do OpenBao e limites do Bitwarden grátis | nada | a fazer |

**Regra durante o import:** nenhum `sync apply` em produção. Você decide, em cada divergência, qual valor vence.

## Quando contratar a VPS

Quando estas linhas estiverem todas marcadas. A lista completa está no [go-live](go-live-vps-principal.md#1-resumo).

- [x] Stack local sobe, volta depois de reiniciar e abre com as chaves digitadas
- [x] Logs de app local sem dado sensível; gateway bloqueia o painel
- [x] Evento chega ao Umami
- [x] Restore do snapshot funciona (passo 1, testado em 2026-11-04)
- [ ] Snapshot fora da máquina (passo 2)
- [ ] Todos os projetos no cofre (B1 a B3)
- [ ] `sync plan` lista as divergências
- [ ] Logs e analytics abrem pelo celular (passo 10)

## Depois de contratar (não precisa agora)

Cada um será detalhado quando chegar a hora.

- **DigitalOcean:** conta com 2FA e Droplet Basic 2 vCPU / 4 GB, Ubuntu 24.04 (US$ 24/mês, conferido em 2026-11-04).
- **Cloudflare R2:** bucket `cp-backups` e token só desse bucket, para os backups automáticos dos bancos. Até onde sei, pede cartão mesmo no plano grátis.
- **Discord:** canal `#alertas` e webhook em **Integrações**.
- **Tailscale:** decidir o plano, porque o Personal é não comercial (Standard: US$ 8/usuário/mês).
- **Instalação e migração do cofre:** Fases 1 e 2 do [go-live](go-live-vps-principal.md#fase-1--vps-do-control-plane).
- **Rotação geral e saída da Railway:** Fases 6 e 7, só com a VPS no ar.
