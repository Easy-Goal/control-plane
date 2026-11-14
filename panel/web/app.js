// Painel do control plane. Sem build e sem dependências.
// "Sólido" vem de /api/device, lido agora. "Hachurado" vem de /api/data enquanto a área for exemplo.
import { ICONS } from './icons.js';
import { ACCOUNT_STATE, APP_TYPES, CHECKS, EXTERNAL_TOOLS, GUIDES, GUIDE_KINDS, HOME, PROVIDERS, REPLACE, TOOLS, TRACKS, WIZ_PLATFORMS } from './content.js';

const DEMO_KEY = 'cp-panel-demo-v1';
const POLL_MS = 15000;
const ACTIVITY_MS = 60000;
const KEY_STORE = 'cp-panel-key';
const SIDE_KEY = 'cp-panel-side';
const ACCOUNT_PENDING = ['expired', 'missing', 'soon'];

// Template com escape por padrão: só o que passou por h`` entra como HTML.
class Raw { constructor(s) { this.s = s; } }
const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ser = (v) => {
  if (v === null || v === undefined || v === false) return '';
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(ser).join('');
  return esc(v);
};
const h = (strings, ...vals) => new Raw(strings.reduce((out, str, i) => out + ser(vals[i - 1]) + str));

const icon = (name) => new Raw(`<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name] || ''}</svg>`);

const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* sem persistência */ } },
  del(key) { try { localStorage.removeItem(key); } catch { /* sem persistência */ } },
};

const S = {
  device: null, auth: null, machines: null, setup: null, setupStep: '', setupForm: { name: '', role: 'teste', origin: '' }, setupError: '', data: null, base: null, failed: false, target: store.get('cp-panel-target') || 'local',
  theme: store.get('cp-panel-theme') || 'dark', navOpen: false, logPage: 0,
  fApps: { client: '', type: '', state: '', q: '' }, fLogs: { client: '', env: '', level: '', q: '' },
  openLog: null, openAct: null, gKind: 'all', gQuery: '', wiz: null, modal: null, toast: '',
};

const emptyWiz = () => ({ step: 1, name: '', plat: { vercel: true, railway: false, github: false, coolify: true, droplet: false }, extra: '', projOff: {}, projExtra: [], logs: true, analytics: false, run: 0, vars: [{ name: 'JWT_SECRET', origin: 'generated' }, { name: 'DATABASE_URL', origin: 'manual' }], newVar: '', newVarOrigin: 'manual' });
const plain = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const toSlug = (s) => plain(s).replace(/[^a-z0-9]+/g, '').slice(0, 31); // sem hífen: o nome da org de logs é <cliente>_<ambiente>
const toProject = (s) => plain(s).replace(/[^a-z0-9]+/g, '-').replace(/^[^a-z]+|-+$/g, '');

// ---------- Marcas de estado: forma + cor + texto; hachura = exemplo ----------
const mark = (kind, label, ex = false) => h`<span class="mark mark-${kind}${ex ? ' is-ex' : ''}"><i aria-hidden="true"></i>${label}</span>`;
const SOLID = { ok: ['ok', 'Pronto'], warn: ['warn', 'Atenção'], missing: ['todo', 'Falta'], off: ['off', 'Opcional aqui'] };
const READY = { ok: ['ok', 'Feito'], todo: ['warn', 'Falta'], err: ['err', 'Com problema'], na: ['off', 'Não usa'] };
const ENV_STATE = { running: ['ok', 'Rodando'], degraded: ['err', 'Com problema'], waiting: ['warn', 'Aguardando'], unread: ['off', 'Não lido'] };
const typeName = (t) => APP_TYPES[t]?.name || t;
const isDemo = (area) => S.data?.sources?.[area] === 'demo';
const rowEx = (row) => !['live', 'config'].includes(row?.source);
const realView = () => S.setup?.view === 'real';
const installed = () => S.setup?.layout === 'installed';
const homeId = () => S.setup?.home_client || S.data?.clients[0]?.id || '';
const conn = () => S.data?.connection || { state: 'off', problems: [] };
const session = {
  get() { try { return sessionStorage.getItem(KEY_STORE); } catch { return null; } },
  set(v) { try { sessionStorage.setItem(KEY_STORE, v); } catch { /* sem chave, sem ações */ } },
};
if (location.hash.startsWith('#k=')) { session.set(location.hash.slice(3)); history.replaceState(null, '', `${location.pathname}#/quadro`); }
const actionsOn = () => Boolean(conn().actions?.enabled);
const remoteOn = () => Boolean(S.auth?.remote);
const canAct = () => actionsOn() && (remoteOn() ? ['operacao', 'lab'].includes(S.auth.device?.class) : Boolean(session.get()));
const realBtn = (label, attrs, cls = 'btn btn-small') => h`<button class="${cls}" data-act="realask" data-action="${attrs.action}" data-label="${attrs.label}" data-client="${attrs.client}" data-app="${attrs.app || ''}" data-env="${attrs.env || ''}" data-target="${attrs.target || ''}" data-provider="${attrs.provider || ''}" data-confirm="${attrs.confirm || ''}">${label}</button>`;
const connected = () => conn().state !== 'off';
const previousEnv = (a) => a.envs.staging || a.envs.dev;
const previousName = (a) => (a.envs.staging ? 'staging' : 'dev');
const isBehind = (a) => { const from = previousEnv(a); return from && a.envs.prod && !from.moving && !a.envs.prod.moving && from.state !== 'unread' && a.envs.prod.state !== 'unread' && from.version !== a.envs.prod.version && !/^Sem leitura/.test(from.version); };
const WHERE = { lab: { de: 'do laboratório', a: 'ao laboratório', em: 'no laboratório' }, local: { de: 'da stack local', a: 'à stack local', em: 'na stack local' } };
const where = () => WHERE[conn().target] || { de: 'do cofre', a: 'ao cofre', em: 'no cofre' };
const areaNote = (area) => (S.data?.sources?.[area] === 'mixed' ? exNote(`Linhas sólidas vieram agora ${where().de}. As hachuradas continuam sendo exemplo.`) : exNote());
const clientName = (id) => S.data.clients.find((c) => c.id === id)?.name || id;
const accountsOf = (client) => S.data.accounts.filter((a) => a.client === client);
const targetName = { local: 'Stack local', lab: 'Laboratório', vps: 'VPS' };

// Conectado ao laboratório, o comando mostrado é o que roda lá: sem isso, ele iria para o cofre principal.
const forTarget = (text) => (conn().target !== 'lab' ? text : text
  .replace(/ssh root@<cp> CP_CLIENT=(\S+) bash/g, 'docker exec -i -e CP_CLIENT=$1 cp-sim-sim-cp-1 bash')
  .replace(/ssh root@<cp> bash/g, 'docker exec -i cp-sim-sim-cp-1 bash')
  .replace(/http:\/\/<cp>:8000/g, 'http://127.0.0.1:8000')
  .replace(/scripts\/(cp-secrets|cp-coolify|cp-obs)/g, 'scripts/cp-lab $1'));
// Instalado, o que depende do repositório vira um aviso: a tela nunca manda rodar o que não existe aqui.
const NOT_PACKAGED = /sim\/lab\.sh|install\/|scripts\/cp-local|cp-sim-sim/;
const copyBlock = (raw, label = 'Copiar comando', exact = false) => {
  if (installed() && NOT_PACKAGED.test(raw)) return h`<p class="muted">Este passo ainda não vem no pacote instalado. Ele chega com a VPS e os módulos: veja <code>docs/proximos-passos.md</code> na pasta do programa.</p>`;
  const text = exact ? raw : forTarget(raw); // exact: o comando já diz em qual cofre roda
  return h`
  <div class="cmd"><pre tabindex="0"><code>${text}</code></pre>
    <button class="btn btn-small" data-act="copy" data-text="${text}">${label}</button></div>`;
};
const exNote = (text = 'Exemplo. Nada aqui é real nem é executado.') => (realView() ? (connected() ? '' : h`<p class="muted">Só o que a conta declara. O estado real aparece quando esta máquina se conectar ao cofre.</p>`) : h`
  <p class="ex-note"><span class="hatch" aria-hidden="true"></span>${text} <a href="#/configurar/real">O que substitui isso</a></p>`);

// ---------- Leitura do device ----------
const visibleChecks = () => (S.device?.checks || []).filter((c) => !c.target || c.target === 'all' || c.target === S.target);
const FOR_INSTALL = {
  vault_local: { name: 'Cofre', steps: ['Precisa de Docker. O cofre roda só nesta máquina.', 'Na primeira vez, inicialize e guarde as chaves no seu gerenciador de senhas. Elas não ficam no painel.', 'Ele volta selado a cada reinício: faça o unseal com 2 das 3 chaves.', 'Abra o painel conectado ao cofre.'], cmd: 'cplane vault up\ncplane secrets init\ncplane secrets apply\ncplane --cofre' },
  desired: { name: 'Conta', steps: ['É a lista de clientes, contas e projetos, só com nomes.', 'Conta vinda de um repositório: rode o comando para receber as mudanças.'], cmd: 'cplane import' },
  vps: { steps: ['Na VPS, instale como nesta máquina e importe a mesma conta.', 'Restaure o snapshot do cofre e faça o unseal.', 'Promova a VPS a principal, pelo terminal dela.', 'Crie a conta de acesso e abra para outras máquinas: veja a tela Máquinas.'], cmd: 'sh install.sh\ncplane import <repositório>\ncplane machine promote\ncplane account create\ncplane --remoto --sem-navegador' },
};
const checkView = (c) => {
  const base = CHECKS[c.id] || { name: c.name || c.id, track: c.track || 'maquina', optional: c.optional, steps: [] };
  const meta = installed() ? { ...base, ...(FOR_INSTALL[c.id] || {}), doc: '' } : base;
  const state = c.state === 'missing' && meta.optional ? 'off' : c.state;
  return { ...c, ...meta, viewState: state };
};
const trackState = (id) => {
  const rows = visibleChecks().map(checkView).filter((c) => c.track === id);
  if (!rows.length) return 'off';
  if (rows.some((c) => c.viewState === 'warn')) return 'warn';
  if (rows.some((c) => c.viewState === 'missing')) return 'missing';
  return rows.some((c) => c.viewState === 'off') ? 'off' : 'ok';
};
const pendingChecks = () => visibleChecks().map(checkView).filter((c) => c.viewState === 'warn' || c.viewState === 'missing');
const vaultCheck = () => (S.device?.checks || []).find((c) => c.id === (S.target === 'lab' ? 'vault_lab' : 'vault_local'));

function headline() {
  if (conn().state === 'connected') {
    const n = attention().filter((a) => !a.ex).length;
    return n ? `${n === 1 ? '1 item real pede' : `${n} itens reais pedem`} atenção ${where().em}.` : `Nada real pede atenção ${where().em}.`;
  }
  if (!S.device) return 'Lendo esta máquina.';
  if (realView() && !S.data.clients.length) return 'Crie o primeiro cliente para organizar seus projetos.';
  if (S.target === 'vps') return 'Nenhuma VPS cadastrada nesta conta. Veja como ela vai ficar.';
  const v = vaultCheck();
  if (v?.sealed) return `Cofre selado em ${targetName[S.target].toLowerCase()}. Faça o unseal para operar.`;
  if (v?.state === 'ok') return 'O cofre está aberto nesta máquina. Pode operar.';
  return 'Esta máquina ainda não tem cofre. O painel ensina a configurar.';
}

// ---------- Moldura ----------
const NAV = [
  ['Operar', [['quadro', 'Quadro', 'layout-dashboard'], ['clientes', 'Clientes', 'building-2'], ['aplicacoes', 'Aplicações', 'boxes'], ['logs', 'Logs', 'scroll-text'], ['atividade', 'Atividade', 'history']]],
  ['Preparar', [['configurar', 'Configurar', 'sliders-horizontal'], ['maquinas', 'Máquinas', 'laptop'], ['contas', 'Contas', 'key-round'], ['guias', 'Guias', 'book-open'], ['ferramentas', 'Ferramentas', 'wrench']]],
];
const attentionBadge = () => { // conectado, o número conta só o que é real; sem conexão, tudo é exemplo
  const list = attention();
  return connected() ? { n: list.filter((a) => !a.ex).length, ex: false } : { n: list.length, ex: true };
};
const countBadge = (n, ex) => (n ? h`<span class="count${ex ? ' is-ex' : ''}">${n}<span class="sr"> ${ex ? 'de exemplo' : 'pendentes'}</span></span>` : '');
const vaultLink = () => { const v = vaultCheck(); return v?.state === 'ok' || v?.sealed ? { href: v.url, ext: true } : { href: '#/ferramentas', ext: false }; };

function sidebar(active) {
  const side = store.get(SIDE_KEY) === 'collapsed';
  const link = ([id, name, ic]) => {
    const badge = id === 'quadro' ? attentionBadge() : { n: id === 'configurar' ? pendingChecks().length : 0, ex: false };
    return h`<a class="nav-link${active === id ? ' is-on' : ''}" href="#/${id}" title="${name}"${active === id ? h` aria-current="page"` : ''}>${icon(ic)}<span class="nav-label">${name}</span>${countBadge(badge.n, badge.ex)}</a>`;
  };
  return h`
  <aside class="side" id="side" aria-label="Menu">
    <div class="side-brand">
      <a class="brand" href="#/quadro">${icon('shield-check')}<span>Control Plane</span></a>
      <button class="icon-btn side-toggle" data-act="sidetoggle" title="${side ? 'Expandir menu' : 'Recolher menu'}" aria-label="${side ? 'Expandir menu' : 'Recolher menu'}">${icon(side ? 'chevron-right' : 'chevron-left')}</button>
      <button class="icon-btn top-menu" data-act="navclose" aria-label="Fechar menu">${icon('x')}</button>
    </div>
    <div class="side-scroll" id="side-scroll">
      <a class="btn btn-pri side-new" href="#/novo-cliente" title="Novo cliente" aria-label="Novo cliente">${icon('plus')}<span>Novo cliente</span></a>
      ${NAV.map(([title, items]) => h`<nav class="nav-group" aria-label="${title}"><p class="side-title">${title}</p>${items.map(link)}</nav>`)}
      <section class="side-device nav-group" aria-label="Esta máquina">
        <p class="side-title">Esta máquina</p>
        ${TRACKS.filter((t) => t.id !== 'maquina').map((t) => { const [k, l] = SOLID[trackState(t.id)]; return h`<a class="side-track" href="#/configurar/maquina#${t.id}" title="${t.name}: ${l}"><span class="sig sig-${k}"><span class="sr">${l}: </span></span><span class="nav-label">${t.name}</span></a>`; })}
      </section>
    </div>
  </aside>`;
}

function crumbs(r) {
  const out = [];
  const add = (label, to) => out.push([label, to]);
  const main = NAV.flatMap(([, items]) => items).find(([id]) => id === r.name);
  if (r.name === 'novo-cliente') { add('Clientes', '#/clientes'); add('Novo cliente'); }
  else add(main ? main[1] : 'Quadro', r.arg ? `#/${r.name}` : '');
  if (r.name === 'clientes' && r.arg) {
    const c = S.data.clients.find((x) => x.id === r.arg);
    add(c?.name || 'Cliente não encontrado', r.sub ? `#/clientes/${r.arg}` : '');
    const tab = CLIENT_TABS.find(([id]) => id === r.sub);
    if (tab && r.sub !== 'visao') add(tab[1]);
  }
  if (r.name === 'aplicacoes' && r.arg) {
    const a = S.data.apps.find((x) => x.id === r.arg);
    if (a) add(clientName(a.client), `#/clientes/${a.client}`);
    add(a?.name || 'Aplicação não encontrada', r.sub ? `#/aplicacoes/${r.arg}` : '');
    if (r.sub) add(r.sub);
  }
  if (r.name === 'contas' && r.arg) { const a = S.data.accounts.find((x) => x.id === r.arg); add(a ? `${PROVIDERS[a.provider].name} de ${clientName(a.client)}` : 'Conta não encontrada'); }
  if (r.name === 'guias' && r.arg) add(guideList().find((g) => g.id === r.arg)?.title || 'Guia não encontrado');
  if (r.name === 'configurar' && r.arg) add(CONFIG_TABS.find(([id]) => id === r.arg)?.[1] || r.arg);
  return out;
}

function topbar(r) {
  const c = conn();
  const badge = attentionBadge();
  const v = vaultLink();
  const source = c.state === 'connected'
    ? mark('ok', `${targetName[c.target] || 'Cofre'}, até ${hhmm(c.expires_at)}`)
    : c.state === 'off' ? (realView() ? mark('off', 'Sem cofre') : mark('off', 'Só exemplos', true)) : mark('err', c.state === 'expired' ? 'Sessão vencida' : 'Sem cofre');
  const themeIcon = { auto: 'monitor', light: 'sun', dark: 'moon' }[S.theme];
  const themeName = { auto: 'automático', light: 'claro', dark: 'escuro' }[S.theme];
  return h`
  <header class="top">
    <button class="icon-btn top-menu" data-act="navopen" aria-label="Abrir menu" aria-expanded="${S.navOpen}" aria-controls="side">${icon('menu')}</button>
    <nav class="crumbs" aria-label="Caminho"><ol>${crumbs(r).map(([label, to]) => h`<li>${to ? h`<a href="${to}">${label}</a>` : h`<span>${label}</span>`}</li>`)}</ol></nav>
    <div class="top-actions">
      <a class="top-source" href="#/configurar/maquina#conexao" title="De onde vêm os dados desta tela">${source}</a>
      ${remoteOn() && h`<span class="top-who" title="Este dispositivo">${S.auth.device?.name}, ${S.auth.device?.class_name}</span><button class="btn btn-small" data-act="logout">Sair</button>`}
      ${actionsOn() && !(remoteOn() && !canAct()) && h`<a class="top-source" href="#/atividade" title="${canAct() ? 'Os botões das linhas sólidas executam de verdade no laboratório.' : 'Abra o link que o terminal mostrou.'}">${canAct() ? mark('warn', 'Ações ligadas') : mark('off', 'Ações sem chave')}</a>`}
      <a class="icon-btn top-bell" href="#/quadro" title="Precisa de atenção" aria-label="Precisa de atenção">${icon('bell')}${countBadge(badge.n, badge.ex)}</a>
      <a class="icon-btn" href="${v.href}"${v.ext ? h` target="_blank" rel="noopener"` : ''} title="Abrir o cofre" aria-label="Abrir o cofre">${icon('vault')}</a>
      <button class="icon-btn" data-act="theme" title="Tema: ${themeName}" aria-label="Tema: ${themeName}. Trocar">${icon(themeIcon)}</button>
    </div>
  </header>`;
}

