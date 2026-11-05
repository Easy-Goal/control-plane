// Conteúdo fixo do painel: como configurar cada coisa. Comandos conferidos em docs/comandos.md.
// Nenhum valor de segredo aqui nem nas telas: os comandos pedem o valor em prompt oculto no terminal.

export const TRACKS = [
  { id: 'cofre', name: 'Cofre e segredos', why: 'Guarda os valores. O painel só mostra nomes e estado.' },
  { id: 'containers', name: 'Containers', why: 'Docker nesta máquina e o Coolify, que opera as VPS.' },
  { id: 'contas', name: 'Contas e estado desejado', why: 'O que cada cliente declara e o que ainda falta declarar.' },
  { id: 'logs', name: 'Logs e analytics', why: 'OpenObserve, Umami e o gateway que recebe os envios.' },
  { id: 'apps', name: 'Aplicações neste device', why: 'O que está rodando aqui agora.' },
  { id: 'acesso', name: 'Acesso remoto', why: 'Como chegar à VPS de qualquer device, só pela tailnet.' },
  { id: 'maquina', name: 'Ferramentas da máquina', why: 'O mínimo para rodar os scripts de terminal.' },
];

export const CHECKS = {
  repo: { track: 'maquina', name: 'Repositório control-plane', steps: ['Clone o repositório e entre na pasta.'], cmd: 'git clone git@github.com:Easy-Goal/control-plane.git\ncd control-plane\ngit switch feat/painel' },
  python: { track: 'maquina', name: 'Python', steps: ['Instale o Python 3.11 ou mais novo.'], cmd: 'sudo apt install -y python3' },
  jq: { track: 'maquina', name: 'jq', optional: true, steps: ['Só os scripts de terminal usam. Instale quando for operar por aqui.'], cmd: 'sudo apt install -y jq' },
  operator: { track: 'cofre', name: 'Credencial de operador', optional: true, steps: ['Ela nasce quando o cofre é inicializado neste device, ou é copiada do Bitwarden.', 'Só o device que opera precisa dela. Para ver o painel, não precisa.'], cmd: 'scripts/cp-secrets init', doc: 'docs/segredos.md' },
  init_json: { track: 'cofre', name: 'Chaves de unseal fora do disco', steps: ['Confirme que as chaves estão no Bitwarden e em papel.', 'Apague o arquivo. Não abra nem copie o conteúdo para outro lugar.'], cmd: 'shred -u <caminho>/.init.json' },
  vault_local: { track: 'cofre', name: 'Cofre local', target: 'local', optional: true, steps: ['Precisa de Docker. Sobe o cofre, os logs e o analytics juntos.', 'O cofre volta selado a cada reinício: faça o unseal com 2 das 3 chaves.'], cmd: 'scripts/cp-local up\nscripts/cp-secrets unseal', doc: 'docs/local.md' },
  vault_lab: { track: 'cofre', name: 'Cofre do laboratório', target: 'lab', optional: true, steps: ['Suba o laboratório, instalado pelos mesmos scripts da VPS.', 'Faça o unseal do cofre do lab.'], cmd: 'sim/lab.sh up\nscripts/cp-lab cp-secrets unseal', doc: 'docs/instalacao.md' },
  docker: { track: 'containers', name: 'Docker', optional: true, steps: ['Só o stack local e o laboratório precisam dele. No device de visualização, pode ficar sem.', 'Windows: Docker Desktop com a integração do WSL ligada.'], cmd: 'docker info' },
  coolify_lab: { track: 'containers', name: 'Coolify do laboratório', target: 'lab', optional: true, steps: ['A stack local não tem Coolify. Ele existe no laboratório e, depois, na VPS.'], cmd: 'sim/lab.sh up\nscripts/cp-lab cp-coolify servers', doc: 'docs/instalacao.md' },
  desired: { track: 'contas', name: 'Estado desejado', steps: ['É a lista versionada de clientes, contas e projetos, só com nomes.', 'Atualize o repositório para receber a versão mais recente.'], cmd: 'git pull', doc: 'docs/sync.md' },
  oo_local: { track: 'logs', name: 'OpenObserve local', target: 'local', optional: true, steps: ['Sobe junto com a stack local.'], cmd: 'scripts/cp-local up\nscripts/cp-local urls', doc: 'docs/observabilidade.md' },
  umami_local: { track: 'logs', name: 'Umami local', target: 'local', optional: true, steps: ['Sobe junto com a stack local.'], cmd: 'scripts/cp-local up', doc: 'docs/observabilidade.md' },
  gw_local: { track: 'logs', name: 'Gateway de logs local', target: 'local', optional: true, steps: ['Sobe junto com a stack local. É o único caminho de envio das apps.'], cmd: 'scripts/cp-local up', doc: 'docs/observabilidade.md' },
  oo_lab: { track: 'logs', name: 'OpenObserve do laboratório', target: 'lab', optional: true, steps: ['Sobe com o laboratório.'], cmd: 'sim/lab.sh up', doc: 'docs/observabilidade.md' },
  umami_lab: { track: 'logs', name: 'Umami do laboratório', target: 'lab', optional: true, steps: ['Sobe com o laboratório.'], cmd: 'sim/lab.sh up', doc: 'docs/observabilidade.md' },
  gw_lab: { track: 'logs', name: 'Gateway do laboratório', target: 'lab', optional: true, steps: ['Sobe com o laboratório.'], cmd: 'sim/lab.sh up', doc: 'docs/observabilidade.md' },
  hs_api: { track: 'apps', name: 'API do Health Stay', optional: true, steps: ['Siga o guia do Neon. Depois, a API responde em localhost:3001.'], guide: 'health-stay-neon', cmd: 'pnpm dev' },
  hs_web: { track: 'apps', name: 'Web do Health Stay', optional: true, steps: ['No repositório do front, com a API no ar.'], guide: 'health-stay-neon', cmd: 'pnpm dev' },
  tailscale: { track: 'acesso', name: 'Tailscale', optional: true, steps: ['Instale e entre com a conta da tailnet.', 'A VPS só será acessível por essa rede privada.'], cmd: 'sudo tailscale up', doc: 'docs/acesso.md' },
  vps: { track: 'acesso', name: 'VPS do control plane', target: 'vps', optional: true, steps: ['Contrate depois que o painel estiver operando no laboratório.', 'Rode o instalador dentro da VPS, como root.', 'Restaure o snapshot do cofre e faça o unseal.'], cmd: 'bash install/control-plane.sh', doc: 'docs/go-live-vps-principal.md' },
};

