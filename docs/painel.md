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
| **Clientes** | checklist de implantação, contas, divergências e encerramento por cliente | exemplo |
| **Aplicações** | versão, deploy, estado e ações por ambiente; containers do Docker local | exemplo + máquina |
| **Logs** | logs filtrados por cliente, ambiente, nível e texto | exemplo |
| **Atividade** | histórico das ações, inclusive as simuladas no painel | exemplo |
| **Configurar** | o que este device tem e o que falta, os requisitos por tipo de aplicação e o caminho do exemplo ao real | máquina + conteúdo fixo |
| **Contas** | uma ficha para cada conta de cada cliente: o que atende, campos no cofre, passo a passo e revogação | exemplo |
| **Guias** | as situações de `comandos.md`, com busca, passos, cuidados e comando pronto | conteúdo fixo |
| **Ferramentas** | para que ir a cada ferramenta e como entrar | máquina |
| **Novo cliente** | caminho único do contrato até dev, com arquivo e comandos prontos no fim | simulação |

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

Ainda exemplo, mesmo com sessão: Vercel, Railway (fase 1b), Clientes, Atividade e divergências.

"Hospedagem" é o que o Coolify informa sobre o servidor. Esse estado pode estar defasado: no lab, ele seguiu verde enquanto
o backup falhava com SSH negado. Confira também o backup e o health check.

A versão hoje é a imagem. Com tag móvel, como `:dev`, o painel avisa e não calcula "Atrás de dev". A esteira passa a usar
tag imutável na fase 3.

Simulado:
- os botões de ação, a criação de cliente e a conexão de conta. Eles não executam comando nem gravam no cofre ou no
  repositório, e o resultado fica só no navegador. Linhas reais não têm esses botões;
- em **Atividade**, "Voltar os exemplos ao início" apaga essas simulações.

Os comandos mostrados nos guias e nas contas são reais. Eles rodam no seu terminal, não pelo painel. O painel não
aceita token: o valor é pedido em prompt oculto pelo próprio `cp-secrets`.

## Regras de segurança

- Escuta só em `127.0.0.1` e recusa `Host` externo, o que barra DNS rebinding.
- Só GET e HEAD. Qualquer escrita responde 405.
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
| 2. Ações | Scripts com saída estruturada, execução em segundo plano, Atividade real e a sessão do operador | laboratório |
| 3. Novo cliente | `openbao/clients/<cliente>.toml`, descoberta de projetos pelos tokens e assistente de ponta a ponta | cliente descartável no laboratório |
| 4. Go-live | Login com MFA, acesso só pela tailnet, VPS contratada e snapshot restaurado | VPS |

O `cp-secrets` ainda lê só `openbao/secrets.toml`. O arquivo por cliente mostrado pelo assistente passa a valer na
fase 3. Até lá, não crie `openbao/clients/` à mão esperando que ele seja aplicado.

A leitura do Coolify usa o token de cada cliente, um por vez: nenhum token enxerga todos os times. Veja
[o comando por cliente](comandos.md#coolify-de-um-cliente-um-time-por-cliente).

## Health Stay com Neon no mesmo device

O passo a passo é `docs/DEV-REMOTO.md`, no `main` do `health-stay-backend`. O painel traz o resumo em
**Guias > Rodar o Health Stay com Neon** e mostra API e web como sólidos assim que estiverem no ar.

Use só dados fictícios no Neon. As URLs de conexão têm a senha do banco: copie do painel do Neon direto para o `.env`.