// ---------- Componentes ----------
const pageHead = (title, lede, actions) => h`<header class="page-head"><div><h1>${title}</h1>${lede && h`<p class="lede">${lede}</p>`}</div>${actions && h`<div class="btns">${actions}</div>`}</header>`;
const stat = ({ label, value, note, to, kind = '', ic, ex, appState }) => h`<a class="stat${kind ? ` stat-${kind}` : ''}${ex ? ' is-ex' : ''}" href="${to}"${appState ? h` data-act="appstate" data-state="${appState}"` : ''}><span class="stat-top">${icon(ic)}${label}</span><b class="stat-val">${value}</b><span class="stat-note">${note}</span></a>`;
const empty = (ic, title, text, action) => h`<div class="empty">${icon(ic)}<h2>${title}</h2>${text && h`<p>${text}</p>`}${action}</div>`;
const progressBar = (done, total, label) => h`<div class="progress"><progress max="${total || 1}" value="${done}" aria-label="${label}"></progress><span class="progress-text">${done} de ${total}</span></div>`;
const tabsNav = (label, items, cur) => h`<nav class="tabs" aria-label="${label}">${items.map(([id, name, to, n]) => h`<a class="tab${id === cur ? ' is-on' : ''}" href="${to}"${id === cur ? h` aria-current="page"` : ''}>${name}${countBadge(n)}</a>`)}</nav>`;
// Diz de que é feito o número: um total nunca finge ser real se tiver exemplo no meio.
const originNote = (rows) => {
  const ex = rows.filter(rowEx).length;
  const real = rows.length - ex;
  if (!rows.length) return 'Nenhum agora';
  if (!ex) return 'Lido agora';
  if (!real) return 'Exemplo';
  return `${real} ${real === 1 ? 'real' : 'reais'}, ${ex} de exemplo`;
};
const allEx = (rows) => rows.length > 0 && rows.every(rowEx);

// ---------- Conexão com o cofre ----------
const actionHint = () => (actionsOn() ? 'abra o link que o terminal mostrou.' : remoteOn() ? 'este dispositivo não tem permissão, ou a principal abriu sem --acoes.' : installed() ? 'as ações pelo painel pedem login: veja em Máquinas.' : 'abra com scripts/cp-lab cp-panel --acoes.');
const hhmm = (iso) => (iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '');
function connBar() { // a barra do topo já diz de onde vêm os dados: aqui só entra o que pede uma ação
  const c = conn();
  if (c.state === 'off') return '';
  if (c.state === 'connected') {
    const noKey = actionsOn() && !canAct() && !remoteOn();
    if (!noKey && !(c.problems || []).length) return '';
    return h`<div class="conn" role="status">
      ${noKey && h`<p><b>Ações ligadas, mas este navegador não tem a chave.</b> Abra o link que o terminal mostrou.</p>`}
      ${(c.problems || []).map((p) => h`<p><b>${p.area}:</b> ${p.text} ${p.next}</p>`)}</div>`;
  }
  return h`<div class="conn conn-off" role="status"><p><b>${c.state === 'expired' ? 'A sessão de leitura venceu.' : 'Sem conexão com o cofre.'}</b> ${c.error || 'As linhas reais aparecem como não lidas.'} Para abrir uma sessão, encerre o painel e rode <code>${c.command}</code>.</p></div>`;
}
function connSection() {
  const c = conn();
  const rows = [
    ['Sessão de leitura', c.state === 'connected' ? `Ativa ${where().em}, até ${hhmm(c.expires_at)}. Nada dela é gravado em disco nem vai para o navegador.` : 'Sem sessão. O painel mostra só exemplos e o que lê desta máquina.'],
  ];
  return h`<section id="conexao" class="track" aria-labelledby="t-conexao"><div class="sec-head"><h2 id="t-conexao">Conexão com o cofre</h2><p class="muted">Opcional. É o que troca os exemplos por dados reais.</p></div>
    <ul class="checks">${rows.map(([name, text]) => h`<li class="check"><div class="check-line">${mark(c.state === 'connected' ? 'ok' : 'off', c.state === 'connected' ? 'Conectado' : 'Opcional aqui')}<span class="row-main"><b>${name}</b><span class="muted">${text}</span></span></div></li>`)}</ul>
    ${(c.problems || []).map((p) => h`<p class="conn-problem"><b>${p.area}:</b> ${p.text} ${p.next}</p>`)}
    ${installed() ? h`<details class="fold"><summary>Como conectar ao cofre</summary>
      <ol class="steps"><li>Suba o cofre. Precisa de Docker.</li><li>Na primeira vez, inicialize. As chaves de unseal ficam em um arquivo que você move para o gerenciador de senhas e apaga.</li><li>Crie as identidades da conta.</li><li>Abra o painel conectado. A sessão de leitura dura 1 h e é encerrada ao fechar.</li></ol>
      ${copyBlock(FOR_INSTALL.vault_local.cmd)}</details>` : h`<details class="fold"><summary>Como conectar ao laboratório</summary>
      <ol class="steps"><li>O cofre do laboratório precisa estar aberto e esta máquina precisa ter a credencial de operador.</li><li>Grave uma vez as credenciais só de leitura: o token do Coolify e as contas de logs.</li><li>Abra o painel pelo laboratório. Ele cria uma sessão de 1 h e a encerra ao fechar.</li></ol>
      ${copyBlock(`docker exec -i cp-sim-sim-cp-1 bash -s < install/coolify-read-token.sh | scripts/cp-lab cp-secrets provider set ${homeId()} coolify-sim-read url=http://127.0.0.1:8000 --stdin token --expires "$(date -u -d '+90 days' +%F)"\nCP_OBS_PROVIDER=openobserve-sim scripts/cp-lab cp-obs panel-read\nscripts/cp-lab cp-panel          # só leitura\nscripts/cp-lab cp-panel --acoes  # também age no laboratório: abra o link que o terminal mostrar`)}</details>`}</section>`;
}

// ---------- Máquinas: o que é real aqui é sempre real, sem exemplo ----------
const SEC_EVENT = {
  unknown_device: 'Dispositivo desconhecido pediu acesso', revoked_used: 'Dispositivo revogado tentou entrar', node_mismatch: 'Token usado de outra máquina da tailnet',
  origin_refused: 'Pedido sem origem identificada na tailnet',
  login_fail: 'Falha de login ou de código', lockout: 'Conta bloqueada por tentativas', device_approved: 'Dispositivo aprovado', device_revoked: 'Acesso revogado', device_class: 'Classe alterada',
  prod_action: 'Ação em produção', recovery_used: 'Código de recuperação usado', login: 'Entrada no painel', account_created: 'Conta de acesso criada',
};
const SEC_ERR = ['revoked_used', 'node_mismatch', 'origin_refused', 'lockout', 'recovery_used'];
const when = (iso) => (iso ? new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : 'nunca');
const recentAlerts = () => (S.machines?.events || []).filter((e) => Date.now() - new Date(e.at).getTime() < 86400000 && (S.machines.alert_kinds || []).includes(e.kind)).slice(0, 5);
async function loadMachines() {
  try {
    const res = await fetch('/api/machines');
    if (res.ok) S.machines = await res.json();
  } catch { /* o aviso de servidor fora do ar vem de pollDevice */ }
}
const ORIGIN_REASON = { sem_origem: 'sem o cabeçalho da tailnet', fora_da_tailnet: 'endereço fora da tailnet', whois_falhou: 'o Tailscale não identificou a máquina' };
const eventText = (e) => [e.device, e.reason && (ORIGIN_REASON[e.reason] || e.reason), e.who && `por ${e.who}`, e.by && `por ${e.by}`, e.node && `tailnet: ${e.node}`, e.seen && `visto como ${e.seen}, esperado ${e.expected}`, e.address, e.action].filter(Boolean).join(', ');
function deviceRow(d, manage) {
  const klass = S.machines.classes?.[d.class] || '';
  const state = { pending: ['warn', 'Aguardando'], approved: ['ok', klass], revoked: ['err', 'Revogado'] }[d.state];
  const seen = d.node ? `Na tailnet: ${d.node.name}${d.node.user ? `, de ${d.node.user}` : ''}` : 'Acesso local da principal, sem tailnet';
  return h`<li class="row-plain">${mark(state[0], state[1])}<span class="row-main"><b>${d.name}</b><span class="muted">${seen}${d.kind === 'install' ? `. Instalação ${d.instance?.role || ''} em ${d.instance?.os || ''}` : ''}</span>
    <span class="muted">${d.state === 'pending' ? `Pediu em ${when(d.created)}` : d.state === 'revoked' ? `Revogado em ${when(d.revoked_at)}` : `Aprovado por ${d.approved_by} em ${when(d.approved_at)}. Último acesso: ${when(d.last_seen)}`}</span></span>
    ${manage && h`<span class="btns row-actions">${d.state === 'pending' && h`<button class="btn btn-small" data-act="machineask" data-op="approve" data-id="${d.id}" data-name="${d.name}">Aprovar</button>`}${d.state === 'approved' && h`<button class="btn btn-small" data-act="machineask" data-op="class" data-id="${d.id}" data-name="${d.name}" data-class="${d.class}">Classe</button>`}${d.state !== 'revoked' && h`<button class="btn btn-small btn-danger" data-act="machineask" data-op="revoke" data-id="${d.id}" data-name="${d.name}">${d.state === 'pending' ? 'Recusar' : 'Revogar'}</button>`}</span>`}</li>`;
}
function viewMaquinas() {
  const m = S.machines;
  if (!m) return h`${pageHead('Máquinas')}<p class="muted" role="status">Lendo.</p>`;
  const manage = m.remote && S.auth?.device?.class === 'operacao';
  const pending = m.devices.filter((d) => d.state === 'pending');
  const rest = m.devices.filter((d) => d.state !== 'pending');
  return h`
  ${pageHead('Máquinas', 'Onde o control plane roda e quem pode acessá-lo. Nome e navegador só ajudam a reconhecer: quem autoriza é a aprovação, o token do dispositivo e o login com autenticador.')}
  <section class="section" aria-labelledby="mq-inst"><div class="sec-head"><h2 id="mq-inst">Instalações</h2><p class="muted">Cada uma tem id próprio. A conta tem uma só principal.</p></div>
    <dl class="facts"><div><dt>Esta máquina</dt><dd>${m.this.name || 'Sem registro'}</dd></div><div><dt>Papel</dt><dd>${m.this.role_name || 'Não definido'}</dd></div><div><dt>Id</dt><dd><code>${m.this.id || '–'}</code></dd></div>
      <div><dt>Principal da conta</dt><dd>${m.principal?.id ? `${m.principal.name}${m.principal.id === m.this.id ? ' (esta)' : ''}` : 'Nenhuma ainda'}</dd></div><div><dt>Acesso de outras máquinas</dt><dd>${m.remote ? `Ligado: ${m.tailnet.join(', ') || 'só nesta máquina'}` : 'Desligado'}</dd></div></dl>
    ${!m.remote && h`<details class="fold"><summary>Como abrir para outras máquinas</summary><ol class="steps"><li>Na máquina principal, promova e crie a conta de acesso, com senha e autenticador. Isso só existe no terminal.</li><li>Abra o painel com acesso remoto e publique só na tailnet.</li><li>Em cada dispositivo, abra o endereço e passe o código ao aprovador. O primeiro é aprovado pelo terminal.</li></ol>
      ${copyBlock('cplane machine promote\ncplane account create\ncplane --remoto --sem-navegador\ntailscale serve --bg --https=443 http://127.0.0.1:4700\ncplane devices approve <código> --classe operacao', 'Copiar comandos', true)}</details>`}
  </section>
  ${pending.length > 0 && h`<section class="section" aria-labelledby="mq-pend"><div class="sec-head"><h2 id="mq-pend">Pedidos aguardando</h2><p class="muted">Aprovar pede o código que aparece na tela do dispositivo: confira com quem pediu. Vencem em 30 minutos.</p></div><ul class="rows">${pending.map((d) => deviceRow(d, manage))}</ul>
    ${!manage && h`<p class="muted">Para aprovar, use um dispositivo de Operação ou o terminal da principal: <code>cplane devices approve &lt;código&gt; --classe operacao</code>.</p>`}</section>`}
  <section class="section" aria-labelledby="mq-dev"><div class="sec-head"><h2 id="mq-dev">Dispositivos</h2><p class="muted">Operação consulta e age. Consulta só lê. Lab/teste nunca alcança produção. Quem aplica é o servidor.</p></div>
    ${rest.length ? h`<ul class="rows">${rest.map((d) => deviceRow(d, manage))}</ul>` : empty('laptop', 'Nenhum dispositivo aprovado', 'Eles aparecem aqui depois do primeiro pedido.')}</section>
  ${m.account?.exists !== undefined && h`<section class="section" aria-labelledby="mq-acc"><div class="sec-head"><h2 id="mq-acc">Conta de acesso</h2></div>
    <dl class="facts"><div><dt>Usuário</dt><dd>${m.account.exists ? m.account.username : 'Não criada'}</dd></div><div><dt>Códigos de recuperação</dt><dd>${m.account.exists ? m.account.recovery_left : '–'}</dd></div><div><dt>Situação</dt><dd>${!m.account.exists ? 'Crie no terminal: cplane account create' : m.account.locked?.length ? `Bloqueio por tentativas em ${m.account.locked.join(', ')}. Espere 15 minutos` : 'Normal'}</dd></div></dl></section>`}
  <section class="section" aria-labelledby="mq-ev"><div class="sec-head"><h2 id="mq-ev">Eventos de segurança</h2><p class="muted">O registro fica nesta máquina: quem tem root nela pode alterá-lo. A lista protege o painel. Cofre, Coolify, logs e SSH têm acessos próprios.</p></div>
    ${m.events?.length ? h`<ul class="rows">${m.events.slice(0, 40).map((e) => h`<li class="row-plain">${mark(SEC_ERR.includes(e.kind) ? 'err' : (m.alert_kinds || []).includes(e.kind) ? 'warn' : 'off', when(e.at))}<span class="row-main"><b>${SEC_EVENT[e.kind] || e.kind}</b><span class="muted">${eventText(e)}</span></span></li>`)}</ul>` : empty('shield-check', 'Nenhum evento ainda', '')}</section>`;
}

// ---------- Entrar, quando o painel atende outras máquinas ----------
function viewAuth() {
  const a = S.auth;
  const err = S.authError && h`<p class="caution" role="alert">${S.authError}</p>`;
  let body;
  if (a.state === 'no_account') {
    body = h`<h1>Acesso ainda não configurado</h1><p class="lede">A conta de acesso é criada no terminal da principal, para ninguém conseguir criá-la pela rede.</p>${copyBlock('cplane account create', 'Copiar comando', true)}`;
  } else if (a.state === 'unknown') {
    body = h`<h1>Este dispositivo não é conhecido</h1><p class="lede">Peça acesso. Nada fica visível até alguém aprovar pelo código que vai aparecer aqui.</p>
      <label class="fld" for="a-name">Nome para reconhecer este dispositivo<input id="a-name" autocomplete="off" maxlength="40" placeholder="Notebook do trabalho"></label>${err}
      <div class="btns"><button class="btn btn-pri" data-act="authrequest">Pedir acesso</button></div>`;
  } else if (a.state === 'pending') {
    body = h`<h1>Aguardando aprovação</h1><p class="lede">Passe este código para quem aprova, por um canal em que você confia. Vale 30 minutos.</p>
      <p class="auth-code" aria-label="Código de aprovação"><code>${a.code}</code></p>
      <p class="muted">Quem aprova usa a tela Máquinas de um dispositivo de Operação ou o terminal da principal. Esta tela continua sozinha.</p>
      <p class="muted">No terminal da principal, quem aprova escolhe a classe:</p>${copyBlock(`cplane devices approve ${a.code} --classe <operacao|consulta|lab>`, 'Copiar comando', true)}`;
  } else if (a.state === 'revoked') {
    body = h`<h1>Acesso revogado</h1><p class="lede">Este dispositivo foi cortado da conta. A tentativa fica registrada. Se foi engano, fale com quem administra a principal.</p>`;
  } else if (a.state === 'node_mismatch') {
    body = h`<h1>Acesso recusado</h1><p class="lede">Este dispositivo foi aprovado em outra máquina da tailnet, ou no acesso local da principal. Isso acontece quando o token é copiado. A tentativa fica registrada.</p>`;
  } else if (a.state === 'origin_refused') {
    body = h`<h1>Acesso só pela tailnet</h1><p class="lede">A principal não identificou de qual máquina da tailnet veio este pedido. Entre pelo endereço da tailnet, com o Tailscale ligado nesta máquina. A tentativa fica registrada.</p>`;
  } else {
    body = h`<h1>Entrar</h1><p class="lede">${a.device?.name}, ${a.device?.class_name}.</p>
      <label class="fld" for="a-user">Usuário<input id="a-user" autocomplete="username" spellcheck="false"></label>
      <label class="fld" for="a-pass">Senha<input id="a-pass" type="password" autocomplete="current-password"></label>
      <label class="fld" for="a-code">Código do autenticador, ou um código de recuperação<input id="a-code" autocomplete="one-time-code" spellcheck="false"></label>${err}
      <div class="btns"><button class="btn btn-pri" data-act="authlogin">Entrar</button></div>`;
  }
  return h`<main class="setup" id="main" tabindex="-1"><p class="brand">${icon('shield-check')}<span>Control Plane</span></p>${body}</main>`;
}