export const PROVIDERS = {
  vercel: {
    name: 'Vercel', role: 'Hospeda os fronts e recebe as variáveis deles.', url: 'https://vercel.com/account/tokens', urlLabel: 'Abrir tokens da Vercel',
    create: ['Entre na conta do cliente, com 2FA.', 'Crie o token control-plane, restrito ao time do cliente, com validade de 90 dias.', 'Copie o Team ID em Settings do time.'],
    command: (c, n) => `scripts/cp-secrets provider set ${c} ${n} team_id=<team_id> --stdin token --expires <AAAA-MM-DD>`,
    revoke: 'api', revokeHelp: 'A revogação usa a API da Vercel e apaga o token do cofre.',
    fields: { token: 'Token do time', team_id: 'Identificador do time' },
  },
  railway: {
    name: 'Railway', role: 'Hospeda APIs até a migração para a VPS.', url: 'https://railway.com/workspace/tokens', urlLabel: 'Abrir tokens da Railway',
    create: ['Entre na conta do cliente.', 'Crie o token control-plane no workspace dele. Não use um token pessoal.'],
    command: (c, n) => `scripts/cp-secrets provider set ${c} ${n} --stdin token --expires <AAAA-MM-DD>`,
    revoke: 'manual', revokeHelp: 'A Railway não tem revogação pelo sync. Apague o token na tela de tokens dela.',
    fields: { token: 'Token do workspace' },
  },
  github: {
    name: 'GitHub', role: 'Grava segredos do Actions, por meio da GitHub App.', url: 'https://github.com/settings/installations', urlLabel: 'Abrir instalações da App',
    create: ['Instale a GitHub App na organização do cliente.', 'Anote o App ID e o Installation ID.', 'Gere a chave privada, grave no cofre e apague o arquivo.'],
    command: (c, n) => `scripts/cp-secrets provider set ${c} ${n} app_id=<id> installation_id=<id> --stdin private_key < arquivo.pem\nshred -u arquivo.pem`,
    revoke: 'api', revokeHelp: 'A revogação remove a instalação pela API e apaga a chave do cofre.',
    fields: { app_id: 'ID da App', installation_id: 'ID da instalação', private_key: 'Chave privada' },
  },
  coolify: {
    name: 'Coolify', role: 'Faz deploy nas VPS. Cada cliente tem um time próprio, com token próprio.', urlLabel: 'Abrir o Coolify', toolCheck: 'coolify_lab',
    create: ['No Coolify, crie o time do cliente.', 'Com esse time ativo, crie o token de API em Keys & Tokens.', 'O token só enxerga os servidores e projetos desse time.'],
    command: (c, n) => `scripts/cp-secrets provider set ${c} ${n} url=http://<cp>:8000 --stdin token --expires <AAAA-MM-DD>`,
    revoke: 'manual', revokeHelp: 'Apague o token em Keys & Tokens, no próprio Coolify.',
    fields: { url: 'Endereço do Coolify', token: 'Token do time' },
  },
  droplet: {
    name: 'Droplet da DigitalOcean', role: 'Servidor do cliente. É operado pelo Coolify, sem token da DigitalOcean.', url: 'https://cloud.digitalocean.com/droplets', urlLabel: 'Abrir Droplets',
    create: ['Crie o Droplet na conta do cliente e guarde a conta com ele.', 'Copie a chave pública do Coolify.', 'Dentro do Droplet, rode o instalador como root.', 'Cadastre o servidor no Coolify, no time do cliente.'],
    command: () => 'scripts/cp-coolify key\nCOOLIFY_PUBKEY="<chave>" SERVER_TAG=app-prd TS_AUTHKEY=<auth key> bash /opt/cp-install/app-server.sh\nscripts/cp-coolify server add <nome> <ip na tailnet>',
    revoke: 'none', revokeHelp: 'No fim do contrato, remova a chave SSH, o servidor no Coolify e o nó da tailnet.',
    fields: {},
  },
};

