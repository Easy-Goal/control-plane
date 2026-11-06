# Painel do control plane

Um lugar único para ver o que está sendo feito, o que falta e onde resolver. O cofre continua com acesso separado.
Decisão registrada no ADR 067 do `easy-labs`.

## Abrir em qualquer device

Só precisa de Python 3.11 ou mais novo. Não precisa de Docker, cofre nem credencial.

```bash
git clone git@github.com:Easy-Goal/control-plane.git
cd control-plane
git switch feat/painel
scripts/cp-panel        # http://127.0.0.1:4700
```

Se a porta estiver ocupada: `scripts/cp-panel --port 4701`. Em Windows sem WSL: `py scripts\cp-panel`.

Para ver o painel em outro device, **não copie** `.init.json` nem `.bootstrap.env`. Nenhum deles é necessário.

## Ver dados reais do laboratório

Precisa do laboratório no ar, do cofre aberto e da credencial de operador nesta máquina. As credenciais de leitura são
gravadas uma vez:

```bash
docker exec -i cp-sim-sim-cp-1 bash -s < install/coolify-read-token.sh \
  | scripts/cp-lab cp-secrets provider set easygoal coolify-sim-read url=http://127.0.0.1:8000 --stdin token \
      --expires "$(date -u -d '+90 days' +%F)"
CP_OBS_PROVIDER=openobserve-sim scripts/cp-lab cp-obs panel-read   # rodar de novo quando surgir org nova
scripts/cp-lab cp-panel
```

