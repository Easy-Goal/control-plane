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

## Como ler a tela

| Marca | Significa |
|---|---|
| **Sólido** | lido agora nesta máquina |
| **Hachurado** | exemplo fictício, até o go-live trocar pelo dado real |

Os estados combinam forma, cor e texto: círculo cheio é pronto, losango é atenção ou falta, quadrado é problema e
círculo vazado é opcional ou não usado.

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

Simulado:
- os botões de ação, a criação de cliente e a conexão de conta. Eles não executam comando nem gravam no cofre ou no
  repositório, e o resultado fica só no navegador;
- em **Atividade**, "Voltar os exemplos ao início" apaga essas simulações.

Os comandos mostrados nos guias e nas contas são reais. Eles rodam no seu terminal, não pelo painel. O painel não
aceita token: o valor é pedido em prompt oculto pelo próprio `cp-secrets`.

## Regras de segurança

- Escuta só em `127.0.0.1` e recusa `Host` externo, o que barra DNS rebinding.
- Só GET e HEAD. Qualquer escrita responde 405.
- Nunca abre `.env`, `.init.json` nem `.bootstrap.env`. Desses arquivos, só verifica se existem.
- Não envia token ao cofre e não lê segredo. Um teste garante que os arquivos de credencial não são abertos.
- Fontes e scripts são locais, sem CDN, com CSP sem `unsafe-inline`.

Testes: `python3 -m unittest panel/test_server.py`.

## Do exemplo ao real

Cada área tem uma fonte em `DATA_SOURCES`, em `panel/server.py`. Quando um adaptador real entra e a fonte deixa de ser
`demo`, a hachura some da tela sem outra mudança.

| Fase | O que entra | Onde testa |
|---|---|---|
| 1. Leitura | Aplicações e containers (API do Coolify), logs (OpenObserve), contas e validade (metadados do cofre) | laboratório |
| 2. Ações | Scripts com saída estruturada, execução em segundo plano, Atividade real e a sessão do operador | laboratório |
| 3. Novo cliente | `openbao/clients/<cliente>.toml`, descoberta de projetos pelos tokens e assistente de ponta a ponta | cliente descartável no laboratório |
| 4. Go-live | Login com MFA, acesso só pela tailnet, VPS contratada e snapshot restaurado | VPS |

O `cp-secrets` ainda lê só `openbao/secrets.toml`. O arquivo por cliente mostrado pelo assistente passa a valer na
fase 3. Até lá, não crie `openbao/clients/` à mão esperando que ele seja aplicado.

## Health Stay com Neon no mesmo device

O passo a passo é `docs/DEV-REMOTO.md`, no `main` do `health-stay-backend`. O painel traz o resumo em
**Guias > Rodar o Health Stay com Neon** e mostra API e web como sólidos assim que estiverem no ar.

Use só dados fictícios no Neon. As URLs de conexão têm a senha do banco: copie do painel do Neon direto para o `.env`.