export const ACCOUNT_STATE = {
  ok: ['ok', 'Válida'], soon: ['warn', 'Vencendo'], expired: ['err', 'Vencida'], missing: ['err', 'Sem token'],
  noexp: ['warn', 'Sem validade'], notoken: ['off', 'Sem token, por desenho'],
};

export const APP_TYPES = {
  'front-vercel': {
    name: 'Front na Vercel', when: 'Next.js e landing pages.',
    layers: [
      { track: 'Conta', items: ['Conta da Vercel conectada, com o token do time do cliente.', 'Team ID e Project ID declarados no estado desejado.'], to: '#/contas', toLabel: 'Abrir contas' },
      { track: 'Segredos', items: ['Allowlist com as variáveis do front. Nada além dela chega ao destino.', 'Variáveis com NEXT_PUBLIC_ são públicas: nunca segredo.'], cmd: 'scripts/cp-secrets sync plan <cliente>/<projeto>' },
      { track: 'Hospedagem', items: ['A Vercel cuida do deploy. Não há container para operar.'] },
      { track: 'Logs e analytics', items: ['Criar a org de logs e o token de envio.', 'Criar o site no Umami e levar as duas chaves.'], cmd: 'scripts/cp-obs ingest <cliente>/<projeto>/<ambiente>\nscripts/cp-obs analytics <cliente>/<projeto>/<ambiente> --domain <domínio>' },
    ],
  },
  'api-coolify': {
    name: 'API em container', when: 'NestJS e outros serviços em VPS, operados pelo Coolify.',
    layers: [
      { track: 'Conta', items: ['Time do cliente no Coolify, com token próprio.', 'GitHub App instalada, se o deploy partir do Actions.'], to: '#/contas', toLabel: 'Abrir contas' },
      { track: 'Segredos', items: ['Segredos internos gerados no cofre.', 'Valores vindos de painéis externos gravados no cofre.', 'Allowlist do service.'], cmd: 'scripts/cp-secrets secret gen <cliente>/<projeto>/<ambiente> JWT_SECRET\nscripts/cp-secrets secret set <cliente>/<projeto>/<ambiente> DATABASE_URL' },
      { track: 'Containers', items: ['VPS instalada e cadastrada no Coolify.', 'Service criado, com o health check da aplicação.'], cmd: 'scripts/cp-coolify server add <nome> <ip na tailnet>\nscripts/cp-coolify service ensure <argumentos>', guide: 'vps-nova' },
      { track: 'Logs', items: ['O app usa o pacote @easygoal/observability.', 'Org e token de envio por ambiente.'], cmd: 'scripts/cp-obs ingest <cliente>/<projeto>/<ambiente>\nscripts/cp-secrets sync apply <cliente>/<projeto>', guide: 'ligar-logs' },
    ],
  },
  'db-coolify': {
    name: 'Banco em container', when: 'Postgres gerenciado pelo Coolify.',
    layers: [
      { track: 'Conta', items: ['Mesmo time do Coolify da API.'], to: '#/contas', toLabel: 'Abrir contas' },
      { track: 'Segredos', items: ['A DATABASE_URL gerada fica no cofre.'] },
      { track: 'Containers', items: ['Criar o banco.', 'Agendar o backup em S3 e testar uma restauração.'], cmd: 'scripts/cp-coolify db ensure <projeto> <ambiente> <servidor> <nome> <caminho>\nscripts/cp-coolify backup ensure <nome> <destino>' },
    ],
  },
  'api-railway': {
    name: 'API na Railway', when: 'Só durante a transição. Depois, vira API em container.',
    layers: [
      { track: 'Conta', items: ['Token do workspace do cliente, com validade.'], to: '#/contas', toLabel: 'Abrir contas' },
      { track: 'Segredos', items: ['IDs de projeto, ambiente e serviço no estado desejado.', 'Allowlist com as variáveis do serviço.'], cmd: 'scripts/cp-secrets sync plan <cliente>/<projeto>' },
      { track: 'Hospedagem', items: ['A Railway cuida do container. O painel mostra versão e estado e leva até lá.', 'Alguns projetos exigem aprovar o deploy na própria Railway.'] },
      { track: 'Logs', items: ['Mesmo pacote e mesmo gateway da API em container.'], cmd: 'scripts/cp-obs ingest <cliente>/<projeto>/<ambiente>' },
    ],
  },
};

