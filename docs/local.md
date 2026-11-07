# Stack local

Cofre, logs e analytics rodando na sua máquina por docker compose. É a etapa antes de contratar a VPS: o que você
aprende e guarda aqui vai para lá pelo snapshot do cofre.

## Subir tudo

```bash
cplane up
```

Em um clone do repositório, sem instalar: `scripts/cplane up`. Em Windows sem WSL: `py scripts\cplane up`.

Um comando só, igual em todo sistema, que precisa de Python e Docker. Ele:

1. Confere o Docker e espera até 2 minutos, se ele ainda estiver ligando.
2. Sobe o cofre e, se estiver selado, pede as chaves ali mesmo, sem mostrar na tela.
3. Sobe OpenObserve, Umami e gateway, e espera cada um responder.
4. Grava no cofre as senhas de admin que faltarem.
5. Mostra o status e confere cada item. Se algo falhar, diz o que é e como olhar.
6. Com tudo certo, abre o painel conectado ao cofre. Ctrl+C fecha só o painel; a stack continua no ar.

Repetir é seguro: o que já está de pé não é recriado, e nada é apagado.

| Opção | O que muda |
|---|---|
| `--lab` | Religa o laboratório já criado, abre o cofre dele e abre o painel com ações nele. Só no repositório |
| `--sem-painel` | Para depois da conferência |
| `--sem-navegador` | Só mostra o link do painel |
| `--port 4701` | Outra porta para o painel |

**O que ele não faz sozinho:**

- **Inicializar um cofre vazio.** Um cofre vazio pode ser sinal de volume trocado, então ele para e mostra os comandos. Na primeira vez: `cplane secrets init`, `cplane secrets apply` e `cplane up` de novo.
- **Guardar as chaves de unseal.** Elas são pedidas toda vez que o cofre volta selado. Com `--lab`, o cofre do laboratório pede as dele.
- **Criar o laboratório.** Isso é com `sim/lab.sh up`.

## Sumário

- [Subir tudo](#subir-tudo)
- [Comandos](#comandos)
- [Endereços e login](#endereços-e-login)
- [Depois de reiniciar a máquina ou o Docker](#depois-de-reiniciar-a-máquina-ou-o-docker)
- [Enviar logs de uma app local](#enviar-logs-de-uma-app-local)
- [O que a stack local não faz](#o-que-a-stack-local-não-faz)
- [Como ela se compara à VPS e ao laboratório](#como-ela-se-compara-à-vps-e-ao-laboratório)
- [Problemas conhecidos](#problemas-conhecidos)

## Comandos

Os comandos separados, que precisam de bash, `jq`, `curl` e `openssl` e por isso só funcionam no repositório:

```bash
scripts/cp-local up       # sobe tudo menos o painel; com o cofre aberto, registra as senhas de admin nele. Pode repetir
scripts/cp-local status   # containers, cofre, OpenObserve, Umami e gateway
scripts/cp-local urls     # endereços dos painéis
scripts/cp-local stop     # para os containers. Dados preservados: nunca remove volumes
scripts/cp-local run cp-obs status   # roda um script contra o OpenObserve e o Umami locais
```

Requisitos: Docker Desktop com integração WSL e `jq`.

## Endereços e login

Tudo só em `127.0.0.1`.

| Ferramenta | Endereço | Login |
|---|---|---|
| OpenBao | `http://127.0.0.1:8200/ui/` | token de `scripts/cp-secrets ui-token` |
| OpenObserve | `http://127.0.0.1:15080` | `operador@cp-local.local` + senha do cofre |
| Umami | `http://127.0.0.1:13300` | `admin` + senha do cofre |
| Gateway de ingestão | `http://127.0.0.1:18280` | sem login; só aceita envio, então abrir no navegador dá 404 |
| Painel | `http://127.0.0.1:4700` | só no ar com `cplane up` ou `cplane` |

Copiar uma senha sem mostrar na tela:

```bash
scripts/cp-secrets provider exec <conta> openobserve-local -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
scripts/cp-secrets provider exec <conta> umami-local -- sh -c 'printf %s "$CP_PASSWORD" | clip.exe'
```

Limpe o histórico da área de transferência do Windows (Win+V) depois.

## Depois de reiniciar a máquina ou o Docker

Os containers voltam sozinhos, mas o cofre volta **selado**. Rode `cplane up`: ele pede 2 das 3 chaves do gerenciador de senhas, confere tudo e abre o painel. Cole com botão direito ou Ctrl+Shift+V.

## Enviar logs de uma app local

```bash
scripts/cp-local run cp-obs ingest <cliente>/<projeto>/dev               # org + token de ingestão, gravados no cofre
scripts/cp-local run cp-obs analytics <cliente>/<projeto>/dev --domain localhost   # site no Umami
scripts/cp-secrets run <aplicação>-dev -- <comando da app>
```

- App rodando direto na máquina: o `OBS_OTLP_ENDPOINT` gravado já serve.
- App em container: ela precisa de `http://host.docker.internal:18280/api/<org>`, porque `127.0.0.1` dentro do
  container é o próprio container.
- Org e stream: a org se chama `<cliente>_<ambiente>` (`<cliente>_dev`) e o stream recebe o nome de `OBS_SERVICE`, com
  hífen virando underscore.
- Na API de consulta, o caminho usa o **id** da org, que aparece no `cp-obs status`, não o nome.

O endpoint local fica gravado no ambiente `dev` do cofre. Na VPS, rode o `cp-obs ingest` de novo, com o provedor real,
para trocá-lo.

## O que a stack local não faz

- **Não recebe logs de produção.** Apps na Vercel ou na Railway não alcançam `127.0.0.1`. Isso depende do gateway
  público da VPS.
- **Não fica no ar com a máquina desligada.**
- **Não tem Coolify.** Para ensaiar deploy, use o [laboratório](instalacao.md#laboratório).
- **Não deve rodar `sync apply` contra produção** enquanto os valores importados não forem conferidos: `.env` local
  costuma ter valor de dev.

## Como ela se compara à VPS e ao laboratório

| | Stack local | Laboratório (`sim/`) | VPS |
|---|---|---|---|
| Uso | dia a dia antes da VPS | ensaio do instalador e de deploy | produção |
| Cofre | principal, `:8200`, HTTP | cópia restaurada, `:8210`, TLS | principal, `:8200`, TLS |
| Observabilidade | `install/observability/setup.sh` | o mesmo | o mesmo |
| Coolify | não | sim | sim |

- **Mesmo código:** `setup.sh`, `compose.yml`, `Caddyfile` e `images.env` são os mesmos nos 3 casos. A stack local só
  acrescenta `local/observability.ports.yml`, que troca as portas.
- **Convivência:** as portas próprias permitem rodar a stack local e o laboratório ao mesmo tempo.
- **Cofre fora do projeto novo:** ele segue no projeto `cp-openbao`. Mover para outro projeto compose mudaria o nome do
  volume e o cofre apareceria vazio.

Arquivos gerados em `local/observability/` (fora do git): cópia do compose e `.env` (600) com as senhas de admin. Apagar
esse `.env` com os volumes existentes tira de sincronia as senhas guardadas no cofre.

## Problemas conhecidos

- O `cp-obs status` pode mostrar `docs=0` logo depois do envio, mesmo com os logs já consultáveis. Confira por SQL no
  painel.
- Prompt oculto do `unseal`: o Ctrl+V pode não colar como texto e gerar `'key' must be a valid hex or base64 string`.
  Esse erro não consome tentativa nem altera o cofre.