async function authPost(path, body) {
  try {
    const res = await fetch(`/api/auth/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const out = await res.json().catch(() => ({}));
    return res.ok ? out : { error: out.error || 'O painel recusou o pedido.', status: res.status };
  } catch { return { error: 'O painel não respondeu.' }; }
}

// A leitura periódica não mantém a sessão viva: só gesto de alguém na tela conta como uso.
let lastActivity = Date.now();
function noteActivity() {
  if (!remoteOn() || S.auth.state !== 'ok' || Date.now() - lastActivity < ACTIVITY_MS) return;
  lastActivity = Date.now();
  authPost('activity', {});
}

async function refreshAuth() {
  const res = await fetch('/api/auth/state');
  S.auth = await res.json();
}

async function machinePost(body) {
  try {
    const res = await fetch('/api/machines', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const out = await res.json().catch(() => ({}));
    return res.ok ? out : { error: out.error || 'O painel recusou o pedido.' };
  } catch { return { error: 'O painel não respondeu.' }; }
}

// ---------- Quadro ----------
function attention() {
  if (!S.data) return [];
  const out = [];
  for (const a of S.data.apps) {
    for (const [env, e] of Object.entries(a.envs)) {
      if (e.state === 'degraded') out.push({ client: a.client, ex: rowEx(a), kind: 'err', label: 'Com problema', title: `${a.name} em ${env}`, sub: `${clientName(a.client)}. ${e.health}.`, next: 'Ver os logs filtrados.', to: `#/aplicacoes/${a.id}/${env}` });
      if (e.state === 'unread' && a.source !== 'config') out.push({ client: a.client, ex: false, kind: 'off', label: 'Não lido', title: `${a.name} em ${env}`, sub: e.health, next: 'Veja a conexão em Configurar.', to: '#/configurar/maquina#conexao' });
      if (e.backupFailed) out.push({ client: a.client, ex: rowEx(a), kind: 'err', label: 'Backup', title: `${a.name} em ${env}`, sub: `${clientName(a.client)}. ${e.backup}.`, next: rowEx(a) ? 'Fazer um backup agora.' : 'Confira o destino do backup no Coolify.', to: `#/aplicacoes/${a.id}/${env}` });
    }
  }
  for (const c of S.data.accounts) {
    if (c.source !== 'config' && ACCOUNT_PENDING.includes(c.state)) {
      const [k, l] = ACCOUNT_STATE[c.state];
      out.push({ client: c.client, ex: rowEx(c), kind: k, label: l, title: `${PROVIDERS[c.provider].name} de ${clientName(c.client)}`, sub: c.expires + '.', next: c.state === 'soon' ? 'Crie um token novo e troque antes de vencer.' : 'Crie o token na conta do cliente e grave no cofre.', to: `#/contas/${c.id}` });
    }
  }
  for (const m of S.machines?.devices || []) if (m.state === 'pending') out.push({ client: '', ex: false, kind: 'warn', label: 'Aguardando', title: `Pedido de acesso: ${m.name}`, sub: (m.node?.name ? `Na tailnet: ${m.node.name}. ` : '') + 'Só aprove se reconhecer o código na tela do dispositivo.', next: 'Abrir Máquinas.', to: '#/maquinas' });
  for (const e of recentAlerts()) if (SEC_ERR.includes(e.kind)) out.push({ client: '', ex: false, kind: 'err', label: 'Segurança', title: SEC_EVENT[e.kind], sub: `${e.device || 'Sem dispositivo'}. ${when(e.at)}.`, next: 'Abrir Máquinas.', to: '#/maquinas' });
  for (const d of S.data.diverge) out.push({ client: d.client, ex: true, kind: 'warn', label: 'Divergente', title: d.target, sub: `${clientName(d.client)}. O cofre e o destino têm valores diferentes.`, next: 'Decidir qual valor vence.', to: `#/clientes/${d.client}/destinos` });
  return out.sort((a, b) => Number(a.ex) - Number(b.ex)); // o que é real vem antes do exemplo
}

const rolloutCount = (id) => {
  const list = (S.data.rollout[id] || []).filter((p) => p.state !== 'na');
  return { done: list.filter((p) => p.state === 'ok').length, total: list.length };
};
function rolloutText(id) {
  const { done, total } = rolloutCount(id);
  return `${done} de ${total} etapas`;
}

const versionCell = (env, ex, strong, behind) => {
  if (!env) return h`<td class="cell-none"><span class="sr">Sem este ambiente</span></td>`;
  const [k, l] = ENV_STATE[env.state];
  return h`<td class="cell-version${strong ? ' is-prod' : ''}"><span class="sig sig-${k}${ex ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span><span>${env.version}</span>${behind && h`<span class="behind">Atrás de ${behind}</span>`}${env.moving && h`<span class="behind" title="A tag pode apontar para outra imagem amanhã">Tag móvel</span>`}</td>`;
};