// Do exemplo ao real: o que substitui cada parte hachurada, e quando.
export const REPLACE = [
  { area: 'Esta máquina', source: 'Leitura direta: portas, Docker, seal-status e secrets.toml', phase: 'Já é real' },
  { area: 'Aplicações, versões e containers', source: 'API do Coolify; Vercel e Railway com a sua sessão', phase: 'Fase 1, no laboratório' },
  { area: 'Logs', source: 'OpenObserve, já filtrado pela allowlist', phase: 'Fase 1, no laboratório' },
  { area: 'Contas e validade', source: 'Metadados do cofre, sem os valores', phase: 'Fase 1, no laboratório' },
  { area: 'Divergências', source: 'cp-secrets sync plan, em saída estruturada', phase: 'Fase 2' },
  { area: 'Ações e atividade', source: 'Os mesmos scripts, com a sessão do operador', phase: 'Fase 2' },
  { area: 'Novo cliente', source: 'Grava openbao/clients/<cliente>.toml e aplica até dev', phase: 'Fase 3' },
  { area: 'Acesso de qualquer device', source: 'VPS só na tailnet, com login e MFA', phase: 'Fase 4, go-live' },
];

export const GUIDE_KINDS = [['all', 'Todos'], ['rot', 'Rotina'], ['cfg', 'Configurar'], ['inc', 'Incidente']];