O `cp-obs panel-read` precisa do provedor `openobserve-sim` gravado no cofre do lab, como em
[observabilidade.md](observabilidade.md#credenciais-de-admin-no-cofre).

A sessão dura 1 h e não é renovada: quando vencer, as linhas reais aparecem como "Não lido". Encerre e abra de novo.

## Agir pelo painel no laboratório

```bash
scripts/cp-lab cp-panel --acoes
```

O terminal mostra um link com uma chave, válido só nesta execução. Abra por ele: sem a chave, o navegador não vê os botões
reais e o servidor recusa o pedido. Depois de abrir, os botões das linhas sólidas executam de verdade:

| Ação | Onde | O que roda |
|---|---|---|
| Reiniciar | ficha da aplicação | `cp-coolify service restart` ou `db restart` |
| Fazer deploy | ficha da API | `cp-coolify service restart --latest` |
| Fazer backup | ficha do banco | `cp-coolify backup now` |
| Levar os segredos | ficha da aplicação | `cp-secrets sync apply` |
| Conferir diferenças | Clientes | `cp-secrets sync plan --json` |
| Testar a conexão | Contas | `cp-secrets provider test` |

Em prod, é preciso digitar o nome para confirmar. O resultado fica em **Atividade**, com a saída já limpa, e o histórico
em `panel/state/activity.jsonl`, fora do git.

**Fica fora do painel:** revogar token e encerrar cliente, que são irreversíveis, e unseal, que continua no terminal.

**Fora do laboratório, as ações não ligam.** O painel recusa `--acoes` em outro cofre até existir o login com MFA da fase 4.

## Como ler a tela

| Marca | Significa |
|---|---|
| **Sólido** | lido agora nesta máquina ou, com sessão, no cofre, no Coolify e no OpenObserve |
| **Hachurado** | exemplo fictício, até o go-live trocar pelo dado real |

Os estados combinam forma, cor e texto: círculo cheio é pronto, losango é atenção ou falta, quadrado é problema e
círculo vazado é opcional, não usado ou não lido.

A marca vale por linha: no mesmo quadro, o que tem leitura fica sólido e o resto segue hachurado. Se uma leitura falha,
a linha mostra "Não lido", a causa e o próximo passo. Ela nunca volta para o exemplo.

## O que cada área faz

| Área | Para quê | Dado hoje |
|---|---|---|
| **Quadro** | o que precisa de atenção, o que falta na máquina e a matriz de aplicações com a versão em produção | exemplo + máquina |
| **Clientes** | checklist de implantação, contas, divergências e encerramento por cliente | exemplo; real com sessão |
| **Aplicações** | versão, deploy, estado e ações por ambiente; containers do Docker local | exemplo + máquina |
| **Logs** | logs filtrados por cliente, ambiente, nível e texto | exemplo |
| **Atividade** | histórico das ações, as reais e as simuladas | exemplo; real com `--acoes` |
| **Configurar** | o que este device tem e o que falta, os requisitos por tipo de aplicação e o caminho do exemplo ao real | máquina + conteúdo fixo |
| **Contas** | uma ficha para cada conta de cada cliente: o que atende, campos no cofre, passo a passo e revogação | exemplo |
| **Guias** | as situações de `comandos.md`, com busca, passos, cuidados e comando pronto | conteúdo fixo |
| **Ferramentas** | para que ir a cada ferramenta e como entrar | máquina |
| **Novo cliente** | cria o cliente e o arquivo dele; depois, o checklist em Clientes guia o resto | simulação; real com `--acoes` |

## O que é real e o que é simulado

Real hoje, lido por `/api/device`:
- repositório, Python, Docker, `jq` e Tailscale;
- cofres em `:8200` e `:8210`, só pela rota pública `sys/seal-status`;
- portas do Coolify, do OpenObserve, do Umami e do gateway, na stack local e no laboratório;
- API e web do Health Stay em `localhost:3001` e `localhost:3000`;
- containers do `docker ps` e os nomes declarados em `openbao/secrets.toml`.

Real com sessão (`scripts/cp-lab cp-panel`), só para clientes em `openbao/secrets.toml`:
- services e bancos do Coolify: estado, imagem, servidor, backup e última mudança;
- segredos por ambiente: versão do cofre e versão levada ao destino;
- contas: se a credencial existe e a validade, pelos metadados do cofre;
- logs do OpenObserve, até 100 por stream nos últimos 7 dias, só com os campos da allowlist.

Sem leitura da plataforma ainda: Vercel e Railway (fase 1b). O que está declarado aparece como "Sem leitura ainda", sem
inventar versão. Atividade e divergências ficam reais com `--acoes`.

A validade da conta é a data anotada no cofre, não a resposta da plataforma. **Testar a conexão** confere de verdade.

"Hospedagem" é o que o Coolify informa sobre o servidor. Esse estado pode estar defasado: no lab, ele seguiu verde enquanto
o backup falhava com SSH negado. Confira também o backup e o health check.

A versão é a imagem. Com tag móvel, como `:dev`, o painel avisa e não compara ambientes.

Simulado, nas linhas hachuradas e no assistente:
- os botões de ação, a criação de cliente e a conexão de conta. Eles não executam comando nem gravam no cofre ou no
  repositório, e o resultado fica só no navegador. Linhas reais não têm botões simulados;
- em **Atividade**, "Voltar os exemplos ao início" apaga essas simulações.

Os comandos mostrados nos guias e nas contas são reais. Eles rodam no seu terminal, não pelo painel. O painel não
aceita token: o valor é pedido em prompt oculto pelo próprio `cp-secrets`.

## Regras de segurança

- Escuta só em `127.0.0.1` e recusa `Host` externo, o que barra DNS rebinding.
- Sem `--acoes`, só GET e HEAD: qualquer escrita responde 405.
- Com `--acoes`, o único POST é `/api/actions`. Ele exige `Host`, `Origin`, JSON e a chave do terminal, aceita só a lista
  fechada de ações, confere o alvo no inventário real e roda sem shell e sem stdin. As ações desligam quando a sessão vence.
- Enquanto `--acoes` está ligado, quem tem a chave age com a credencial de operador desta máquina, a mesma dos scripts. A
  janela de 1 h é aplicada pelo painel, não pelo cofre. Por isso as ações não saem do laboratório antes do login com MFA.
- Nunca abre `.env`, `.init.json` nem `.bootstrap.env`. Desses arquivos, só verifica se existem.
- Sem sessão, não envia token ao cofre e não lê segredo. Um teste garante que os arquivos de credencial não são abertos.
- Com sessão, o `cp-secrets panel-session` entra como operador, cria um token de 1 h e revoga o de operador. O painel
  guarda o token só em memória, nunca o envia ao navegador e o revoga ao fechar.
- A política `cp-panel-read` lê metadados e só as credenciais `*-read`. Segredo de aplicação e token de escrita dão 403.
- `install/coolify-read-token.sh` gera token só com `read`: o Coolify esconde senhas, URLs de banco, compose e chave privada.
- Cada conta de logs enxerga uma org. No OpenObserve OSS ela também poderia enviar logs para essa org; por isso o acesso
  à API fica na tailnet.
- Só saem campos escritos em `panel/live.py`. Rota de log perde query e identificadores; mensagem de erro não sai.
- Fontes e scripts são locais, sem CDN, com CSP sem `unsafe-inline`.

Testes: `python3 -m unittest panel/test_server.py`.

## Do exemplo ao real

Cada linha tem `source`: `live` vem de `panel/live.py` e `demo` vem de `demo.json`. Quando um adaptador real entra, a
hachura daquela linha some sem outra mudança na tela.

| Fase | O que entra | Onde testa |
|---|---|---|
| 1. Leitura (feita) | Aplicações e containers (API do Coolify), logs (OpenObserve), contas e validade (metadados do cofre) | laboratório |
| 1b. Vercel e Railway | Versão e estado com a conta de cada cliente, quando os tokens existirem | contas reais |
| 2. Ações (feita) | Scripts com saída estruturada, execução em segundo plano e Atividade real | laboratório |
| 3. Novo cliente (feita) | `openbao/clients/<cliente>.toml`, descoberta de projetos, checklist real e tag imutável | cliente descartável no laboratório |
| 4. Go-live | Login com MFA, acesso só pela tailnet, VPS contratada e snapshot restaurado | VPS |

Os scripts e o painel leem `openbao/secrets.toml` mais `openbao/clients/<cliente>.toml`, pelo mesmo `scripts/cp_config.py`.

A leitura do Coolify usa o token de cada cliente, um por vez: nenhum token enxerga todos os times. Veja
[o comando por cliente](comandos.md#coolify-de-um-cliente-um-time-por-cliente).

## Cliente novo

Com `--acoes`, **Novo cliente** cria de verdade, no laboratório. Sem `--acoes`, é simulação e não grava nada.

1. **No assistente:** nome, plataformas, projetos e nomes das variáveis. A revisão mostra o arquivo que será gravado.
2. **O painel faz:** grava `openbao/clients/<cliente>.toml`, tira um snapshot, roda `cp-secrets apply --client <cliente>`,
   gera os segredos internos e liga os logs. Se parar no meio, **Terminar a preparação** retoma sem repetir o que já foi feito.
3. **Você faz, seguindo o checklist do cliente:** conectar as contas, cadastrar a VPS, gravar os valores externos e levar
   para cada ambiente. Cada item mostra o que falta e o comando pronto; os comandos mudam sozinhos para o laboratório.

O identificador do cliente não tem hífen: o nome da org de logs é `<cliente>_<ambiente>`. O painel nunca sobrescreve um
arquivo de cliente, e o arquivo gravado fica para você revisar e fazer commit.

**Limites de hoje:**
- Railway: o projeto entra sem destino, porque precisa de três ids. **Buscar projetos** lista os ids; complete o arquivo à mão.
- Vercel e Railway: a descoberta e o teste de conta só rodaram com dados simulados nos testes do repositório, salvo o teste
  de conta da Vercel, que rodou uma vez com um token real.
- Encerrar cliente continua no terminal, com passos manuais: `cp-obs revoke`, `cp-secrets offboard` e remover o time e o
  usuário de serviço no Coolify. As orgs vazias ficam no OpenObserve até a retenção.

## Versão em produção

Uma imagem com tag `<versão>-<sha>` diz exatamente o que está rodando. O compose usa `${IMAGE_TAG:-dev}`, e o comando abaixo
leva o service para a tag, espera ficar saudável e registra o release nos metadados do cofre, que é onde o painel lê:

```bash
scripts/cp-coolify --client <cliente> service release <service> 1.3.0-a1b2c3d   # recusa tag móvel
sim/lab.sh release staging                                                      # no lab: publica a imagem e leva
```

Com as duas pontas em tag imutável, o quadro mostra "Atrás de staging" ou "Atrás de dev", e a ficha de prod oferece
**Promover**: leva prod à mesma imagem do ambiente anterior, com o nome digitado para confirmar.

**Limites:** o registro diz o último release feito por este caminho; mudar a imagem à mão no Coolify não aparece aqui. A
esteira real ainda não publica nesse formato: `health-stay-backend` publica por tag `v*.*.*` e precisa passar a gerar
`<versão>-<sha>` antes do go-live.

## Health Stay com Neon no mesmo device

O passo a passo é `docs/DEV-REMOTO.md`, no `main` do `health-stay-backend`. O painel traz o resumo em
**Guias > Rodar o Health Stay com Neon** e mostra API e web como sólidos assim que estiverem no ar.

Use só dados fictícios no Neon. As URLs de conexão têm a senha do banco: copie do painel do Neon direto para o `.env`.