function board() {
  const cols = [['conta', 'Conta'], ['segredos', 'Segredos'], ['host', 'Hospedagem'], ['logs', 'Logs']];
  return h`
  <section class="section" aria-labelledby="board-title">
    <div class="sec-head"><h2 id="board-title">Quadro de aplicações</h2>${areaNote('apps')}</div>
    <div class="scroll" tabindex="0" role="region" aria-labelledby="board-title">
    <table class="board">
      <thead><tr><th scope="col" class="col-name">Aplicação</th>${cols.map(([, n]) => h`<th scope="col" class="col-sig">${n}</th>`)}<th scope="col">Dev</th><th scope="col">Staging</th><th scope="col" class="col-prod">Em produção</th></tr></thead>
      ${S.data.clients.map((c) => h`
      <tbody>
        <tr class="group"><th colspan="8" scope="rowgroup"><a href="#/clientes/${c.id}">${c.name}</a><span class="group-meta">${rolloutText(c.id)}${(S.data.rollout[c.id] || []).some((p) => !rowEx(p)) ? '' : ', exemplo'}</span></th></tr>
        ${S.data.apps.filter((a) => a.client === c.id).map((a) => {
          const behind = isBehind(a) && previousName(a);
          const ex = rowEx(a);
          return h`<tr>
            <th scope="row" class="col-name"><a href="#/aplicacoes/${a.id}">${a.name}</a><span class="type">${typeName(a.type)}</span></th>
            ${cols.map(([key]) => { const [k, l] = READY[a.ready[key]]; return h`<td class="col-sig"><span class="sig sig-${k}${ex ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span></td>`; })}
            ${versionCell(a.envs.dev, ex)}${versionCell(a.envs.staging, ex)}
            ${versionCell(a.envs.prod, ex, true, behind)}
          </tr>`;
        })}
      </tbody>`)}
    </table></div>
    <p class="legend">${mark('ok', 'Feito')}${mark('warn', 'Falta')}${mark('err', 'Com problema')}${mark('off', 'Não usa')}</p>
  </section>`;
}

function viewQuadro() {
  const pending = pendingChecks();
  const list = attention();
  const apps = S.data.apps;
  const problem = apps.filter((a) => APP_FILTER_STATE(a, 'problem'));
  const behind = apps.filter(isBehind);
  const accounts = S.data.accounts.filter((a) => ACCOUNT_PENDING.includes(a.state));
  return h`
  <header class="page-head"><div>
    <h1>${headline()}</h1>
    <p class="key"><span class="key-item"><span class="solid" aria-hidden="true"></span>Sólido: ${connected() ? `lido agora nesta máquina e ${where().em}` : 'lido agora nesta máquina'}</span>${!realView() && h`<span class="key-item"><span class="hatch" aria-hidden="true"></span>Hachurado: exemplo. Não é dado de ninguém</span>`}</p>
  </div></header>
  ${connBar()}
  ${nextSteps()}
  <div class="stats">
    ${stat({ label: 'Aplicações', value: apps.length, note: originNote(apps), to: '#/aplicacoes', ic: 'boxes', ex: allEx(apps), appState: 'all' })}
    ${stat({ label: 'Com problema', value: problem.length, note: originNote(problem), to: '#/aplicacoes', ic: 'circle-alert', kind: problem.length ? 'err' : 'ok', ex: allEx(problem), appState: 'problem' })}
    ${stat({ label: 'Produção atrás', value: behind.length, note: originNote(behind), to: '#/aplicacoes', ic: 'git-compare', kind: behind.length ? 'warn' : 'ok', ex: allEx(behind), appState: 'behind' })}
    ${stat({ label: 'Contas a resolver', value: accounts.length, note: originNote(accounts), to: '#/contas', ic: 'key-round', kind: accounts.length ? 'warn' : 'ok', ex: allEx(accounts) })}
    ${stat({ label: 'Falta nesta máquina', value: S.device ? pending.length : '–', note: S.device ? 'Lido agora' : 'Lendo', to: '#/configurar', ic: 'laptop', kind: !S.device ? '' : pending.length ? 'warn' : 'ok' })}
  </div>
  <div class="two">
    <section class="section" aria-labelledby="att-title">
      <div class="sec-head"><h2 id="att-title">Precisa de atenção</h2>${areaNote('apps')}</div>
      <ul class="rows is-ex-list">
        ${list.slice(0, 6).map((a) => h`<li><a class="row-link" href="${a.to}">${mark(a.kind, a.label, a.ex)}<span class="row-main"><b>${a.title}</b><span class="muted">${a.sub}</span><span class="next">${a.next}</span></span></a></li>`)}
        ${list.length > 6 && h`<li class="row-more">${list.length === 7 ? 'Mais 1 item' : `Mais ${list.length - 6} itens`} nas telas de contas e clientes.</li>`}
        ${!list.length && h`<li class="row-empty">Nada pendente.</li>`}
      </ul>
    </section>
    <section class="section" aria-labelledby="dev-title">
      <div class="sec-head"><h2 id="dev-title">O que falta nesta máquina</h2><p class="muted">Lido agora. O painel funciona mesmo sem estes itens.</p></div>
      <ul class="rows">
        ${pending.slice(0, 5).map((c) => { const [k, l] = SOLID[c.viewState]; return h`<li><a class="row-link" href="#/configurar/maquina#${c.track}">${mark(k, l)}<span class="row-main"><b>${c.name}</b><span class="muted">${c.detail}</span></span></a></li>`; })}
        ${!S.device && h`<li class="row-empty" role="status">Lendo esta máquina.</li>`}
        ${S.device && !pending.length && h`<li class="row-empty">Tudo o que é obrigatório aqui está pronto. Os itens opcionais estão em Configurar.</li>`}
      </ul>
      <a class="btn" href="#/configurar">Configurar esta máquina</a>
    </section>
  </div>
  ${board()}`;
}

// ---------- Clientes ----------
const CLIENT_TABS = [['visao', 'Visão geral'], ['implantacao', 'Implantação'], ['contas', 'Contas'], ['aplicacoes', 'Aplicações'], ['destinos', 'Destinos']];

function viewClientesLista() {
  return h`
  ${pageHead('Clientes', 'Cada cliente tem contas e tokens próprios. Abra um para ver o que falta para ele estar completo.', h`<a class="btn btn-pri" href="#/novo-cliente">${icon('plus')}Novo cliente</a>`)}
  ${areaNote('apps')}
  <div class="cards">${S.data.clients.map((c) => {
    const { done, total } = rolloutCount(c.id);
    const ex = !(S.data.rollout[c.id] || []).some((p) => !rowEx(p));
    const apps = S.data.apps.filter((a) => a.client === c.id);
    const accounts = accountsOf(c.id);
    const late = accounts.filter((a) => ACCOUNT_PENDING.includes(a.state)).length;
    const bad = apps.filter((a) => APP_FILTER_STATE(a, 'problem')).length;
    return h`<a class="client-card${ex ? ' is-ex' : ''}" href="#/clientes/${c.id}">
      <h2>${icon('building-2')}${c.name}</h2>
      <p class="muted">${c.hosting}</p>
      ${progressBar(done, total, `Implantação de ${c.name}`)}
      <p class="client-facts"><span>${apps.length === 1 ? '1 aplicação' : `${apps.length} aplicações`}</span><span>${accounts.length === 1 ? '1 conta' : `${accounts.length} contas`}</span></p>
      <p class="btns">${bad > 0 && mark('err', bad === 1 ? '1 com problema' : `${bad} com problema`, ex)}${late > 0 && mark('warn', late === 1 ? '1 conta a resolver' : `${late} contas a resolver`, ex)}${!bad && !late && mark('ok', 'Nada pendente', ex)}</p>
    </a>`;
  })}</div>`;
}

function rolloutActions(c, p) {
  return h`${p.cmd && copyBlock(p.cmd)}
    <span class="btns">${p.to && h`<a class="btn btn-small" href="${p.to}">${p.toLabel}</a>`}
    ${p.real && canAct() && realBtn(p.real.button, p.real)}
    ${p.action === 'prod' && h`<button class="btn btn-small" data-act="ask" data-verb="Levar para prod os projetos de" data-name="${c.id}" data-env="prod" data-client="${c.id}" data-kind="prod">Levar para prod</button>`}</span>`;
}

function nextStepCard(c, p, link) {
  return h`<article class="panel next-step" aria-label="Próximo passo">
    <div class="panel-head"><p class="next-step-tag">Próximo passo</p>${mark(READY[p.state][0], READY[p.state][1], rowEx(p))}</div>
    <h3>${p.title}</h3>
    <div class="step-body">${p.hint && h`<p>${p.hint}</p>`}${link ? h`<a class="btn btn-small" href="#/clientes/${c.id}/implantacao">Ver a implantação</a>` : rolloutActions(c, p)}</div>
  </article>`;
}
const nextStepOf = (rollout) => rollout.find((p) => p.state === 'err') || rollout.find((p) => p.state === 'todo');

function tabImplantacao(c) {
  const rollout = S.data.rollout[c.id] || [];
  const { done, total } = rolloutCount(c.id);
  const next = nextStepOf(rollout);
  const later = rollout.filter((p) => p !== next && (p.state === 'todo' || p.state === 'err'));
  const finished = rollout.filter((p) => p.state === 'ok');
  const unused = rollout.filter((p) => p.state === 'na');
  const realClient = rollout.some((p) => !rowEx(p));
  const row = (p) => { const [k, l] = READY[p.state]; return h`<li>${mark(k, l, rowEx(p))}<span class="row-main"><b>${p.title}</b>${p.hint && (p.state !== 'ok' || !rowEx(p)) && h`<span class="${p.state === 'ok' ? 'muted' : 'next'}">${p.hint}</span>`}${(p.state === 'todo' || p.state === 'err') && (p.cmd || p.to || p.real || p.action) && h`<details class="fold"><summary>Como fazer</summary><div class="step-body">${rolloutActions(c, p)}</div></details>`}</span></li>`; };
  return h`
  <div class="panel">
    <div class="panel-head"><h2>Implantação</h2>${realClient && canAct() && c.id !== homeId() && realBtn('Terminar a preparação', { action: 'client_prepare', label: `Terminar a preparação de ${c.name}`, client: c.id })}</div>
    ${progressBar(done, total, `Implantação de ${c.name}`)}
  </div>
  ${next ? nextStepCard(c, next) : h`<div class="info"><b>Implantação concluída.</b> Nenhuma etapa pendente.</div>`}
  ${later.length > 0 && h`<section class="section" aria-labelledby="ro-later"><div class="sec-head"><h2 id="ro-later">Depois disso</h2></div><ol class="checklist">${later.map(row)}</ol></section>`}
  ${finished.length > 0 && h`<details class="fold"><summary>${finished.length === 1 ? '1 etapa feita' : `${finished.length} etapas feitas`}</summary><ol class="checklist">${finished.map(row)}</ol></details>`}
  ${unused.length > 0 && h`<p class="muted">Este cliente não usa: ${unused.map((p) => p.title).join(', ')}.</p>`}`;
}

function tabVisao(c) {
  const rollout = S.data.rollout[c.id] || [];
  const { done, total } = rolloutCount(c.id);
  const next = nextStepOf(rollout);
  const apps = S.data.apps.filter((a) => a.client === c.id);
  const accounts = accountsOf(c.id);
  const late = accounts.filter((a) => ACCOUNT_PENDING.includes(a.state));
  const diverge = S.data.diverge.filter((d) => d.client === c.id);
  const items = attention().filter((a) => a.client === c.id);
  const rolloutEx = !rollout.some((p) => !rowEx(p));
  return h`
  <div class="stats">
    ${stat({ label: 'Implantação', value: `${done}/${total}`, note: rolloutEx ? 'Exemplo' : 'Lido agora', to: `#/clientes/${c.id}/implantacao`, ic: 'list-checks', ex: rolloutEx })}
    ${stat({ label: 'Aplicações', value: apps.length, note: originNote(apps), to: `#/clientes/${c.id}/aplicacoes`, ic: 'boxes', ex: allEx(apps) })}
    ${stat({ label: 'Contas a resolver', value: late.length, note: `De ${accounts.length}. ${originNote(accounts)}`, to: `#/clientes/${c.id}/contas`, ic: 'key-round', kind: late.length ? 'warn' : 'ok', ex: allEx(accounts) })}
    ${stat({ label: 'Divergências', value: diverge.length, note: originNote(diverge), to: `#/clientes/${c.id}/destinos`, ic: 'git-compare', kind: diverge.length ? 'warn' : 'ok', ex: allEx(diverge) })}
  </div>
  <div class="two">
    <div class="section">${next ? nextStepCard(c, next, true) : h`<div class="info"><b>Implantação concluída.</b> Nenhuma etapa pendente.</div>`}</div>
    <section class="section" aria-labelledby="cl-att"><div class="sec-head"><h2 id="cl-att">Precisa de atenção</h2></div>
      <ul class="rows">${items.slice(0, 5).map((a) => h`<li><a class="row-link" href="${a.to}">${mark(a.kind, a.label, a.ex)}<span class="row-main"><b>${a.title}</b><span class="next">${a.next}</span></span></a></li>`)}${!items.length && h`<li class="row-empty">Nada pendente neste cliente.</li>`}</ul>
    </section>
  </div>
  ${c.id !== homeId() && (!realView() || connected()) && h`<div class="danger-zone"><p class="muted">Fim de contrato: exporta os segredos e tira o seu acesso.</p><button class="btn btn-danger" data-act="offboard" data-client="${c.id}">Encerrar este cliente</button></div>`}`;
}

function tabContasCliente(c) {
  const accounts = accountsOf(c.id);
  return accounts.length
    ? h`<ul class="rows">${accounts.map((a) => { const [k, l] = ACCOUNT_STATE[a.state]; return h`<li><a class="row-link" href="#/contas/${a.id}">${mark(k, l, rowEx(a))}<span class="row-main"><b>${PROVIDERS[a.provider].name}</b><span class="muted">${a.label}. ${a.expires}.</span></span></a></li>`; })}</ul>`
    : empty('key-round', 'Nenhuma conta conectada', 'Conecte a primeira conta. O painel mostra o passo a passo de cada plataforma.', h`<button class="btn btn-pri" data-act="newacc" data-client="${c.id}">Conectar conta</button>`);
}

function tabDestinos(c) {
  const realClient = (S.data.rollout[c.id] || []).some((p) => !rowEx(p));
  const found = S.data.discoveries?.[c.id] || [];
  const diverge = S.data.diverge.filter((d) => d.client === c.id);
  const checked = canAct() && (S.data.connection.plans || []).includes(c.id) && !diverge.some((d) => !rowEx(d));
  return h`
  <p class="lede">Compara o que está no cofre com o que está em cada destino. Só os nomes das chaves aparecem aqui.</p>
  ${canAct() && realClient && h`<div class="btns">${realBtn('Conferir diferenças', { action: 'sync_plan', label: `Conferir diferenças de ${c.name}`, client: c.id })}${realBtn('Buscar projetos', { action: 'discover', label: `Buscar projetos nas contas de ${c.name}`, client: c.id })}</div>`}
  ${!canAct() && realClient && h`<p class="muted">Para conferir pelo painel: ${actionHint()}</p>`}
  ${checked && mark('ok', 'Nenhuma divergência na última conferência')}
  ${diverge.length > 0 ? h`<section class="section" aria-labelledby="dv-title"><div class="sec-head"><h2 id="dv-title">Destinos divergentes</h2></div>
    <div class="tools">${diverge.map((d) => h`<div class="panel"><p><b>${d.target}</b></p><p class="muted">Chaves, só os nomes: ${d.keys.join(', ')}. Decida qual valor vence.</p>
      <div class="btns">${!rowEx(d) && canAct() ? realBtn('Levar o valor do cofre', { action: 'sync_apply', label: `Levar o valor do cofre para ${d.targetId}`, client: d.client, target: d.targetId, env: d.env, confirm: d.env === 'prod' ? d.targetId : '' }, 'btn') : h`<button class="btn" data-act="ask" data-verb="Levar o valor do cofre para" data-name="${d.target}" data-env="prod" data-diverge="${d.id}">Levar o valor do cofre</button>`}<a class="btn btn-ghost" href="#/ferramentas">O do destino é o certo: gravar no cofre</a></div></div>`)}</div></section>`
    : !checked && empty('git-compare', 'Nenhuma divergência conhecida', realClient ? 'Esta lista só muda depois de uma conferência.' : 'Neste exemplo, cofre e destinos estão iguais.')}
  ${found.length > 0 && h`<section class="section" aria-labelledby="dv-found"><div class="sec-head"><h2 id="dv-found">O que as contas enxergam</h2></div><ul class="rows">${found.map((f) => h`<li class="row-plain"><span class="row-main"><b>${f.name}</b><span class="muted">${f.provider}. <code>${f.id}</code></span></span></li>`)}</ul></section>`}`;
}

function viewClientes(id, sub) {
  if (!id) return viewClientesLista();
  const c = S.data.clients.find((x) => x.id === id);
  if (!c) return empty('building-2', 'Cliente não encontrado', 'Ele pode ter sido encerrado.', h`<a class="btn" href="#/clientes">Ver os clientes</a>`);
  const cur = CLIENT_TABS.some(([t]) => t === sub) ? sub : 'visao';
  const rollout = S.data.rollout[c.id] || [];
  const realClient = rollout.some((p) => !rowEx(p));
  const apps = S.data.apps.filter((a) => a.client === c.id);
  const late = accountsOf(c.id).filter((a) => ACCOUNT_PENDING.includes(a.state)).length;
  const diverge = S.data.diverge.filter((d) => d.client === c.id).length;
  const tabs = CLIENT_TABS.map(([t, name]) => [t, name, `#/clientes/${c.id}/${t}`, t === 'contas' ? late : t === 'destinos' ? diverge : 0]);
  return h`
  ${pageHead(c.name, `Onde roda: ${c.hosting}.`, cur === 'contas' && h`<button class="btn btn-pri" data-act="newacc" data-client="${c.id}">Conectar conta</button>`)}
  ${connBar()}
  ${realClient ? h`<p class="muted">Implantação lida agora ${where().de}. Exemplos continuam hachurados.</p>` : exNote('A implantação deste cliente é exemplo.')}
  ${tabsNav('Seções do cliente', tabs, cur)}
  ${cur === 'visao' ? tabVisao(c) : cur === 'implantacao' ? tabImplantacao(c) : cur === 'contas' ? tabContasCliente(c) : cur === 'destinos' ? tabDestinos(c) : appList(apps)}`;
}

// ---------- Aplicações ----------
function appList(apps) {
  if (!apps.length) return empty('boxes', 'Nenhuma aplicação aqui', 'Mude os filtros ou declare um projeto no cliente.');
  return h`<ul class="rows">${apps.map((a) => {
    const prod = a.envs.prod || Object.values(a.envs)[0];
    const [k, l] = ENV_STATE[prod.state];
    return h`<li><a class="row-link" href="#/aplicacoes/${a.id}">${mark(k, l, rowEx(a))}<span class="row-main"><b>${a.name}</b><span class="muted">${clientName(a.client)}. ${typeName(a.type)}.</span></span><span class="row-side"><b>${prod.version}</b><span class="muted">${prod.when}</span></span></a></li>`;
  })}</ul>`;
}

const APP_FILTER_STATE = (a, st) => {
  const envs = Object.values(a.envs);
  if (st === 'problem') return envs.some((e) => e.state === 'degraded' || (e.state === 'unread' && a.source !== 'config') || e.backupFailed);
  if (st === 'behind') return isBehind(a);
  return true;
};

function platformLink(a, env) {
  if (a.type === 'front-vercel') return { url: 'https://vercel.com/dashboard', label: 'Abrir na Vercel' };
  if (a.type === 'api-railway') return { url: 'https://railway.com/dashboard', label: 'Abrir na Railway' };
  return { url: null, label: 'Log bruto no Coolify', env };
}

function envPanel(a, name, e) {
  const ex = rowEx(a);
  const [k, l] = ENV_STATE[e.state];
  const pl = platformLink(a, name);
  const coolify = a.type.endsWith('coolify');
  return h`<article class="panel env">
    <header class="env-head"><h2>${name === 'prod' ? 'Em produção' : name}</h2>${mark(k, l, ex)}</header>
    <p class="env-version">${e.version}</p>
    <dl class="facts">
      ${e.commit && h`<div><dt>Commit</dt><dd><code>${e.commit}</code></dd></div>`}
      <div><dt>${e.whenLabel || 'Último deploy'}</dt><dd>${e.when}</dd></div>
      <div><dt>Onde roda</dt><dd>${e.where}</dd></div>
      ${e.health && h`<div><dt>Health check</dt><dd>${e.health}</dd></div>`}
      ${e.backup && h`<div><dt>Backup</dt><dd>${e.backup}</dd></div>`}
      ${e.secrets && h`<div><dt>Segredos</dt><dd>${e.secrets}</dd></div>`}
    </dl>
    ${e.moving && h`<p class="muted">A tag de <code>${e.version}</code> é móvel: o nome não diz qual versão está rodando. Publique com <code><versão>-<sha></code> e leve com <code>cp-coolify service release</code>.</p>`}
    ${e.next && h`<p class="next">${e.next}</p>`}
    <div class="btns">
      ${ex && coolify && h`<button class="btn btn-small" data-act="ask" data-verb="Reiniciar" data-name="${a.name}" data-env="${name}">Reiniciar</button>`}
      ${ex && coolify && a.type !== 'db-coolify' && h`<button class="btn btn-small" data-act="ask" data-verb="Fazer deploy de" data-name="${a.name}" data-env="${name}">Fazer deploy</button>`}
      ${!ex && canAct() && e.state !== 'unread' && a.type.endsWith('coolify') && realBtn('Reiniciar', { action: 'restart', label: `Reiniciar ${a.name} em ${name}`, client: a.client, app: a.id, env: name, confirm: name === 'prod' ? a.name : '' })}
      ${!ex && canAct() && name === 'prod' && previousEnv(a)?.tag && previousEnv(a).tag !== e.tag && realBtn(`Promover ${previousEnv(a).tag}`, { action: 'promote', label: `Promover ${a.name} para ${previousEnv(a).tag} em prod`, client: a.client, app: a.id, env: 'prod', confirm: a.name })}
      ${!ex && canAct() && e.state !== 'unread' && a.type === 'api-coolify' && realBtn('Fazer deploy', { action: 'deploy', label: `Fazer deploy de ${a.name} em ${name}`, client: a.client, app: a.id, env: name, confirm: name === 'prod' ? a.name : '' })}
      ${!ex && canAct() && a.type === 'db-coolify' && realBtn('Fazer backup', { action: 'backup', label: `Fazer backup de ${a.name} em ${name}`, client: a.client, app: a.id, env: name })}
      ${!ex && canAct() && e.target && realBtn('Levar os segredos', { action: 'sync_apply', label: `Levar os segredos para ${e.target}`, client: a.client, target: e.target, confirm: name === 'prod' ? e.target : '', env: name })}
      ${ex && e.backupFailed && h`<button class="btn btn-small" data-act="ask" data-verb="Fazer backup de" data-name="${a.name}" data-env="${name}" data-backup="${a.id}">Fazer backup</button>`}
      ${pl.url ? h`<a class="btn btn-small btn-ghost" href="${pl.url}" target="_blank" rel="noopener">${icon('external-link')}${pl.label}</a>` : h`<a class="btn btn-small btn-ghost" href="#/ferramentas">${pl.label}</a>`}
    </div>
    ${!ex && !canAct() && e.state !== 'unread' && h`<p class="muted">Para agir pelo painel: ${actionHint()}</p>`}
  </article>`;
}

function viewAplicacao(app, envName) {
  const order = ['prod', 'staging', 'dev'].filter((n) => app.envs[n]);
  const cur = order.includes(envName) ? envName : order[0];
  const recent = S.data.logs.filter((l) => l.client === app.client && l.env === cur && l.app === app.name).slice(0, 5);
  return h`
  ${pageHead(app.name, h`<a href="#/clientes/${app.client}">${clientName(app.client)}</a>. ${typeName(app.type)}: ${APP_TYPES[app.type]?.when}`)}
  ${connBar()}
  ${rowEx(app) ? exNote() : h`<p class="muted">Lido agora ${where().de}.${canAct() ? ' Os botões abaixo executam de verdade.' : ''}</p>`}
  <nav class="env-strip" aria-label="Ambientes">${order.map((n) => { const e = app.envs[n]; const [k, l] = ENV_STATE[e.state]; return h`<a class="env-pick${n === cur ? ' is-on' : ''}" href="#/aplicacoes/${app.id}/${n}"${n === cur ? h` aria-current="page"` : ''}><span class="env-pick-name">${n === 'prod' ? 'Em produção' : n}<span class="sig sig-${k}${rowEx(app) ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span></span><span class="env-pick-version">${e.version}</span><span class="muted">${e.when}</span></a>`; })}</nav>
  ${envPanel(app, cur, app.envs[cur])}
  ${!app.type.endsWith('coolify') && h`<p class="muted">Esta plataforma cuida do próprio container. O painel mostra versão e estado e leva até lá.</p>`}
  <section class="section" aria-labelledby="app-logs"><div class="sec-head"><div class="panel-head"><h2 id="app-logs">Logs recentes em ${cur}</h2><a class="btn btn-small" href="#/logs" data-act="seelogs" data-client="${app.client}" data-env="${cur}" data-q="${app.name}">Ver todos os logs</a></div></div>
    ${recent.length ? h`<ul class="rows logs">${recent.map(logRow)}</ul>` : empty('scroll-text', 'Nenhum log recente aqui', 'Os registros aparecem quando esta aplicação envia logs para este ambiente.')}</section>`;
}

function viewAplicacoes(id, sub) {
  if (id) {
    const app = S.data.apps.find((a) => a.id === id);
    return app ? viewAplicacao(app, sub) : empty('boxes', 'Aplicação não encontrada', 'Ela pode ter saído do inventário.', h`<a class="btn" href="#/aplicacoes">Ver as aplicações</a>`);
  }
  const f = S.fApps;
  const q = f.q.trim().toLowerCase();
  const apps = S.data.apps.filter((a) => (!f.client || a.client === f.client) && (!f.type || a.type === f.type) && APP_FILTER_STATE(a, f.state) && (!q || a.name.includes(q)));
  const containers = S.device?.containers || [];
  return h`
  ${pageHead('Aplicações', 'Versão, estado e deploy de cada aplicação, por cliente e por tipo.')}
  <section class="section" aria-labelledby="al-title"><div class="sec-head"><h2 id="al-title" class="sr">Todas as aplicações</h2>${areaNote('apps')}</div>
  <div class="filters sec-filters">
    ${select('f-client', 'Cliente', 'fApps.client', f.client, [['', 'Todos'], ...S.data.clients.map((c) => [c.id, c.name])])}
    ${select('f-type', 'Tipo', 'fApps.type', f.type, [['', 'Todos'], ...Object.entries(APP_TYPES).map(([k, v]) => [k, v.name])])}
    ${select('f-state', 'Situação', 'fApps.state', f.state, [['', 'Todas'], ['problem', 'Com problema'], ['behind', 'Produção atrás do ambiente anterior']])}
    <label class="fld fld-grow" for="f-q">Buscar<input id="f-q" type="search" data-bind="fApps.q" value="${f.q}" placeholder="Nome da aplicação"></label>
  </div>
  <p class="muted" role="status">${apps.length === 1 ? '1 aplicação' : `${apps.length} aplicações`}</p>
  ${appList(apps)}</section>
  ${containers.length > 0 && h`<section class="section" aria-labelledby="ct-title"><div class="sec-head"><h2 id="ct-title">Containers nesta máquina</h2><p class="muted">Lido agora do Docker: ${containers.length}.</p></div>
    <details class="fold"><summary>Ver os containers</summary><ul class="rows">${containers.map((c) => h`<li class="row-plain">${mark(c.state === 'running' ? 'ok' : 'off', c.state === 'running' ? 'Rodando' : 'Parado')}<span class="row-main"><b>${c.names}</b><span class="muted">${c.status}</span></span></li>`)}</ul></details></section>`}`;
}

function select(id, label, bind, value, opts) {
  return h`<label class="fld" for="${id}">${label}<select id="${id}" data-bind="${bind}">${opts.map(([v, n]) => h`<option value="${v}"${v === value ? h` selected` : ''}>${n}</option>`)}</select></label>`;
}

// ---------- Logs ----------
const LOG_LEVEL = { info: 'off', warn: 'warn', error: 'err' };
const LOG_PAGE = 25;
const logRow = (l) => h`<li><button class="row-link" data-act="openlog" data-id="${l.id}" aria-expanded="${S.openLog === l.id}">
  ${mark(LOG_LEVEL[l.level], l.level, rowEx(l))}<span class="row-main"><b><code>${l.event}</code> ${l.route}</b><span class="muted">${clientName(l.client)}, ${l.app}, ${l.env}</span></span><span class="row-side"><b>${l.status || 'Sem status'}</b><span class="muted">${l.time}</span></span></button>
  ${S.openLog === l.id && h`<div class="row-detail"><dl class="facts"><div><dt>Duração</dt><dd>${l.ms === '' ? 'Não informada' : `${l.ms} ms`}</dd></div>${l.rid && h`<div><dt>Request</dt><dd><code>${l.rid}</code></dd></div>`}<div><dt>Marcação de segurança</dt><dd>${l.flag || 'Nenhuma'}</dd></div></dl><p class="muted">A mensagem de erro não vem para cá, porque pode trazer valores. Para investigar, procure este horário e esta rota no log bruto do Coolify.</p></div>`}</li>`;

function viewLogs() {
  const f = S.fLogs;
  const q = f.q.trim().toLowerCase();
  const rows = S.data.logs.filter((l) => (!f.client || l.client === f.client) && (!f.env || l.env === f.env) && (!f.level || l.level === f.level) && (!q || `${l.app} ${l.event} ${l.route}`.toLowerCase().includes(q)));
  const pages = Math.max(1, Math.ceil(rows.length / LOG_PAGE));
  const page = Math.min(S.logPage, pages - 1);
  const shown = rows.slice(page * LOG_PAGE, (page + 1) * LOG_PAGE);
  const first = rows.length ? page * LOG_PAGE + 1 : 0;
  return h`
  ${pageHead('Logs', 'Vêm já filtrados pela allowlist, sem mensagem de erro e sem dado sensível. Para o log bruto, o caminho é o Coolify.')}
  ${connBar()}
  ${areaNote('logs')}
  <div class="filters">
    ${select('l-client', 'Cliente', 'fLogs.client', f.client, [['', 'Todos'], ...S.data.clients.map((c) => [c.id, c.name])])}
    ${select('l-env', 'Ambiente', 'fLogs.env', f.env, [['', 'Todos'], ['dev', 'dev'], ['staging', 'staging'], ['prod', 'prod']])}
    ${select('l-level', 'Nível', 'fLogs.level', f.level, [['', 'Todos'], ['info', 'info'], ['warn', 'warn'], ['error', 'error']])}
    <label class="fld fld-grow" for="l-q">Buscar<input id="l-q" type="search" data-bind="fLogs.q" value="${f.q}" placeholder="Aplicação, evento ou rota"></label>
    <button class="btn" data-act="clearlogs">Limpar filtros</button>
  </div>
  ${rows.length ? h`<div class="section"><ul class="rows logs">${shown.map(logRow)}</ul></div>
  <div class="pager"><p class="muted" role="status">${first} a ${first + shown.length - 1} de ${rows.length === 1 ? '1 registro' : `${rows.length} registros`}</p>
    ${pages > 1 && h`<div class="btns"><button class="btn btn-small" data-act="logpage" data-p="${page - 1}"${page === 0 ? h` disabled` : ''}>Anterior</button><span class="muted">Página ${page + 1} de ${pages}</span><button class="btn btn-small" data-act="logpage" data-p="${page + 1}"${page >= pages - 1 ? h` disabled` : ''}>Próxima</button></div>`}</div>`
    : empty('scroll-text', 'Nenhum log com esses filtros', '', h`<button class="btn" data-act="clearlogs">Limpar filtros</button>`)}`;
}

// ---------- Atividade ----------
function viewAtividade() {
  const res = { ok: ['ok', 'Sucesso'], err: ['err', 'Falhou'], sim: ['off', 'Simulado'], running: ['warn', 'Em andamento'] };
  return h`
  ${pageHead('Atividade', 'O que foi feito pelo painel e o resultado de cada etapa. Quem leu qual segredo fica no audit do cofre.')}
  ${actionsOn() ? exNote('Linhas sólidas são ações reais no laboratório. As hachuradas são exemplos e simulações.') : exNote('Exemplo. As ações que você simular neste painel entram aqui.')}
  ${S.data.activity.length ? h`<ul class="rows">
    ${S.data.activity.map((a) => h`<li><button class="row-link" data-act="openact" data-id="${a.id}" aria-expanded="${S.openAct === a.id}">${mark(res[a.result][0], res[a.result][1], rowEx(a))}<span class="row-main"><b>${a.action}</b><span class="muted">${a.who}, ${a.where}</span></span><span class="row-side muted">${a.time || hhmm(a.at)}</span></button>
      ${S.openAct === a.id && h`<div class="row-detail">${a.steps.length ? h`<ol class="steps">${a.steps.map((s) => h`<li>${s}</li>`)}</ol>` : h`<p class="muted">Aguardando a primeira saída.</p>`}</div>`}</li>`)}
  </ul>` : empty('history', 'Nada foi feito ainda', 'As ações feitas pelo painel entram aqui, com o resultado de cada etapa.')}
  ${!realView() && h`<div><button class="link-btn" data-act="resetdemo">Voltar os exemplos ao início</button></div>`}`;
}

// ---------- Contas: por conta de cada cliente, não por tabela de tokens ----------
function accountDetail(a) {
  const p = PROVIDERS[a.provider];
  const ex = rowEx(a);
  const [k, l] = ACCOUNT_STATE[a.state];
  const tool = p.toolCheck && (S.device?.checks || []).find((c) => c.id === p.toolCheck);
  const url = p.url || (tool?.state === 'ok' ? 'http://127.0.0.1:8000' : null);
  const hasToken = a.provider !== 'droplet';
  const filled = a.fields.filter((f) => f.set).length;
  return h`
  <article class="account" aria-labelledby="acc-title">
    <header class="account-head">
      <div><p class="account-owner">${clientName(a.client)}</p><h2 id="acc-title">${p.name}</h2><p class="muted">${a.label}</p></div>
      ${mark(k, l, ex)}
    </header>
    <p>${p.role}</p>
    <dl class="facts facts-wide">
      <div><dt>Validade</dt><dd>${a.expires}</dd></div>
      <div><dt>Último teste</dt><dd>${a.tested}</dd></div>
      <div><dt>Atende</dt><dd>${a.serves.length ? a.serves.join(', ') : 'Nenhuma aplicação ainda'}</dd></div>
    </dl>
    ${hasToken && h`<section class="account-sec"><h3>O que fica no cofre</h3>
      <p class="muted">Em <code>kv/${a.client}/_providers/${a.name}</code>. ${a.fieldsRead === false ? 'O painel não abre esta credencial.' : 'O painel mostra só se o campo existe, nunca o valor.'}</p>
      ${a.fieldsRead === false
        ? h`<ul class="fields">${Object.keys(p.fields).map((f) => h`<li><span><code>${f}</code><span class="muted"> ${p.fields[f]}</span></span></li>`)}</ul>
           <p class="muted">Campos esperados nesta plataforma. O painel lê só a validade. Para conferir os campos, use o comando em "Como conferir".</p>`
        : h`<ul class="fields">${a.fields.map((f) => h`<li>${mark(f.set ? 'ok' : 'warn', f.set ? 'Gravado' : 'Falta', ex)}<span><code>${f.name}</code><span class="muted"> ${p.fields[f.name] || ''}</span></span></li>`)}</ul>
           <p class="muted">${filled} de ${a.fields.length} campos gravados.</p>`}</section>`}
    <section class="account-sec"><h3>${hasToken ? 'Como conectar ou renovar' : 'Como conectar este servidor'}</h3>
      <ol class="steps">${p.create.map((s) => h`<li>${s}</li>`)}${hasToken && !p.piped && h`<li>Rode o comando abaixo no terminal. O valor é pedido em prompt oculto e vai direto para o cofre.</li>`}</ol>
      ${url ? h`<a class="btn" href="${url}" target="_blank" rel="noopener">${icon('external-link')}${p.urlLabel}</a>` : p.toolCheck && h`<p class="muted">O Coolify ainda não está no ar nesta máquina. <a href="#/configurar/maquina#containers">Veja como subir</a>.</p>`}
      ${copyBlock(p.command(a.client, a.name))}</section>
    ${hasToken && h`<section class="account-sec"><h3>Como conferir</h3>
      ${copyBlock(`scripts/cp-secrets provider list ${a.client}\nscripts/cp-secrets sync plan ${a.client}`)}</section>`}
    <section class="account-sec"><h3>Encerrar o acesso</h3><p class="muted">${p.revokeHelp}</p>
      <div class="btns">
        ${ex && hasToken && h`<button class="btn" data-act="testacc" data-id="${a.id}">Testar a conexão</button>`}
        ${ex && hasToken && a.state !== 'missing' && h`<button class="btn btn-danger" data-act="revokeacc" data-id="${a.id}">Revogar</button>`}
      </div>
      ${!ex && canAct() && hasToken && a.state !== 'missing' && h`<div class="btns">${realBtn('Testar a conexão', { action: 'test_account', label: `Testar a conta ${a.name}`, client: a.client, provider: a.name })}</div>`}
      ${!ex && h`<p class="muted">Revogar não é feito pelo painel: é irreversível e cada plataforma tem o próprio caminho. Use o que está descrito acima.${canAct() ? '' : ` Para testar a conexão daqui: ${actionHint()}`}</p>`}
    </section>
  </article>`;
}

function viewContas(id) {
  const selected = S.data.accounts.find((a) => a.id === id) || S.data.accounts.find((a) => ACCOUNT_PENDING.includes(a.state)) || S.data.accounts[0];
  return h`
  ${pageHead('Contas', 'Cada plataforma de cada cliente é uma conta separada, com login e token próprios. Escolha uma para ver o que ela atende e o que falta.', h`<button class="btn btn-pri" data-act="newacc">${icon('plus')}Conectar conta</button>`)}
  ${connBar()}
  ${areaNote('accounts')}
  <div class="master${id ? ' has-detail' : ''}">
    <nav class="master-list" aria-label="Contas por cliente">
      ${S.data.clients.map((c) => h`<div class="master-group"><h2>${c.name}</h2>
        ${accountsOf(c.id).map((a) => { const [k, l] = ACCOUNT_STATE[a.state]; return h`<a class="master-item${a.id === selected?.id ? ' is-on' : ''}" href="#/contas/${a.id}"${a.id === selected?.id ? h` aria-current="true"` : ''}><span class="sig sig-${k}${rowEx(a) ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span><span class="master-text"><b>${PROVIDERS[a.provider].name}</b><span class="muted">${a.expires}</span></span></a>`; })}
        ${!accountsOf(c.id).length && h`<p class="muted">Nenhuma conta ainda.</p>`}</div>`)}
    </nav>
    <div class="section">${id && h`<a class="master-back" href="#/contas">${icon('arrow-left')}Todas as contas</a>`}${selected && accountDetail(selected)}</div>
  </div>`;
}

// ---------- Configurar ----------
function checkRow(c) {
  const [k, l] = SOLID[c.viewState];
  const needs = c.viewState !== 'ok';
  const hasHelp = needs && (c.steps?.length || c.cmd);
  return h`<li class="check">
    <div class="check-line">${mark(k, l)}<span class="row-main"><b>${c.name}</b><span class="muted">${c.detail}</span></span>${c.url && c.state !== 'missing' && !c.url.includes('/healthz') && !c.url.includes('/api/') && h`<a class="inline-link" href="${c.url}" target="_blank" rel="noopener">Abrir</a>`}</div>
    ${hasHelp && h`<details class="fold"${c.viewState === 'warn' || c.viewState === 'missing' ? h` open` : ''}><summary>Como configurar</summary>
      <ol class="steps">${c.steps.map((s) => h`<li>${s}</li>`)}</ol>
      ${c.cmd && copyBlock(c.cmd)}
      <p class="btns">${c.guide && h`<a class="inline-link" href="#/guias/${c.guide}">Abrir o guia completo</a>`}${c.doc && !installed() && h`<span class="muted">Mais em <code>${c.doc}</code>.</span>`}</p></details>`}
  </li>`;
}

function tabMaquina() {
  const d = S.device;
  if (!d) return h`<p class="muted" role="status">Lendo esta máquina.</p>`;
  const rows = visibleChecks().map(checkView);
  const desired = d.desired;
  return h`
  <p class="lede">O painel funciona mesmo que falte tudo abaixo. Esta lista mostra o que este device tem e o que fazer se ele for operar também.</p>
  ${targetPicker()}
  ${connSection()}
  ${TRACKS.map((t) => { const list = rows.filter((c) => c.track === t.id); return list.length > 0 && h`
    <section id="${t.id}" class="track" aria-labelledby="t-${t.id}"><div class="sec-head"><h2 id="t-${t.id}">${t.name}</h2><p class="muted">${t.why}</p></div><ul class="checks">${list.map(checkRow)}</ul></section>`; })}
  ${desired && !desired.error && h`<section class="track" aria-labelledby="t-desired"><div class="sec-head"><h2 id="t-desired">Declarado no repositório</h2><p class="muted">Lido agora de <code>openbao/secrets.toml</code>. São só nomes.${d.draft_todos ? ` O rascunho completo ainda tem ${d.draft_todos} IDs a preencher.` : ''}</p></div>
    <ul class="rows">${desired.clients.map((c) => h`<li class="row-plain">${mark('ok', 'Declarado')}<span class="row-main"><b>${c.slug}</b><span class="muted">${c.providers.length} contas e ${c.projects.length} projetos: ${c.projects.map((p) => p.slug).join(', ')}</span></span></li>`)}</ul></section>`}`;
}

function tabTipos() {
  return h`
  <p class="lede">O que cada tipo de aplicação precisa, camada por camada. Os números mostram quantas aplicações ainda têm alguma pendência. Hachurado inclui exemplos.</p>
  <div class="types">${Object.entries(APP_TYPES).map(([id, t]) => {
    const apps = S.data.apps.filter((a) => a.type === id);
    const pending = apps.filter((a) => Object.values(a.ready).some((r) => r === 'todo' || r === 'err'));
    const ex = apps.some(rowEx);
    return h`<article class="type-card" id="tipo-${id}">
      <header><h2>${t.name}</h2><p class="muted">${t.when}</p>${mark(pending.length ? 'warn' : 'ok', pending.length ? `${pending.length} de ${apps.length} com pendência` : `${apps.length} sem pendência`, ex)}</header>
      ${t.layers.map((l) => h`<section class="layer"><h3>${l.track}</h3><ul class="plain">${l.items.map((i) => h`<li>${i}</li>`)}</ul>
        ${l.cmd && h`<details class="fold"><summary>Ver o comando</summary>${copyBlock(l.cmd)}</details>`}
        <p class="btns">${l.to && h`<a class="inline-link" href="${l.to}">${l.toLabel}</a>`}${l.guide && h`<a class="inline-link" href="#/guias/${l.guide}">Abrir o guia</a>`}</p></section>`)}
    </article>`;
  })}</div>`;
}

function tabReal() {
  const values = Object.values(S.data.sources || {});
  const areas = values.filter((v) => v === 'demo').length;
  const mixed = values.filter((v) => v === 'mixed').length;
  return h`
  <p class="lede">Hoje, ${areas} áreas usam só dados de exemplo${mixed ? ` e ${mixed} misturam dado real e exemplo` : ''}. Cada linha ganha o dado real quando a fase dela chegar, sem mudar a tela. A hachura some sozinha.</p>
  <div class="scroll" tabindex="0" role="region" aria-label="Do exemplo ao real"><table class="plain-table"><thead><tr><th scope="col">Área</th><th scope="col">De onde virá o dado</th><th scope="col">Quando</th></tr></thead>
  <tbody>${REPLACE.map((r) => h`<tr><th scope="row">${r.area}</th><td>${r.source}</td><td>${r.phase}</td></tr>`)}</tbody></table></div>`;
}

const CONFIG_TABS = [['maquina', 'Esta máquina'], ['tipos', 'Por tipo de aplicação'], ['real', 'Do exemplo ao real']];
function viewConfigurar(tab) {
  const cur = CONFIG_TABS.some(([t]) => t === tab) ? tab : 'maquina';
  return h`
  ${pageHead('Configurar')}
  ${tabsNav('Seções de configuração', CONFIG_TABS.map(([t, n]) => [t, n, `#/configurar/${t}`, t === 'maquina' ? pendingChecks().length : 0]), cur)}
  ${cur === 'maquina' && machineSection()}
  ${cur === 'maquina' ? tabMaquina() : cur === 'tipos' ? tabTipos() : tabReal()}`;
}

// ---------- Guias ----------
function viewGuia(g) {
  const single = g.cmds || (g.cmd ? [['', g.cmd]] : []);
  return h`
  <div class="guide-page">
    ${pageHead(g.title, g.when)}
    <p class="guide-where">${icon('globe')}${g.where}</p>
    <ol class="timeline panel">${g.steps.map((s) => h`<li>${s}</li>`)}</ol>
    ${g.warn && h`<p class="caution"><b>Cuidado:</b> ${g.warn}</p>`}
    ${single.length > 0 && h`<section class="panel" aria-labelledby="g-cmd"><h2 id="g-cmd">${single.length === 1 ? 'Comando' : 'Comandos'}</h2>${single.map(([label, cmd]) => h`${label && h`<p class="cmd-label">${label}</p>`}${copyBlock(cmd, 'Copiar comando', g.exact)}`)}</section>`}
    <div class="btns">${g.to && h`<a class="btn btn-pri" href="${g.to}">${g.goLabel}</a>`}${g.also && h`<a class="btn" href="${g.also}">${g.alsoLabel}</a>`}${g.link && h`<a class="btn" href="${g.link}" target="_blank" rel="noopener">${icon('external-link')}${g.linkLabel}</a>`}<a class="btn btn-ghost" href="#/guias">${icon('arrow-left')}Todos os guias</a></div>
  </div>`;
}

// O guia do dia a dia na stack local e o de começar pressupõem o repositório.
const GUIDE_INSTALLED = { id: 'comecar', k: 'cfg', title: 'Por onde começar nesta máquina', when: 'Primeira vez, ou em dúvida sobre o que instalar', where: 'Terminal', steps: ['Só para organizar clientes e projetos: Python basta. É o que você já está usando.', 'Para guardar segredos nesta máquina: instale o Docker e suba o cofre.', 'Para trazer a conta de outra máquina: importe o repositório de configuração. Valores e chaves não vêm junto.', 'Em dúvida sobre o que falta, rode o doctor: ele mostra o comando deste sistema.'], cmds: [['Conferir esta máquina', 'cplane doctor'], ['Trazer a conta', 'cplane import <repositório>'], ['Subir o cofre', 'cplane vault up']] };
const guideList = () => (installed() ? GUIDES.filter((g) => g.id !== 'comecar-o-dia').map((g) => (g.id === 'comecar' ? GUIDE_INSTALLED : g)) : GUIDES);

function viewGuias(id) {
  if (id) {
    const g = guideList().find((x) => x.id === id);
    return g ? viewGuia(g) : empty('book-open', 'Guia não encontrado', '', h`<a class="btn" href="#/guias">Ver os guias</a>`);
  }
  const q = S.gQuery.trim().toLowerCase();
  const rows = guideList().filter((g) => (S.gKind === 'all' || g.k === S.gKind) && (!q || `${g.title} ${g.when} ${g.steps.join(' ')}`.toLowerCase().includes(q)));
  return h`
  ${pageHead('Guias', 'O que fazer em cada situação, onde fazer e o comando equivalente no terminal.')}
  <div class="filters"><div class="tabs" role="group" aria-label="Filtrar por tipo">${GUIDE_KINDS.map(([k, n]) => h`<button class="tab${S.gKind === k ? ' is-on' : ''}" data-act="gkind" data-k="${k}" aria-pressed="${S.gKind === k}">${n}</button>`)}</div>
  <label class="fld fld-grow" for="g-q">Buscar situação<input id="g-q" type="search" data-bind="gQuery" value="${S.gQuery}" placeholder="Vazou, reiniciar, logs, Neon"></label></div>
  ${rows.length ? h`<ul class="rows guides">
    ${rows.map((g) => h`<li id="guia-${g.id}"><a class="row-link" href="#/guias/${g.id}"><span class="row-main"><b>${g.title}</b><span class="muted">${g.when}</span></span><span class="row-side muted">${g.where}</span></a></li>`)}
  </ul>` : empty('book-open', 'Nenhum guia para essa busca', 'Tente outra palavra ou troque o filtro.')}`;
}

// ---------- Ferramentas ----------
const TOOL_ICON = { cofre: 'vault', coolify: 'server', openobserve: 'activity', umami: 'chart-column' };
function targetPicker() {
  return h`<fieldset class="segmented"><legend>Ver como</legend>
    ${['local', 'lab', 'vps'].map((t) => h`<label class="${S.target === t ? 'is-on' : ''}"><input type="radio" name="target" value="${t}" data-act="target"${S.target === t ? h` checked` : ''}>${targetName[t]}</label>`)}
  </fieldset>`;
}

function viewFerramentas() {
  const all = S.device?.checks || [];
  return h`
  ${pageHead('Ferramentas', 'Cada uma mantém o próprio login. Aqui estão o endereço, o usuário e o comando que entrega a senha ou o token, sem mostrar o valor.')}
  ${targetPicker()}
  <ul class="tools">${TOOLS.map((t) => {
    const a = t.access[S.target];
    const c = (t.checks[S.target] && all.find((x) => x.id === t.checks[S.target])) || null;
    const up = c && (c.state === 'ok' || c.sealed);
    return h`<li class="tool${t.id === 'cofre' ? ' tool-vault' : ''}"><div class="tool-main"><h2>${icon(TOOL_ICON[t.id] || 'wrench')}${t.name}</h2><p>${t.purpose}</p><p><b>Vá até lá para:</b> ${t.goFor}</p>
        ${a ? h`<dl class="facts facts-wide"><div><dt>Endereço</dt><dd><code>${a.url}</code></dd></div><div><dt>Usuário</dt><dd>${a.user}</dd></div></dl>
          <p>${a.secret}</p>${copyBlock(a.cmd, 'Copiar comando', true)}${a.after && h`<p class="cmd-label">Ao terminar, encerra os tokens abertos</p>${copyBlock(a.after, 'Copiar comando', true)}`}` : h`<p class="muted">Não existe em ${targetName[S.target].toLowerCase()}. Veja como Laboratório.</p>`}
      </div>
      <div class="tool-side">${S.target === 'vps' ? mark('off', 'Só pela tailnet') : a && (c ? mark(up ? (c.sealed ? 'warn' : 'ok') : 'off', up ? (c.sealed ? 'Selado' : 'No ar') : 'Não está aqui') : null)}
        ${up && a ? h`<a class="btn" href="${a.url}" target="_blank" rel="noopener">${icon('external-link')}Abrir</a>` : a && S.device && S.target !== 'vps' && h`<a class="inline-link" href="#/configurar/maquina">Como subir</a>`}</div></li>`;
  })}</ul>
  <section class="section" aria-labelledby="ext-title"><div class="sec-head"><h2 id="ext-title">Contas externas</h2><p class="muted">Ficam fora do control plane. Em cada cliente, use a conta dele.</p></div>
    <ul class="ext-tools">${EXTERNAL_TOOLS.map((t) => h`<li class="ext-tool"><h3>${t.name}</h3><p class="muted">${t.goFor} ${t.login}</p><a class="btn btn-small" href="${t.url}" target="_blank" rel="noopener">${icon('external-link')}Abrir</a></li>`)}</ul></section>`;
}

// ---------- Primeira visita ----------
const ROLE_TEXT = { teste: ['Teste', 'Uma máquina para experimentar. Nunca alcança produção.'], lab: ['Laboratório', 'Roda um ambiente de ensaio, separado da produção.'] };
const roleChoice = () => h`<fieldset class="setup-roles"><legend>O que é esta máquina?</legend>
  ${Object.entries(ROLE_TEXT).map(([k, [n, d]]) => h`<label class="check-opt"><input type="radio" name="s-role" data-act="setuprole" data-k="${k}"${S.setupForm.role === k ? h` checked` : ''}><span><b>${n}</b><span class="muted"> ${d}</span></span></label>`)}
  <p class="muted">A VPS que controla tudo vira principal depois, pelo terminal dela: <code>cplane machine promote</code>.</p></fieldset>`;
const setupKeyNote = () => (session.get() ? '' : h`<p class="caution" role="alert">Para gravar, abra o link que o terminal mostrou ao rodar <code>cplane</code>.</p>`);

function viewSetup() {
  const st = S.setup;
  const f = S.setupForm;
  const err = S.setupError && h`<p class="caution" role="alert">${S.setupError}</p>`;
  let body;
  if (st.needs_role) {
    body = h`<h1>${st.account || 'Conta importada'}</h1><p class="lede">A configuração chegou, só com nomes. Falta dizer o papel desta máquina (${st.machine.name}).</p>
      ${setupKeyNote()}${roleChoice()}${err}<div class="btns"><button class="btn btn-pri" data-act="setupsaverole">Continuar</button></div>`;
  } else if (S.setupStep === 'import') {
    const origin = f.origin.trim() || '<endereço do repositório>';
    body = h`<button class="link-btn" data-act="setupback">Voltar</button><h1>Importar uma conta</h1>
      <p class="lede">Traz clientes e projetos, só com nomes. Valores do cofre e chaves de unseal não vêm junto.</p>
      <label class="fld" for="s-origin">Repositório privado de configuração ou arquivo gerado por <code>cplane export</code><input id="s-origin" data-bind="setupForm.origin" value="${f.origin}" autocomplete="off" spellcheck="false" placeholder="git@github.com:sua-org/sua-config.git"></label>
      <p>Rode em outro terminal, nesta máquina. É por lá que o git usa a sua chave:</p>
      ${copyBlock(`cplane import ${origin}`, 'Copiar comando', true)}
      <p class="muted" role="status">Esta tela continua sozinha quando a importação terminar.</p>
      <details class="fold"><summary>Se der erro de acesso</summary><ol class="steps"><li>Confira se esta máquina fala com o GitHub.</li><li>Se o comando negar o acesso, cadastre a chave desta máquina na sua conta do GitHub.</li></ol>${copyBlock('ssh -T git@github.com', 'Copiar comando', true)}</details>`;
  } else if (S.setupStep === 'empty') {
    body = h`<button class="link-btn" data-act="setupback">Voltar</button><h1>Começar do zero</h1>
      <p class="lede">O nome identifica sua conta nesta e nas próximas máquinas.</p>
      ${setupKeyNote()}
      <label class="fld" for="s-name">Nome da conta<input id="s-name" data-bind="setupForm.name" value="${f.name}" autocomplete="off" placeholder="Sua empresa ou seu nome"></label>
      ${roleChoice()}${err}
      <div class="btns"><button class="btn btn-pri" data-act="setupstart" data-mode="empty"${f.name.trim().length < 2 ? h` disabled` : ''}>Criar a conta</button></div>`;
  } else {
    const option = (k, ic, title, text) => h`<button class="setup-opt" data-act="setupgo" data-k="${k}">${icon(ic)}<span><b>${title}</b><span class="muted">${text}</span></span></button>`;
    body = h`<h1>Como você quer começar?</h1>
      <p class="lede">Dá para mudar depois. Nada sai desta máquina.</p>
      ${setupKeyNote()}${err}
      <div class="setup-opts">
        ${option('import', 'download', 'Importar uma conta', 'Já uso o control plane em outra máquina ou tenho o repositório de configuração.')}
        ${option('empty', 'plus', 'Começar do zero', 'Criar a conta e organizar meus clientes e projetos.')}
        ${option('examples', 'layout-dashboard', 'Ver com exemplos', 'Conhecer as telas com uma empresa fictícia. Nada real é misturado.')}
      </div>`;
  }
  return h`<main class="setup" id="main" tabindex="-1"><p class="brand">${icon('shield-check')}<span>Control Plane</span></p><p class="muted setup-meta">Versão ${st.version}</p>${body}</main>`;
}

async function postSetup(body) {
  try {
    const res = await fetch('/api/setup', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CP-Key': session.get() || '' }, body: JSON.stringify(body) });
    const out = await res.json().catch(() => ({}));
    return res.ok ? out : { error: out.error || 'O painel recusou o pedido.' };
  } catch { return { error: 'O painel não respondeu.' }; }
}

async function applySetup(body) {
  S.setupError = '';
  const out = await postSetup(body);
  if (out.error) { S.setupError = out.error; render(); return; }
  S.setup = out.setup; S.setupStep = '';
  store.del(DEMO_KEY);
  await reloadBase();
  location.hash = '#/quadro';
  render();
  pollDevice();
}

function nextSteps() {
  if (!realView() || connected()) return '';
  const hasClients = S.data.clients.length > 0;
  const rows = [
    ['ok', `Conta ${S.setup.account || 'pronta'}`, 'Só nomes e estrutura, nesta máquina.'],
    ['ok', `Esta máquina é ${S.setup.role_name || 'sem papel'}`, S.setup.machine.name, '#/configurar/maquina#esta-instalacao', 'Ver'],
    [hasClients ? 'ok' : 'todo', hasClients ? `${S.data.clients.length === 1 ? '1 cliente' : `${S.data.clients.length} clientes`} na conta` : 'Crie o primeiro cliente', hasClients ? 'Cada cliente tem contas, projetos e ambientes próprios.' : 'Pode ser a sua própria empresa.', hasClients ? '#/clientes' : '#/novo-cliente', hasClients ? 'Abrir' : 'Criar'],
    ['todo', 'Conecte o cofre', 'É ele que troca os nomes pelo estado real. Precisa de Docker nesta máquina ou do acesso a uma principal.', '#/configurar/maquina#cofre', 'Ver como'],
  ];
  const done = rows.filter(([s]) => s === 'ok').length;
  return h`<section class="section" aria-labelledby="ns-title"><div class="sec-head"><h2 id="ns-title">Próximos passos</h2>${progressBar(done, rows.length, 'Próximos passos')}</div>
    <ul class="rows">${rows.map(([state, title, text, to, label]) => { const [k, l] = READY[state]; return h`<li class="row-plain">${mark(k, l)}<span class="row-main"><b>${title}</b><span class="muted">${text}</span></span>${to && h`<a class="btn btn-small" href="${to}">${label}</a>`}</li>`; })}</ul></section>`;
}

function machineSection() {
  const st = S.setup;
  if (!st || !installed()) return '';
  const facts = [['Versão', st.version], ['Nome', st.machine.name], ['Id', st.machine.id], ['Papel', st.role_name || 'Não definido'], ['Conta', realView() ? st.account || 'Sem nome' : 'Exemplos'], ['Configuração', st.config_dir]];
  return h`<section class="track" id="esta-instalacao" aria-labelledby="t-inst"><div class="sec-head"><h2 id="t-inst">Esta instalação</h2><p class="muted">O id identifica esta máquina e não muda em atualizações.</p></div>
    <dl class="facts">${facts.map(([k, v]) => h`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
    ${!realView() ? h`<div class="btns"><button class="btn" data-act="leaveexamples">Sair dos exemplos</button></div>`
    : st.machine.role !== 'principal' && h`<div class="btns">${Object.entries(ROLE_TEXT).filter(([k]) => k !== st.machine.role).map(([k, [n]]) => h`<button class="btn btn-small" data-act="changerole" data-k="${k}">Marcar como ${n}</button>`)}</div>`}
    ${S.setupError && h`<p class="caution" role="alert">${S.setupError}</p>`}</section>`;
}

// ---------- Novo cliente ----------
const wizProjects = (w, slug) => {
  const out = [];
  if (w.plat.vercel) out.push({ slug: `${slug}-web`, type: 'front-vercel' });
  if (w.plat.railway) out.push({ slug: `${slug}-api`, type: 'api-railway' });
  if (w.plat.coolify) out.push({ slug: w.plat.railway ? `${slug}-worker` : `${slug}-api`, type: 'api-coolify' });
  return out.concat(w.projExtra);
};
const wizSpec = (w) => {
  const slug = toSlug(w.name);
  return {
    name: w.name.trim(), slug, platforms: Object.keys(w.plat).filter((k) => w.plat[k]),
    projects: wizProjects(w, slug).filter((p) => !w.projOff[p.slug]).map((p) => ({ slug: p.slug, type: p.type, environments: ['dev', 'prod'] })),
    variables: w.vars, logs: w.logs, analytics: w.analytics,
  };
};
const saveOnly = () => realView() && !canAct() && !remoteOn();
const wizLabels = (w) => (saveOnly() ? ['Gravar o arquivo do cliente, só com nomes'] : [
  'Snapshot do cofre', 'Gravar o arquivo do cliente', 'Criar policies e identidades', 'Gerar os segredos internos',
  ...(w.logs ? ['Ligar os logs'] : []),
]);
async function loadPreview() {
  const w = S.wiz;
  w.preview = null; w.previewError = '';
  try {
    const res = await fetch(`/api/client-preview?spec=${encodeURIComponent(JSON.stringify(wizSpec(w)))}`);
    const out = await res.json();
    if (res.ok) w.preview = out.toml; else w.previewError = out.error;
  } catch { w.previewError = 'O painel não respondeu.'; }
  if (S.wiz === w && w.step === 4) render();
}

function viewNovoCliente() {
  if (remoteOn() && !canAct()) return empty('building-2', 'Cliente novo é feito na principal', 'Este dispositivo não pode criar clientes. No terminal da principal, abra o painel com --acoes.', h`<a class="btn" href="#/clientes">Ver os clientes</a>`);
  if (!S.wiz) S.wiz = emptyWiz();
  const w = S.wiz;
  const real = canAct();
  const slug = toSlug(w.name);
  const dup = S.data.clients.some((c) => c.id === slug);
  const chosen = Object.keys(w.plat).filter((k) => w.plat[k]);
  const hosts = chosen.filter((k) => !['github', 'droplet'].includes(k));
  const projAll = wizProjects(w, slug || 'cliente');
  const projOn = projAll.filter((p) => !w.projOff[p.slug]);
  const names = ['Cliente', 'Projetos', 'Variáveis', 'Revisão', 'Preparação'];
  let block = '';
  if (w.step === 1) block = !slug ? 'Informe o nome do cliente.' : !/^[a-z]/.test(slug) ? 'O nome precisa começar por letra.' : dup ? 'Já existe um cliente com esse identificador.' : !hosts.length ? 'Escolha ao menos uma plataforma de hospedagem.' : w.plat.droplet && !w.plat.coolify ? 'O Droplet é operado pelo Coolify: marque o Coolify também.' : '';
  if (w.step === 2 && !projOn.length) block = 'Escolha ao menos um projeto.';
  if (w.step === 4) block = w.previewError || (w.preview ? '' : 'Gerando o arquivo.');
  const job = w.jobId && S.data.activity.find((a) => a.id === w.jobId);
  const labels = wizLabels(w);
  const simDone = w.step === 5 && !w.jobId && w.run >= labels.length;
  const done = simDone || job?.result === 'ok';
  return h`
  <div class="wizard">
    ${pageHead('Novo cliente', 'Do contrato até o cliente pronto para receber as contas. Depois, o checklist dele mostra o que falta, passo a passo.')}
    ${real ? h`<div class="info">Isto cria o cliente de verdade no laboratório: grava o arquivo <code>${slug || 'cliente'}.toml</code> e prepara o cofre. Nenhum token passa por esta tela.</div>` : saveOnly() ? h`<div class="info">Isto grava o cliente na sua conta, só com nomes. O cofre e as contas entram depois, sem refazer nada.</div>` : exNote(installed() ? 'Simulação: nada é gravado. Para criar de verdade, saia dos exemplos em Configurar.' : 'Simulação: nada é gravado. Para criar de verdade no laboratório, abra com scripts/cp-lab cp-panel --acoes.')}
    <ol class="stepper" aria-label="Etapas">${names.map((n, i) => h`<li class="${i + 1 === w.step ? 'is-on' : i + 1 < w.step ? 'is-done' : ''}"${i + 1 === w.step ? h` aria-current="step"` : ''}><span class="stepper-n">${i + 1}</span>${n}</li>`)}</ol>

    ${w.step === 1 && h`<section class="panel"><h2>Quem é o cliente</h2>
      <div class="form-grid"><label class="fld" for="w-name">Nome<input id="w-name" data-bind="wiz.name" value="${w.name}" autocomplete="off" placeholder="Loja Exemplo"></label>
      <p class="fld">Identificador gerado<output class="slug"><code>${slug || 'aparece aqui'}</code></output></p></div></section>
      <section class="panel"><h2>Onde ele roda</h2><p class="muted">Só aparecem as plataformas com esteira pronta. Todas usam a conta do próprio cliente.</p>
      ${Object.entries(WIZ_PLATFORMS).map(([k, p]) => h`<label class="check-opt"><input type="checkbox" data-act="wplat" data-k="${k}"${w.plat[k] ? h` checked` : ''}><span><b>${p.name}</b><span class="muted"> ${p.desc}</span></span></label>`)}</section>`}

    ${w.step === 2 && h`<section class="panel"><h2>Projetos deste cliente</h2><p class="muted">Cada projeto começa com dev e prod. Depois de conectar as contas, Buscar projetos mostra o que elas enxergam.</p>
      ${projAll.map((p) => h`<label class="check-opt"><input type="checkbox" data-act="wproj" data-k="${p.slug}"${!w.projOff[p.slug] ? h` checked` : ''}><span><code>${p.slug}</code><span class="muted"> ${typeName(p.type)}${p.type === 'api-railway' ? ', falta completar os ids depois' : ''}</span></span></label>`)}
      <div class="form-inline"><label class="fld fld-grow" for="w-extra">Outro projeto<input id="w-extra" data-bind="wiz.extra" value="${w.extra}" autocomplete="off" placeholder="lp-exemplo"></label>
      ${select('w-extra-type', 'Tipo', 'wiz.extraType', w.extraType || 'front-vercel', Object.entries(APP_TYPES).map(([k, v]) => [k, v.name]))}
      <button class="btn" data-act="waddproj"${!toProject(w.extra) ? h` disabled` : ''}>Adicionar</button></div></section>`}

    ${w.step === 3 && h`<section class="panel"><h2>Variáveis que cada projeto precisa</h2><p class="muted">Só o que está nesta lista chega ao destino. Os valores não passam por esta tela. <code>NODE_ENV</code> já vem definido por ambiente.</p>
      <ul class="fields">${w.vars.map((v, i) => h`<li><code>${v.name}</code><span class="muted">${v.origin === 'generated' ? 'Gerada no cofre' : 'Você grava no cofre'}</span><button class="link-btn" data-act="wvardel" data-i="${i}">Remover</button></li>`)}</ul>
      <div class="form-inline"><label class="fld fld-grow" for="w-var">Outra variável<input id="w-var" data-bind="wiz.newVar" value="${w.newVar}" autocomplete="off" placeholder="RESEND_API_KEY"></label>
      ${select('w-var-origin', 'Valor', 'wiz.newVarOrigin', w.newVarOrigin, [['manual', 'Você grava no cofre'], ['generated', 'Gerada no cofre']])}
      <button class="btn" data-act="wvaradd"${!/^[A-Z][A-Z0-9_]{1,62}$/.test(w.newVar) ? h` disabled` : ''}>Adicionar</button></div></section>
      <section class="panel"><h2>Logs e analytics</h2>
      <label class="check-opt"><input type="checkbox" data-act="wlogs"${w.logs ? h` checked` : ''}><span><b>Ligar logs</b><span class="muted"> Cria as orgs por ambiente e o token de envio.</span></span></label>
      <label class="check-opt"><input type="checkbox" data-act="wanalytics"${w.analytics ? h` checked` : ''}><span><b>Quero analytics</b><span class="muted"> Precisa do domínio de cada front, então entra depois, pelo guia.</span></span></label></section>`}

    ${w.step === 4 && h`<section class="panel"><h2>O que será feito agora</h2><ol class="steps">${labels.map((l) => h`<li>${l}</li>`)}</ol>
      <p class="caution"><b>Fica com você, no checklist do cliente:</b> conectar as contas, cadastrar a VPS, gravar os valores vindos de painéis externos e decidir quando levar para prod.</p></section>
      <section class="panel"><h2>Arquivo do cliente, só com nomes</h2>${w.preview ? copyBlock(w.preview, 'Copiar arquivo') : h`<p class="muted" role="status">${w.previewError || 'Gerando o arquivo.'}</p>`}</section>`}

    ${w.step === 5 && w.saved ? h`<section class="panel"><h2>Cliente salvo</h2><p>O arquivo <code>${w.slugDone}.toml</code> está em <code>${S.setup.config_dir}</code>.</p>
      ${S.setup.config_git && h`<p class="muted">Sua conta vem de um repositório. Para as outras máquinas receberem este cliente, envie a mudança:</p>${copyBlock(`git -C "${S.setup.config_dir}" add .\ngit -C "${S.setup.config_dir}" commit -m "Novo cliente: ${w.slugDone}"\ngit -C "${S.setup.config_dir}" push`, 'Copiar comandos', true)}`}</section>
      <div><a class="btn btn-pri" href="#/clientes/${w.slugDone}">Abrir o cliente</a></div>` : ''}
    ${w.step === 5 && !w.saved && (w.jobId ? h`<section class="panel"><h2>${job?.result === 'ok' ? 'Cliente preparado' : job?.result === 'err' ? 'A preparação parou' : 'Preparando o cliente'}</h2>
        <div class="row-detail"><ol class="steps" role="status">${(job?.steps || []).map((s) => h`<li>${s}</li>`)}</ol></div>
        ${job?.result === 'err' && h`<p class="caution">O arquivo do cliente já foi gravado. Abra o cliente e use Terminar a preparação depois de corrigir: o que já foi feito não se repete.</p>`}</section>
        ${job && job.result !== 'running' && h`<div><a class="btn btn-pri" href="#/clientes/${w.slugDone}">Abrir o cliente</a></div>`}`
    : h`<section class="panel"><h2>${simDone ? 'Simulação concluída' : 'Simulando a preparação'}</h2>
      <ul class="rows" role="status">${labels.map((l, i) => { const st = i < w.run ? ['ok', 'Feito'] : i === w.run ? ['warn', 'Rodando'] : ['off', 'Na fila']; return h`<li class="row-plain">${mark(st[0], st[1], true)}<span class="row-main">${l}</span></li>`; })}</ul></section>
      ${done && h`<div class="info"><b>${w.name.trim()} entrou nas telas como exemplo.</b> Nada foi gravado no cofre nem no repositório.</div>
      <div><a class="btn btn-pri" href="#/clientes/${slug}">Abrir o cliente</a></div>`}`)}

    ${w.step < 5 && h`<footer class="wiz-nav"><a class="btn btn-ghost" href="#/clientes" data-act="wcancel">Cancelar</a>
      <span class="btns">${w.step > 1 && h`<button class="btn" data-act="wback">Voltar</button>`}<button class="btn btn-pri" data-act="wnext" data-block="${block}"${block ? h` disabled` : ''}>${w.step === 4 ? (real ? 'Criar o cliente' : saveOnly() ? 'Salvar o cliente' : 'Simular') : 'Continuar'}</button></span></footer>
      ${w.step === 4 && real && remoteOn() && totpField()}
      ${w.error && h`<p class="caution" role="alert">${w.error}</p>`}
      ${block && h`<p class="muted wiz-block" role="status">${block}</p>`}`}
  </div>`;
}

function finishWizard() {
  const w = S.wiz;
  const slug = toSlug(w.name);
  const name = w.name.trim();
  const chosen = Object.keys(w.plat).filter((k) => w.plat[k]);
  const projs = wizProjects(w, slug).filter((p) => !w.projOff[p.slug]);
  S.data.clients.push({ id: slug, name, hosting: chosen.map((k) => PROVIDERS[k].name).join(', ') });
  for (const k of chosen) {
    const hasToken = k !== 'droplet';
    S.data.accounts.push({ id: `${slug}-${k}`, client: slug, provider: k, name: hasToken ? k : `vps-${slug}`, label: hasToken ? `Conta de ${name}` : `Droplet de ${name}`, state: hasToken ? 'missing' : 'notoken', expires: hasToken ? 'Ainda sem token' : 'Sem token', tested: 'Nunca testada', fields: Object.keys(PROVIDERS[k].fields).map((f) => ({ name: f, set: false })), serves: projs.map((p) => p.slug) });
  }
  for (const p of projs) {
    const where = p.type.endsWith('coolify') ? `vps-${slug}` : p.type === 'front-vercel' ? 'Vercel' : 'Railway';
    S.data.apps.push({ id: `${slug}--${p.slug}`, client: slug, name: p.slug, type: p.type, ready: { conta: 'todo', segredos: 'todo', host: 'todo', logs: w.logs ? 'ok' : 'todo' }, envs: { dev: { state: 'waiting', version: 'Aguardando', commit: '', when: 'Sem deploy', where }, prod: { state: 'waiting', version: 'Aguardando', commit: '', when: 'Sem deploy', where } } });
  }
  S.data.rollout[slug] = [
    { title: 'Contas conectadas', state: 'todo', hint: 'Cada conta tem o passo a passo.', to: `#/contas/${slug}-${chosen[0]}`, toLabel: 'Abrir a conta' },
    { title: 'Projetos declarados', state: 'ok' }, { title: 'Segredos internos gerados', state: 'ok' },
    { title: 'Valores vindos de painéis externos', state: 'todo', hint: 'Preencha DATABASE_URL e as demais no cofre.', to: '#/ferramentas', toLabel: 'Abrir ferramentas' },
    { title: 'Logs ligados', state: w.logs ? 'ok' : 'todo', hint: 'Ligue quando o app estiver pronto.', to: '#/guias/ligar-logs', toLabel: 'Ver guia' },
    { title: 'VPS cadastrada no Coolify', state: w.plat.coolify ? 'todo' : 'na', hint: 'Rode o instalador na VPS do cliente.', to: '#/guias/vps-nova', toLabel: 'Ver guia' },
    { title: 'Segredos levados para dev', state: 'todo', hint: 'Leve depois de conectar as contas.' },
    { title: 'Segredos levados para prod', state: 'todo', hint: 'Leve quando os valores estiverem conferidos.', action: 'prod' },
  ];
  record(`Cliente ${name} simulado`, wizLabels(w));
  saveDemo();
}

// ---------- Janelas ----------
const READ_ACTIONS = ['sync_plan', 'discover'];  // no servidor: read_only em actions.py
const asksCode = (m) => remoteOn() && (m.needCode || (!['dev', 'staging'].includes(m.env) && !READ_ACTIONS.includes(m.action)));
const totpField = () => (S.auth?.fresh ? '' : h`<label class="fld" for="m-totp">Código do autenticador<input id="m-totp" inputmode="numeric" autocomplete="one-time-code" maxlength="6"></label>`);
function modalView() {
  const m = S.modal;
  if (!m) return '';
  if (m.type === 'machine') {
    const classes = Object.entries(S.machines?.classes || {});
    return h`<dialog id="modal" aria-labelledby="m-title"><form method="dialog" class="modal-body">
      <h2 id="m-title">${{ approve: 'Aprovar', class: 'Trocar a classe de', revoke: 'Cortar o acesso de' }[m.op]} ${m.name}</h2>
      ${m.op === 'approve' && h`<p>Digite o código que aparece na tela do dispositivo. Se não reconhecer o pedido, recuse.</p><label class="fld" for="m-code">Código do dispositivo<input id="m-code" autocomplete="off" spellcheck="false" maxlength="12"></label>`}
      ${m.op === 'revoke' && h`<p>O dispositivo perde o acesso na hora. Tentativas seguintes ficam registradas.</p>`}
      ${m.op !== 'revoke' && h`<label class="fld" for="m-class">Classe<select id="m-class">${classes.map(([k, n]) => h`<option value="${k}"${k === m.klass ? h` selected` : ''}>${n}</option>`)}</select></label>`}
      ${totpField()}
      ${m.error && h`<p class="caution" role="alert">${m.error}</p>`}
      <div class="modal-foot"><button class="btn" type="button" data-act="closemodal">Cancelar</button><button class="btn btn-danger" id="m-ok" type="button" data-act="machinerun">Confirmar</button></div></form></dialog>`;
  }
  if (m.type === 'real') {
    return h`<dialog id="modal" aria-labelledby="m-title"><form method="dialog" class="modal-body">
      <h2 id="m-title">${m.label}</h2>
      <p>Isto executa de verdade ${where().em}, em segundo plano. O resultado aparece em Atividade.</p>
      ${m.confirm && h`<label class="fld" for="m-confirm">Em prod, digite <code>${m.confirm}</code> para confirmar<input id="m-confirm" autocomplete="off" data-expected="${m.confirm}"></label>`}
      ${asksCode(m) && totpField()}
      ${m.error && h`<p class="caution" role="alert">${m.error}</p>`}
      <div class="modal-foot"><button class="btn" type="button" data-act="closemodal">Cancelar</button><button class="btn btn-danger" id="m-ok" type="button" data-act="realrun"${m.confirm ? h` disabled` : ''}>Executar</button></div>
    </form></dialog>`;
  }
  if (m.type === 'action') {
    const prod = m.env === 'prod';
    return h`<dialog id="modal" aria-labelledby="m-title"><form method="dialog" class="modal-body">
      <h2 id="m-title">${m.verb} ${m.name}</h2>
      <p class="muted">Simulação: nada é executado. ${prod ? 'Em prod, a confirmação exige digitar o nome.' : `Ambiente ${m.env}.`} O registro fica em Atividade.</p>
      ${prod && h`<label class="fld" for="m-confirm">Digite <code>${m.name}</code> para confirmar<input id="m-confirm" data-act="typeconfirm" autocomplete="off" data-expected="${m.name}"></label>`}
      <div class="modal-foot"><button class="btn" type="button" data-act="closemodal">Cancelar</button><button class="btn btn-danger" id="m-ok" type="button" data-act="confirmaction"${prod ? h` disabled` : ''}>Simular</button></div>
    </form></dialog>`;
  }
  if (m.type === 'revoke') {
    const a = S.data.accounts.find((x) => x.id === m.id);
    const p = PROVIDERS[a.provider];
    return h`<dialog id="modal" aria-labelledby="m-title"><form method="dialog" class="modal-body">
      <h2 id="m-title">Revogar ${p.name} de ${clientName(a.client)}</h2>
      <p>${p.revokeHelp}</p><p class="muted">O sync deste cliente para até um token novo ser gravado. Aqui é só simulação.</p>
      ${p.url && p.revoke === 'manual' && h`<a class="btn" href="${p.url}" target="_blank" rel="noopener">${p.urlLabel}</a>`}
      <div class="modal-foot"><button class="btn" type="button" data-act="closemodal">Cancelar</button><button class="btn btn-danger" type="button" data-act="confirmrevoke">${p.revoke === 'manual' ? 'Simular: marcar como revogada' : 'Simular a revogação'}</button></div>
    </form></dialog>`;
  }
  if (m.type === 'newacc') {
    return h`<dialog id="modal" aria-labelledby="m-title"><form method="dialog" class="modal-body">
      <h2 id="m-title">Conectar conta</h2><p class="muted">Escolha de quem é a conta e a plataforma. Em seguida, o painel mostra o passo a passo dela.</p>
      <label class="fld" for="n-client">Cliente<select id="n-client">${S.data.clients.map((c) => h`<option value="${c.id}"${c.id === m.client ? h` selected` : ''}>${c.name}</option>`)}</select></label>
      <label class="fld" for="n-prov">Plataforma<select id="n-prov">${Object.entries(PROVIDERS).map(([k, p]) => h`<option value="${k}">${p.name}</option>`)}</select></label>
      <div class="modal-foot"><button class="btn" type="button" data-act="closemodal">Cancelar</button><button class="btn btn-pri" type="button" data-act="confirmnewacc">Ver o passo a passo</button></div>
    </form></dialog>`;
  }
  if (m.type === 'offboard') {
    return h`<dialog id="modal" aria-labelledby="m-title"><form method="dialog" class="modal-body">
      <h2 id="m-title">Encerrar ${clientName(m.client)}</h2>
      <p class="muted">Exporta os segredos para o Bitwarden do cliente e tira o seu acesso. Os containers continuam rodando na VPS dele.</p>
      <h3>O painel fará</h3><ol class="steps"><li>Snapshot do cofre.</li><li>Export dos segredos do cliente.</li><li>Revogação dos tokens que a plataforma permite.</li><li>Remoção das identidades e dos caminhos dele no cofre.</li></ol>
      <h3>Você faz depois</h3><ol class="steps"><li>Importa o export no Bitwarden do cliente e apaga o arquivo.</li><li>Remove a chave SSH de cada VPS dele.</li><li>Remove os servidores no Coolify e os nós da tailnet.</li><li>Revoga o token da Railway na plataforma, se houver.</li></ol>
      ${copyBlock(`scripts/cp-secrets backup\nscripts/cp-secrets offboard ${m.client}\nscripts/cp-obs revoke ${m.client}`)}
      <div class="modal-foot"><button class="btn" type="button" data-act="closemodal">Fechar</button></div>
    </form></dialog>`;
  }
  return '';
}

// ---------- Estado de exemplo ----------
function saveDemo() { if (!connected() && !realView()) store.set(DEMO_KEY, JSON.stringify(S.data)); } // conectado, nada real vai para o navegador guardar
function record(action, steps) {
  const now = new Date();
  S.data.activity.unshift({ id: `a${now.getTime()}`, time: now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }), who: 'Operador', action, where: targetName[S.target], result: 'sim', steps });
}
function notify(msg) {
  S.toast = msg;
  clearTimeout(notify.t);
  notify.t = setTimeout(() => { S.toast = ''; paintToast(); }, 3500);
  paintToast();
}
function paintToast() {
  const el = document.getElementById('toast');
  if (el) { el.textContent = S.toast; el.hidden = !S.toast; }
}

// ---------- Ações ----------
const closeModal = () => { S.modal = null; render(); };
const ACTIONS = {
  sidetoggle() { store.set(SIDE_KEY, store.get(SIDE_KEY) === 'collapsed' ? 'open' : 'collapsed'); render(); },
  navopen() { S.navOpen = true; render(); document.querySelector('.side a')?.focus(); },
  navclose() { S.navOpen = false; render(); document.querySelector('.top .top-menu')?.focus(); },
  appstate(el) { S.fApps = { client: '', type: '', q: '', state: el.dataset.state === 'all' ? '' : el.dataset.state }; },
  logpage(el) { S.logPage = Number(el.dataset.p); S.openLog = null; render(); window.scrollTo(0, 0); },
  theme() { S.theme = { dark: 'light', light: 'auto', auto: 'dark' }[S.theme]; store.set('cp-panel-theme', S.theme); applyTheme(); render(); },
  async copy(el) {
    try { await navigator.clipboard.writeText(el.dataset.text); notify('Copiado.'); } catch { notify('Não foi possível copiar. Selecione o texto e copie à mão.'); }
  },
  target(el) { S.target = el.value; store.set('cp-panel-target', S.target); render(); },
  ask(el) { S.modal = { type: 'action', verb: el.dataset.verb, name: el.dataset.name, env: el.dataset.env, diverge: el.dataset.diverge, backup: el.dataset.backup, client: el.dataset.client, kind: el.dataset.kind }; render(); },
  closemodal: closeModal,
  realask(el) { const d = el.dataset; S.modal = { type: 'real', action: d.action, label: d.label, client: d.client, app: d.app, env: d.env, target: d.target, provider: d.provider, confirm: d.confirm }; render(); },
  async realrun() {
    const m = S.modal;
    const typed = document.getElementById('m-confirm')?.value;
    const body = { action: m.action, client: m.client };
    for (const k of ['app', 'env', 'target', 'provider']) if (m[k]) body[k] = m[k];
    if (typed) body.confirm = typed;
    try {
      const code = document.getElementById('m-totp')?.value;
      if (code) {
        const up = await authPost('step-up', { code });
        if (up.error) { S.modal = { ...m, error: up.error }; render(); return; }
        S.auth.fresh = true;
      }
      const res = await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CP-Key': session.get() || '' }, body: JSON.stringify(body) });
      const out = await res.json();
      if (res.status === 428) S.auth.fresh = false;
      if (!res.ok) { S.modal = { ...m, error: out.error || 'O painel recusou o pedido.', needCode: res.status === 428 }; render(); return; }
      S.modal = null;
      S.openAct = out.job.id;
      location.hash = '#/atividade';
      notify('Em andamento. O resultado aparece aqui.');
      await refreshData(true);
      watchJobs();
    } catch { S.modal = { ...m, error: 'O painel não respondeu. Confira em Atividade antes de tentar de novo.' }; render(); }
  },
  typeconfirm() { /* tratado no evento input */ },
  confirmaction() {
    const m = S.modal;
    if (m.diverge) S.data.diverge = S.data.diverge.filter((d) => d.id !== m.diverge);
    if (m.backup) { const e = S.data.apps.find((a) => a.id === m.backup).envs[m.env]; e.backup = 'Sucesso agora'; e.backupFailed = false; delete e.next; }
    if (m.kind === 'prod') {
      S.data.rollout[m.client].filter((p) => p.action === 'prod').forEach((p) => { p.state = 'ok'; });
      S.data.apps.filter((a) => a.client === m.client).forEach((a) => { if (a.envs.prod?.state === 'waiting') Object.assign(a.envs.prod, { state: 'running', version: a.envs.dev.version, when: 'agora', next: '' }); });
    }
    record(`${m.verb} ${m.name} (${m.env})`, ['Simulado: nada foi executado.']);
    saveDemo();
    S.modal = null;
    render();
    notify('Simulado. Veja em Atividade.');
  },
  offboard(el) { S.modal = { type: 'offboard', client: el.dataset.client }; render(); },
  seelogs(el, ev) { ev.preventDefault(); S.fLogs = { client: el.dataset.client, env: el.dataset.env, level: '', q: el.dataset.q }; S.openLog = null; S.logPage = 0; location.hash = '#/logs'; },
  clearlogs() { S.fLogs = { client: '', env: '', level: '', q: '' }; S.openLog = null; S.logPage = 0; render(); },
  openlog(el) { S.openLog = S.openLog === el.dataset.id ? null : el.dataset.id; render(); },
  openact(el) { S.openAct = S.openAct === el.dataset.id ? null : el.dataset.id; render(); },
  setupgo(el) {
    const k = el.dataset.k;
    if (k === 'examples') { applySetup({ action: 'start', mode: 'examples' }); return; }
    S.setupStep = k; S.setupError = ''; render(); window.scrollTo(0, 0);
  },
  setupback() { S.setupStep = ''; S.setupError = ''; render(); },
  setuprole(el) { S.setupForm.role = el.dataset.k; render(); },
  setupstart(el) { applySetup({ action: 'start', mode: el.dataset.mode, name: S.setupForm.name, role: S.setupForm.role }); },
  setupsaverole() { applySetup({ action: 'role', role: S.setupForm.role }); },
  async changerole(el) { const out = await postSetup({ action: 'role', role: el.dataset.k }); S.setupError = out.error || ''; if (out.setup) S.setup = out.setup; render(); },
  leaveexamples() { S.setupStep = ''; applySetup({ action: 'leave_examples' }); },
  async authrequest() {
    const out = await authPost('request', { name: document.getElementById('a-name')?.value || '' });
    S.authError = out.error || '';
    if (!out.error) await refreshAuth();
    render();
  },
  async authlogin() {
    const value = (id) => document.getElementById(id)?.value || '';
    const out = await authPost('login', { username: value('a-user'), password: value('a-pass'), code: value('a-code') });
    if (out.error) { S.authError = out.error; document.getElementById('a-pass').value = ''; document.getElementById('a-code').value = ''; render(); return; }
    location.reload();
  },
  async logout() { await authPost('logout', {}); location.reload(); },
  machineask(el) { const d = el.dataset; S.modal = { type: 'machine', op: d.op, id: d.id, name: d.name, klass: d.class || 'operacao' }; render(); },
  async machinerun() {
    const m = S.modal;
    const value = (id) => document.getElementById(id)?.value || '';
    const stay = (error) => { const saved = value('m-code'); S.modal = { ...m, error, klass: value('m-class') || m.klass }; render(); const f = document.getElementById('m-code'); if (f) f.value = saved; };
    if (!S.auth.fresh || value('m-totp')) {
      const up = await authPost('step-up', { code: value('m-totp') });
      if (up.error) { stay(up.error); return; }
      S.auth.fresh = true;
    }
    const body = m.op === 'approve' ? { action: 'approve', code: value('m-code'), class: value('m-class') } : m.op === 'class' ? { action: 'set_class', id: m.id, class: value('m-class') } : { action: 'revoke', id: m.id };
    const out = await machinePost(body);
    if (out.error) { stay(out.error); return; }
    S.modal = null;
    await refreshAuth();
    await loadMachines();
    render();
    notify(m.op === 'approve' ? 'Dispositivo aprovado.' : m.op === 'revoke' ? 'Acesso cortado.' : 'Classe alterada.');
  },
  resetdemo() { store.del(DEMO_KEY); S.data = structuredClone(S.base); render(); notify('Exemplos no estado inicial.'); },
  testacc(el) {
    const a = S.data.accounts.find((x) => x.id === el.dataset.id);
    if (a.state === 'missing') return notify('Simulação: esta conta ainda não tem token para testar.');
    if (a.state === 'expired') return notify('Simulação: a plataforma recusou o token vencido.');
    a.tested = 'Testada agora';
    saveDemo(); render(); notify('Simulação: token aceito pela plataforma.');
    return undefined;
  },
  revokeacc(el) { S.modal = { type: 'revoke', id: el.dataset.id }; render(); },
  confirmrevoke() {
    const a = S.data.accounts.find((x) => x.id === S.modal.id);
    Object.assign(a, { state: 'missing', expires: 'Ainda sem token', tested: 'Nunca testada' });
    a.fields.forEach((f) => { if (['token', 'private_key'].includes(f.name)) f.set = false; });
    record(`Token de ${PROVIDERS[a.provider].name} de ${clientName(a.client)} revogado`, ['Simulado: nada foi executado.']);
    saveDemo(); S.modal = null; render(); notify('Simulado. Veja em Atividade.');
  },
  newacc(el) { S.modal = { type: 'newacc', client: el.dataset.client }; render(); },
  confirmnewacc() {
    const client = document.getElementById('n-client').value;
    const provider = document.getElementById('n-prov').value;
    const p = PROVIDERS[provider];
    let id = `${client}-${provider}`;
    let name = provider === 'droplet' ? `vps-${client}` : provider;
    for (let n = 2; S.data.accounts.some((a) => a.id === id); n += 1) { id = `${client}-${provider}-${n}`; name = `${provider}-${n}`; }
    const hasToken = provider !== 'droplet';
    S.data.accounts.push({ id, client, provider, name, label: `Conta de ${clientName(client)}`, state: hasToken ? 'missing' : 'notoken', expires: hasToken ? 'Ainda sem token' : 'Sem token', tested: 'Nunca testada', fields: Object.keys(p.fields).map((f) => ({ name: f, set: false })), serves: [] });
    saveDemo(); S.modal = null; location.hash = `#/contas/${id}`; render();
  },
  gkind(el) { S.gKind = el.dataset.k; render(); },
  wplat(el) { S.wiz.plat[el.dataset.k] = el.checked; render(); },
  wproj(el) { S.wiz.projOff[el.dataset.k] = !el.checked; render(); },
  wlogs(el) { S.wiz.logs = el.checked; render(); },
  wanalytics(el) { S.wiz.analytics = el.checked; render(); },
  waddproj() {
    const w = S.wiz;
    const slug = toProject(w.extra);
    if (slug && !wizProjects(w, toSlug(w.name)).some((p) => p.slug === slug)) w.projExtra.push({ slug, type: w.extraType || 'front-vercel' });
    w.extra = '';
    render();
  },
  wvaradd() {
    const w = S.wiz;
    if (!w.vars.some((v) => v.name === w.newVar) && w.newVar !== 'NODE_ENV') w.vars.push({ name: w.newVar, origin: w.newVarOrigin });
    w.newVar = '';
    render();
  },
  wvardel(el) { S.wiz.vars.splice(Number(el.dataset.i), 1); render(); },
  wback() { S.wiz.step -= 1; if (S.wiz.step === 4) loadPreview(); render(); window.scrollTo(0, 0); },
  wcancel() { S.wiz = null; },
  async wnext() {
    const w = S.wiz;
    w.error = '';
    if (w.step === 4 && saveOnly()) {
      const out = await postSetup({ action: 'client', spec: wizSpec(w) });
      if (out.error) { w.error = out.error; render(); return; }
      w.step = 5; w.saved = true; w.slugDone = out.slug;
      S.setup = out.setup;
      await reloadBase();
      render(); window.scrollTo(0, 0);
      pollDevice();
      return;
    }
    if (w.step === 4 && canAct()) {
      const code = document.getElementById('m-totp')?.value;
      if (code) {
        const up = await authPost('step-up', { code });
        if (up.error) { w.error = up.error; render(); return; }
        S.auth.fresh = true;
      }
      const res = await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CP-Key': session.get() || '' }, body: JSON.stringify({ action: 'client_create', spec: wizSpec(w) }) }).catch(() => null);
      const out = res ? await res.json().catch(() => ({})) : {};
      if (res?.status === 428) S.auth.fresh = false;
      if (!res || !res.ok) { w.error = out.error || 'O painel não respondeu.'; render(); return; }
      w.step = 5; w.jobId = out.job.id; w.slugDone = toSlug(w.name);
      await refreshData(true);
      watchJobs();
      render(); window.scrollTo(0, 0);
      return;
    }
    if (w.step === 4) {
      w.step = 5; w.run = 0; render();
      const total = wizLabels(w).length;
      const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
      clearInterval(ACTIONS.timer);
      ACTIONS.timer = setInterval(() => {
        w.run = reduce ? total : w.run + 1;
        if (w.run >= total) { clearInterval(ACTIONS.timer); finishWizard(); }
        if (location.hash === '#/novo-cliente') render();
      }, reduce ? 1 : 450);
    } else {
      w.step += 1;
      if (w.step === 4) loadPreview();
      render();
    }
    window.scrollTo(0, 0);
  },
};

// ---------- Renderização ----------
function route() {
  const clean = location.hash.replace(/^#\/?/, '').split('#');
  const parts = clean[0].split('/').filter(Boolean);
  return { name: parts[0] || 'quadro', arg: parts[1], sub: parts[2], anchor: clean[1] };
}

function viewFor(r) {
  switch (r.name) {
    case 'clientes': return viewClientes(r.arg, r.sub);
    case 'aplicacoes': return viewAplicacoes(r.arg, r.sub);
    case 'logs': return viewLogs();
    case 'atividade': return viewAtividade();
    case 'configurar': return viewConfigurar(r.arg);
    case 'contas': return viewContas(r.arg);
    case 'guias': return viewGuias(r.arg);
    case 'ferramentas': return viewFerramentas();
    case 'novo-cliente': return viewNovoCliente();
    case 'maquinas': return viewMaquinas();
    default: return viewQuadro();
  }
}

// Em uma instalação, os scripts são subcomandos do cplane. Um só lugar: nenhuma tela mostra comando que não existe aqui.
const forInstall = (html) => (!installed() ? html : html
  .replace(/já lido com scripts\/cp-lab cp-panel/g, 'lido com o cofre conectado')
  .replace(/scripts\/cp-lab cp-panel/g, 'cplane lab panel')
  .replace(/scripts\/cp-lab cp-(secrets|coolify|obs)/g, 'cplane lab $1')
  .replace(/scripts\/cp-(secrets|coolify|obs)/g, 'cplane $1')
  .replace(/scripts\/cp-panel/g, 'cplane'));

function render() {
  const app = document.getElementById('app');
  if (S.failed) {
    app.innerHTML = h`<main class="fatal"><h1>O servidor do painel não respondeu.</h1><p>Rode <code>${installed() ? 'cplane' : 'scripts/cp-panel'}</code> no terminal e recarregue esta página.</p></main>`.s;
    return;
  }
  if (S.auth?.remote && S.auth.state !== 'ok') {
    app.dataset.first = 'yes';
    const typing = document.activeElement?.matches?.('input');
    if (S.authShown === S.auth.state + S.authError && typing) return; // não apaga a senha que está sendo digitada
    S.authShown = S.auth.state + S.authError;
    app.innerHTML = viewAuth().s;
    return;
  }
  if (!S.data) return;
  HOME.slug = homeId();
  const focus = focusKey(document.activeElement);
  const sel = document.activeElement && 'selectionStart' in document.activeElement ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  const sideTop = document.getElementById('side-scroll')?.scrollTop || 0;
  const r = route();
  const active = r.name === 'novo-cliente' ? 'clientes' : r.name;
  app.dataset.side = store.get(SIDE_KEY) === 'collapsed' ? 'collapsed' : 'open';
  app.dataset.nav = S.navOpen ? 'open' : 'closed';
  const first = S.setup?.needs_setup || S.setup?.needs_role;
  app.dataset.first = first ? 'yes' : 'no';
  app.innerHTML = forInstall(first ? h`${viewSetup()}<div id="toast" class="toast" role="status"${S.toast ? '' : h` hidden`}>${S.toast}</div>`.s
    : h`${sidebar(active)}<div class="scrim" data-act="navclose"></div><div class="stage"${S.navOpen ? h` inert` : ''}>${topbar(r)}<main class="main" id="main" tabindex="-1">${viewFor(r)}</main></div>${new Raw(ser(modalView()))}<div id="toast" class="toast" role="status"${S.toast ? '' : h` hidden`}>${S.toast}</div>`.s);
  const side = document.getElementById('side-scroll');
  if (side) side.scrollTop = sideTop;
  const dlg = document.getElementById('modal');
  if (dlg) { dlg.showModal(); dlg.addEventListener('cancel', () => { S.modal = null; setTimeout(render); }); }
  if (focus && !dlg) {
    const el = document.querySelector(focus);
    if (el) { el.focus({ preventScroll: true }); if (sel && el.setSelectionRange) { try { el.setSelectionRange(sel[0], sel[1]); } catch { /* tipo sem seleção */ } } }
  }
}

// O painel redesenha a tela inteira: sem isto, quem navega pelo teclado perderia o lugar a cada leitura.
function focusKey(el) {
  if (!el || el === document.body) return '';
  if (el.id) return `#${CSS.escape(el.id)}`;
  if (el.matches('a[href]')) return `${el.closest('.side') ? '.side ' : ''}a[href="${CSS.escape(el.getAttribute('href'))}"]`;
  if (el.dataset.act) return `[data-act="${CSS.escape(el.dataset.act)}"]${el.dataset.id ? `[data-id="${CSS.escape(el.dataset.id)}"]` : ''}${el.dataset.k ? `[data-k="${CSS.escape(el.dataset.k)}"]` : ''}`;
  return '';
}

function setPath(path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  keys.reduce((o, k) => o[k], S)[last] = value;
}

function applyTheme() {
  document.documentElement.setAttribute('data-theme', S.theme);
}

document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el || el.matches('input[type=radio], input[type=checkbox], input:not([type])')) return;
  ACTIONS[el.dataset.act]?.(el, ev);
});
document.addEventListener('change', (ev) => {
  const el = ev.target;
  if (el.matches('input[type=radio][data-act], input[type=checkbox][data-act]')) ACTIONS[el.dataset.act]?.(el, ev);
  if (el.matches('select[data-bind]')) { setPath(el.dataset.bind, el.value); if (el.dataset.bind.startsWith('fLogs')) S.logPage = 0; render(); }
});
document.addEventListener('input', (ev) => {
  const el = ev.target;
  if (el.matches('input[data-bind]')) { setPath(el.dataset.bind, el.value); if (el.dataset.bind.startsWith('fLogs')) S.logPage = 0; render(); }
  if (el.id === 'm-confirm') document.getElementById('m-ok').disabled = el.value !== el.dataset.expected;
});

let lastRoute = '';
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && S.navOpen) ACTIONS.navclose(); });
window.addEventListener('hashchange', () => {
  const r = route();
  if (r.name === 'maquinas') loadMachines().then(render);
  const key = `${r.name}/${r.arg || ''}/${r.sub || ''}`;
  if (r.name === 'novo-cliente' && S.wiz?.step === 5 && (S.wiz.saved || S.wiz.jobId ? S.data.activity.find((a) => a.id === S.wiz.jobId)?.result !== 'running' : S.wiz.run >= wizLabels(S.wiz).length)) S.wiz = null;
  S.navOpen = false;
  render();
  if (key !== lastRoute) {
    if (r.anchor) document.getElementById(r.anchor)?.scrollIntoView();
    else window.scrollTo(0, 0);
    document.getElementById('main')?.focus({ preventScroll: true });
  }
  lastRoute = key;
});