export const GUIDES = [
  { id: 'painel-outro-device', k: 'cfg', title: 'Abrir o painel em outro device', when: 'Device novo, sem cofre nem Docker', where: 'Terminal', steps: ['Clone o repositório e troque para a branch do painel.', 'Rode o painel. Ele só precisa de Python.', 'Abra o endereço no navegador do próprio device.', 'Em Configurar, veja o que este device tem e o que falta.'], warn: 'não copie .init.json nem .bootstrap.env para ver o painel. Este device não precisa deles.', cmd: 'git clone git@github.com:Easy-Goal/control-plane.git\ncd control-plane\ngit switch feat/painel\nscripts/cp-panel', to: '#/configurar', goLabel: 'Conferir esta máquina' },
  { id: 'health-stay-neon', k: 'cfg', title: 'Rodar o Health Stay com Neon', when: 'Device sem Docker, com front e API locais', where: 'Neon e terminal', steps: ['No Neon, crie o projeto health-stay-dev e o branch dev, seguindo docs/DEV-REMOTO.md do backend.', 'No backend, atualize o main, instale e copie o .env.example.', 'Gere JWT_SECRET e AES_KEY direto no .env.', 'Abra o .env no editor e preencha DATABASE_URL (com pool), DIRECT_DATABASE_URL (direta) e as três senhas SEED_*_PASSWORD.', 'Aplique as migrations, rode o seed e confira. Depois, suba a API.', 'No front, instale e suba. Ele usa localhost:3001 sem configurar nada.', 'Entre em localhost:3000/login com admin, proprietario ou hospede@healthstay.dev. O painel mostra os dois no ar.'], warn: 'só dados fictícios no Neon. As URLs têm a senha do banco: copie do painel do Neon direto para o .env, nunca para chat, issue ou PR.', cmd: '# backend\ngit switch main && git pull\nnvm use && corepack enable\npnpm install --frozen-lockfile\ncp .env.example .env\nsed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -base64 32)|" .env\nsed -i "s|^AES_KEY=.*|AES_KEY=$(openssl rand -hex 32)|" .env\n# preencha as URLs e as senhas no editor\npnpm db:migrate:deploy\npnpm db:seed\npnpm setup:check\npnpm dev\n\n# front, em outro terminal\ngit switch main && git pull\nnvm use && corepack enable\npnpm install --frozen-lockfile\npnpm dev', link: 'https://console.neon.tech', linkLabel: 'Abrir o Neon', to: '#/configurar', goLabel: 'Conferir se subiu' },
  { id: 'comecar-o-dia', k: 'rot', title: 'Começar o dia', when: 'Todo dia de trabalho', where: 'Painel', steps: ['Abra o Quadro.', 'Se o cofre estiver selado, faça o unseal.', 'Resolva a lista de atenção, de cima para baixo.'], cmd: 'scripts/cp-secrets status\nscripts/cp-secrets sync plan', to: '#/quadro', goLabel: 'Abrir o Quadro' },
  { id: 'importar-env', k: 'cfg', title: 'Importar o .env de um projeto para o cofre', when: 'Projeto entrando no cofre pela primeira vez', where: 'Terminal', steps: ['No estado desejado, declare o repositório do projeto com import_env, indicando o arquivo e o ambiente.', 'Veja o plano. Ele só cria as chaves que faltam.', 'Aplique e confira os nomes.'], warn: 'um .env local costuma ter valor de dev. Confira antes de levar qualquer coisa para produção.', cmd: '# em [[client.project.repo]]\nimport_env = { file = ".env", environment = "dev" }\n\nscripts/cp-secrets plan\nscripts/cp-secrets apply\nscripts/cp-secrets keys <cliente>/<projeto>/dev' },
  { id: 'levar-segredos', k: 'rot', title: 'Levar segredos para os destinos', when: 'Depois de toda mudança de segredo', where: 'Painel', steps: ['Abra o cliente e veja as diferenças, só por nome.', 'Em divergência, decida qual valor vence.', 'Confirme. Em prod, é preciso digitar o nome.', 'Acompanhe o resultado em Atividade.'], warn: 'se alguém mudou no destino, o sync restaura o valor do cofre. Se o do destino for o certo, grave-o no cofre antes.', cmd: 'scripts/cp-secrets sync plan\nscripts/cp-secrets sync apply easygoal/health-stay', to: '#/clientes', goLabel: 'Abrir clientes' },
  { id: 'renovar-token', k: 'rot', title: 'Renovar o token de uma conta', when: 'Quando o painel avisar, 15 dias antes', where: 'Painel e plataforma', steps: ['Em Contas, abra a conta.', 'Crie o token novo na plataforma do cliente.', 'Grave no cofre com o comando pronto da conta.', 'Teste e revogue o antigo.'], cmd: 'scripts/cp-secrets provider set easygoal vercel --stdin token --expires "$(date -u -d \'+90 days\' +%F)"', to: '#/contas', goLabel: 'Abrir contas' },
  { id: 'backup-cofre', k: 'rot', title: 'Fazer backup do cofre', when: 'Antes de mudanças grandes', where: 'Terminal e Drive', steps: ['Gere o snapshot.', 'Copie para o Drive.', 'Nunca guarde o snapshot junto das chaves de unseal.'], cmd: 'scripts/cp-secrets backup' },
  { id: 'audit', k: 'rot', title: 'Conferir quem leu o quê', when: 'Semanal, ou se houver suspeita', where: 'Cofre', steps: ['Veja as leituras por identidade e ambiente.', 'Procure acessos negados e identidades inesperadas.'], cmd: 'scripts/cp-secrets audit 168' },
  { id: 'cliente-novo', k: 'cfg', title: 'Cliente novo', when: 'A cada contrato', where: 'Painel', steps: ['Clique em Novo cliente.', 'Siga as etapas: contas, projetos, variáveis e revisão.', 'Dev é aplicado primeiro. Prod, quando você decidir.'], cmd: 'scripts/cp-secrets provider set <cliente> vercel team_id=<team_id> --stdin token --expires <data>\nscripts/cp-secrets plan\nscripts/cp-secrets apply\nscripts/cp-secrets sync plan', to: '#/novo-cliente', goLabel: 'Começar' },
  { id: 'ligar-logs', k: 'cfg', title: 'Ligar logs em um app', when: 'Uma vez por app e ambiente', where: 'Terminal', steps: ['Crie a org e o token de envio.', 'Inclua as chaves OBS_* na allowlist.', 'Leve para o destino.'], warn: 'o app precisa usar o pacote @easygoal/observability.', cmd: 'scripts/cp-obs ingest easygoal/health-stay/staging\nscripts/cp-secrets sync apply easygoal/health-stay' },
  { id: 'ligar-analytics', k: 'cfg', title: 'Ligar analytics em um front', when: 'Uma vez por front e ambiente', where: 'Terminal e código', steps: ['Crie o site no Umami.', 'Inclua as duas chaves na allowlist e leve para o destino.', 'Adicione o script no layout do Next.'], cmd: 'scripts/cp-obs analytics easygoal/site-easygoal/prod --domain easygoal.com.br' },
  { id: 'vps-nova', k: 'cfg', title: 'VPS de app nova', when: 'Uma vez por VPS, inclusive Droplet de cliente', where: 'Terminal', steps: ['Copie a chave pública do Coolify.', 'Rode o instalador dentro da VPS, como root.', 'Cadastre o servidor no Coolify.', 'Confira se ficou utilizável.'], warn: 'o instalador roda dentro da VPS, por isso este passo sempre fica no terminal.', cmd: 'scripts/cp-coolify key\nCOOLIFY_PUBKEY="<chave>" SERVER_TAG=app-prd TS_AUTHKEY=<auth key> bash /opt/cp-install/app-server.sh\nscripts/cp-coolify server add <nome> <ip na tailnet>' },
  { id: 'banco-backup', k: 'cfg', title: 'Banco e backup de um projeto', when: 'Uma vez por projeto e ambiente', where: 'Terminal', steps: ['Crie o Postgres gerenciado.', 'Agende o backup.', 'Teste um backup e uma restauração.'], cmd: 'scripts/cp-coolify db ensure <projeto> <ambiente> <servidor> <nome> <caminho>\nscripts/cp-coolify backup ensure <nome> <destino>' },
  { id: 'cliente-saiu', k: 'cfg', title: 'Cliente saiu', when: 'Fim de contrato', where: 'Painel e manual', steps: ['Abra o cliente e clique em Encerrar.', 'Faça os passos manuais listados.'], warn: 'a Easy Goal nunca passa por este fluxo.', cmd: 'scripts/cp-secrets backup\nscripts/cp-secrets offboard <cliente>\nscripts/cp-obs revoke <cliente>', to: '#/clientes', goLabel: 'Abrir clientes' },
  { id: 'reiniciei', k: 'inc', title: 'Reiniciei o Docker ou a VPS', when: 'Cofre selado depois de reiniciar', where: 'Terminal', steps: ['As apps continuam no ar.', 'Tenha 2 das 3 chaves de unseal.', 'Faça o unseal. As chaves nunca passam pelo painel.'], cmd: 'scripts/cp-secrets unseal' },
  { id: 'vazou-segredo', k: 'inc', title: 'Vazou um segredo', when: 'Vazamento confirmado', where: 'Cofre e terminal', steps: ['Troque o segredo sem janela. Quem depende dele é afetado na hora.', 'Leve para os destinos.', 'Revogue o antigo na plataforma, se for o caso.', 'Confira o audit das últimas 72 h.'], warn: 'AES_KEY cifra dado de saúde e não pode ser trocada direto: exige recifrar os dados.', cmd: 'scripts/cp-secrets secret gen easygoal/health-stay/prod JWT_SECRET\nscripts/cp-secrets sync apply easygoal/health-stay\nscripts/cp-secrets audit 72' },
  { id: 'vazou-ingestao', k: 'inc', title: 'Vazou o token de envio de logs', when: 'Token exposto', where: 'Terminal', steps: ['Gere um token novo. O antigo para na hora.', 'Leve para o destino logo depois, para o app não parar de enviar.'], cmd: 'scripts/cp-obs ingest easygoal/health-stay/staging --rotate\nscripts/cp-secrets sync apply easygoal/health-stay' },
  { id: 'rotacionar-sso', k: 'inc', title: 'Rotacionar o SSO', when: 'Rotina ou incidente', where: 'Terminal', steps: ['Confira os membros e o assinante no plano.', 'Aplique o modo gradual.', 'Espere a janela de pelo menos 7 dias.', 'Encerre a janela.'], warn: 'sem as branches de chave dupla em produção, todos são deslogados.', cmd: 'scripts/cp-secrets rotate easygoal/sso-global prod\nscripts/cp-secrets rotate easygoal/sso-global prod --apply\nscripts/cp-secrets rotate easygoal/sso-global prod --finish --apply' },
];

export const TOOLS = [
  { id: 'cofre', name: 'Cofre (OpenBao)', purpose: 'É onde ficam os valores, o unseal e o audit completo. O acesso é sempre separado do painel.', goFor: 'ver ou corrigir um valor e conferir o audit.', login: 'token de 1 hora, gerado com scripts/cp-secrets ui-token.', checks: { local: 'vault_local', lab: 'vault_lab' } },
  { id: 'coolify', name: 'Coolify', purpose: 'Deploy e operação dos containers.', goFor: 'log bruto, CPU, memória e configuração de um service.', login: 'e-mail e senha do Coolify.', checks: { lab: 'coolify_lab' }, base: 'http://127.0.0.1:8000' },
  { id: 'openobserve', name: 'OpenObserve', purpose: 'Consulta avançada de logs.', goFor: 'SQL, dashboards e alertas.', login: 'e-mail do admin e senha guardada no cofre.', checks: { local: 'oo_local', lab: 'oo_lab' }, baseBy: { local: 'http://127.0.0.1:15080', lab: 'http://127.0.0.1:5080' } },
  { id: 'umami', name: 'Umami', purpose: 'Analytics de cada site.', goFor: 'visitas e eventos.', login: 'usuário admin e senha guardada no cofre.', checks: { local: 'umami_local', lab: 'umami_lab' }, baseBy: { local: 'http://127.0.0.1:13300', lab: 'http://127.0.0.1:3300' } },
];

export const WIZ_PLATFORMS = {
  vercel: { name: 'Vercel', desc: 'Fronts, na conta do cliente.' },
  railway: { name: 'Railway', desc: 'APIs, enquanto não migram.' },
  github: { name: 'GitHub', desc: 'Segredos do Actions, pela GitHub App.' },
  coolify: { name: 'Coolify', desc: 'Containers, em um time só do cliente.' },
  droplet: { name: 'Droplet da DigitalOcean', desc: 'Servidor do cliente, operado pelo Coolify.' },
};