// Linhas reais vêm do servidor. O que foi simulado nos exemplos fica como está até recarregar.
const LIVE_AREAS = ['apps', 'accounts', 'logs', 'activity', 'diverge'];
let watching = null;
function watchJobs() {
  if (watching) return;
  watching = setInterval(async () => {
    await refreshData(true);
    if (!S.data.activity.some((a) => a.result === 'running')) { clearInterval(watching); watching = null; await refreshData(true); }
  }, 2000);
}
function pollData() { return refreshData(false); }
async function refreshData(always) {
  if ((document.hidden && !always) || !connected() || S.modal) return;
  try {
    const res = await fetch('/api/data');
    if (!res.ok) return;
    const next = await res.json();
    const fingerprint = (d) => JSON.stringify([d.connection.state, d.connection.problems, d.rollout, d.discoveries, LIVE_AREAS.map((a) => d[a].filter((r) => !rowEx(r)))]);
    const before = fingerprint(S.data);
    for (const area of LIVE_AREAS) S.data[area] = [...next[area].filter((r) => !rowEx(r)), ...S.data[area].filter(rowEx)];
    S.data.connection = next.connection;
    S.data.sources = next.sources;
    const known = new Set(next.clients.map((c) => c.id));
    S.data.clients = [...next.clients, ...S.data.clients.filter((c) => !known.has(c.id))];
    for (const [id, rows] of Object.entries(next.rollout)) if (rows.some((p) => !rowEx(p))) S.data.rollout[id] = rows;
    S.data.discoveries = next.discoveries;
    if (S.data.activity.some((a) => a.result === 'running')) watchJobs();
    if (before !== fingerprint(S.data) && !document.activeElement?.matches?.('input, select')) render();
  } catch { /* o aviso de servidor fora do ar vem de pollDevice */ }
}

const stripTime = (d) => JSON.stringify({ ...d, read_at: '' });
async function pollDevice() {
  if (document.hidden) return;
  try {
    const res = await fetch('/api/device');
    if (res.status === 401) { await refreshAuth(); render(); return; }
    if (!res.ok) throw new Error(String(res.status));
    const next = await res.json();
    const changed = !S.device || stripTime(next) !== stripTime(S.device);
    const before = JSON.stringify(S.setup);
    S.setup = next.setup;
    if (before !== JSON.stringify(next.setup)) { await reloadBase(); S.setupError = ''; }
    S.device = next;
    S.failed = false;
    if (S.setup?.layout === 'installed' || remoteOn()) {
      const seen = JSON.stringify(S.machines?.devices);
      await loadMachines();
      if (remoteOn()) { await refreshAuth(); }
      if (seen !== JSON.stringify(S.machines?.devices) && !document.activeElement?.matches?.('input, select')) render();
    }
    if (changed && !S.modal) render();
  } catch {
    S.failed = true;
    if (!S.modal) render();
  }
}

// A conta pode mudar pela tela ou pelo terminal (cplane import): os dados vêm de novo do servidor.
async function reloadBase() {
  const res = await fetch('/api/data');
  S.base = await res.json();
  S.data = structuredClone(S.base);
}

function waitAuth() {
  const timer = setInterval(async () => {
    if (document.hidden) return;
    const before = S.auth.state;
    try { await refreshAuth(); } catch { return; }
    if (before !== S.auth.state) {
      clearInterval(timer);
      if (S.auth.state === 'ok') { location.reload(); return; }
      render();
      waitAuth();
    }
  }, 3000);
}

async function start() {
  applyTheme();
  try {
    await refreshAuth();
    if (S.auth.remote && S.auth.state !== 'ok') { render(); waitAuth(); return; }
    const setup = await fetch('/api/setup');
    S.setup = await setup.json();
    const res = await fetch('/api/data');
    S.base = await res.json();
    const saved = S.base.connection?.state === 'off' && !realView() ? store.get(DEMO_KEY) : null;
    S.data = saved ? { ...JSON.parse(saved), sources: S.base.sources, connection: S.base.connection } : structuredClone(S.base);
    if (['lab', 'local'].includes(S.base.connection?.target)) S.target = S.base.connection.target;
  } catch {
    S.failed = true;
  }
  render();
  await pollDevice();
  const r = route();
  lastRoute = `${r.name}/${r.arg || ''}/${r.sub || ''}`;
  if (r.anchor) document.getElementById(r.anchor)?.scrollIntoView();
  setInterval(pollDevice, POLL_MS);
  setInterval(() => { if (S.setup?.needs_setup && S.setupStep === 'import') pollDevice(); }, 3000);
  setInterval(pollData, POLL_MS * 2);
  for (const gesture of ['pointerdown', 'keydown', 'wheel', 'touchmove', 'hashchange']) window.addEventListener(gesture, noteActivity, { capture: true, passive: true });
}

start();
