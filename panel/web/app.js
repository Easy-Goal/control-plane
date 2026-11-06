// Painel do control plane. Sem build e sem dependências.
// "Sólido" vem de /api/device, lido agora. "Hachurado" vem de /api/data enquanto a área for exemplo.
import { ACCOUNT_STATE, APP_TYPES, CHECKS, GUIDES, GUIDE_KINDS, PROVIDERS, REPLACE, TOOLS, TRACKS, WIZ_PLATFORMS } from './content.js';

const DEMO_KEY = 'cp-panel-demo-v1';
const POLL_MS = 15000;
const KEY_STORE = 'cp-panel-key';

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

const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* sem persistência */ } },
  del(key) { try { localStorage.removeItem(key); } catch { /* sem persistência */ } },
};

const S = {
  device: null, data: null, base: null, failed: false, target: store.get('cp-panel-target') || 'local',
  theme: store.get('cp-panel-theme') || 'auto',
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
const rowEx = (row) => row?.source !== 'live';
const conn = () => S.data?.connection || { state: 'off', problems: [] };
const session = {
  get() { try { return sessionStorage.getItem(KEY_STORE); } catch { return null; } },
  set(v) { try { sessionStorage.setItem(KEY_STORE, v); } catch { /* sem chave, sem ações */ } },
};
if (location.hash.startsWith('#k=')) { session.set(location.hash.slice(3)); history.replaceState(null, '', `${location.pathname}#/quadro`); }
const actionsOn = () => Boolean(conn().actions?.enabled);
const canAct = () => actionsOn() && Boolean(session.get());
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
const copyBlock = (raw, label = 'Copiar comando') => {
  const text = forTarget(raw);
  return h`
  <div class="cmd"><pre tabindex="0"><code>${text}</code></pre>
    <button class="btn btn-small" data-act="copy" data-text="${text}">${label}</button></div>`;
};
const exNote = (text = 'Exemplo. Nada aqui é real nem é executado.') => h`
  <p class="ex-note"><span class="hatch" aria-hidden="true"></span>${text} <a href="#/configurar/real">O que substitui isso</a></p>`;

// ---------- Leitura do device ----------
const visibleChecks = () => (S.device?.checks || []).filter((c) => !c.target || c.target === 'all' || c.target === S.target);
const checkView = (c) => {
  const meta = CHECKS[c.id] || { name: c.id, track: 'maquina', steps: [] };
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
  if (S.target === 'vps') return 'A VPS ainda não foi contratada. Veja como ela vai ficar.';
  const v = vaultCheck();
  if (v?.sealed) return `Cofre selado em ${targetName[S.target].toLowerCase()}. Faça o unseal para operar.`;
  if (v?.state === 'ok') return 'O cofre está aberto nesta máquina. Pode operar.';
  return 'Esta máquina ainda não tem cofre. O painel ensina a configurar.';
}

// ---------- Moldura ----------
function rail(route) {
  const items = [
    ['quadro', 'Quadro', attention().length], ['clientes', 'Clientes'], ['aplicacoes', 'Aplicações'], ['logs', 'Logs'], ['atividade', 'Atividade'],
  ];
  const config = [['configurar', 'Configurar', pendingChecks().length], ['contas', 'Contas'], ['guias', 'Guias'], ['ferramentas', 'Ferramentas']];
  const link = ([id, name, n]) => h`<a class="nav-link${route === id ? ' is-on' : ''}" href="#/${id}"${route === id ? h` aria-current="page"` : ''}>${name}${n ? h`<span class="count">${n}</span>` : ''}</a>`;
  const v = vaultCheck();
  return h`
  <aside class="rail">
    <a class="brand" href="#/quadro">Control Plane</a>
    <a class="btn btn-rail" href="#/novo-cliente">Novo cliente</a>
    <nav aria-label="Operar"><p class="rail-title">Operar</p>${items.map(link)}</nav>
    <nav aria-label="Preparar"><p class="rail-title">Preparar</p>${config.map(link)}</nav>
    <section class="rail-device" aria-label="Esta máquina">
      <p class="rail-title">Esta máquina</p>
      ${TRACKS.filter((t) => t.id !== 'maquina').map((t) => { const [k, l] = SOLID[trackState(t.id)]; return h`<a class="rail-track" href="#/configurar/maquina#${t.id}" title="${t.name}: ${l}">${mark(k, t.name)}</a>`; })}
    </section>
    <div class="rail-foot">
      <a class="btn btn-ghost" href="${v?.state === 'ok' || v?.sealed ? v.url : '#/ferramentas'}"${v?.state === 'ok' || v?.sealed ? h` target="_blank" rel="noopener"` : ''}>Abrir o cofre</a>
      <button class="link-btn" data-act="theme">Tema: ${{ auto: 'automático', light: 'claro', dark: 'escuro' }[S.theme]}</button>
    </div>
  </aside>`;
}

// ---------- Conexão com o cofre ----------
const actionHint = () => (actionsOn() ? 'abra o link que o terminal mostrou.' : 'abra com scripts/cp-lab cp-panel --acoes.');
const hhmm = (iso) => (iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '');
function connBar() {
  const c = conn();
  if (c.state === 'off') return '';
  if (c.state === 'connected') {
    return h`<div class="conn" role="status"><p><b>Conectado ${where().a}.</b> Leitura das ${hhmm(c.read_at)}. A sessão vence às ${hhmm(c.expires_at)}.</p>
      ${actionsOn() && (canAct()
        ? h`<p class="conn-problem"><b>Ações ligadas.</b> Os botões das linhas sólidas executam de verdade no laboratório.</p>`
        : h`<p class="conn-problem"><b>Ações ligadas, mas este navegador não tem a chave.</b> Abra o link que o terminal mostrou.</p>`)}
      ${(c.problems || []).map((p) => h`<p class="conn-problem"><b>${p.area}:</b> ${p.text} ${p.next}</p>`)}</div>`;
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
    <details class="fold"><summary>Como conectar ao laboratório</summary>
      <ol class="steps"><li>O cofre do laboratório precisa estar aberto e esta máquina precisa ter a credencial de operador.</li><li>Grave uma vez as credenciais só de leitura: o token do Coolify e as contas de logs.</li><li>Abra o painel pelo laboratório. Ele cria uma sessão de 1 h e a encerra ao fechar.</li></ol>
      ${copyBlock(`docker exec -i cp-sim-sim-cp-1 bash -s < install/coolify-read-token.sh | scripts/cp-lab cp-secrets provider set easygoal coolify-sim-read url=http://127.0.0.1:8000 --stdin token --expires "$(date -u -d '+90 days' +%F)"\nCP_OBS_PROVIDER=openobserve-sim scripts/cp-lab cp-obs panel-read\nscripts/cp-lab cp-panel          # só leitura\nscripts/cp-lab cp-panel --acoes  # também age no laboratório: abra o link que o terminal mostrar`)}</details></section>`;
}

// ---------- Quadro ----------
function attention() {
  if (!S.data) return [];
  const out = [];
  for (const a of S.data.apps) {
    for (const [env, e] of Object.entries(a.envs)) {
      if (e.state === 'degraded') out.push({ ex: rowEx(a), kind: 'err', label: 'Com problema', title: `${a.name} em ${env}`, sub: `${clientName(a.client)}. ${e.health}.`, next: 'Ver os logs filtrados.', to: `#/aplicacoes/${a.id}` });
      if (e.state === 'unread') out.push({ ex: false, kind: 'off', label: 'Não lido', title: `${a.name} em ${env}`, sub: e.health, next: 'Veja a conexão em Configurar.', to: '#/configurar/maquina#conexao' });
      if (e.backupFailed) out.push({ ex: rowEx(a), kind: 'err', label: 'Backup', title: `${a.name} em ${env}`, sub: `${clientName(a.client)}. ${e.backup}.`, next: rowEx(a) ? 'Fazer um backup agora.' : 'Confira o destino do backup no Coolify.', to: `#/aplicacoes/${a.id}` });
    }
  }
  for (const c of S.data.accounts) {
    if (['expired', 'missing', 'soon'].includes(c.state)) {
      const [k, l] = ACCOUNT_STATE[c.state];
      out.push({ ex: rowEx(c), kind: k, label: l, title: `${PROVIDERS[c.provider].name} de ${clientName(c.client)}`, sub: c.expires + '.', next: c.state === 'soon' ? 'Crie um token novo e troque antes de vencer.' : 'Crie o token na conta do cliente e grave no cofre.', to: `#/contas/${c.id}` });
    }
  }
  for (const d of S.data.diverge) out.push({ ex: true, kind: 'warn', label: 'Divergente', title: d.target, sub: `${clientName(d.client)}. O cofre e o destino têm valores diferentes.`, next: 'Decidir qual valor vence.', to: `#/clientes/${d.client}` });
  return out.sort((a, b) => Number(a.ex) - Number(b.ex)); // o que é real vem antes do exemplo
}

function rolloutText(id) {
  const list = (S.data.rollout[id] || []).filter((p) => p.state !== 'na');
  return `${list.filter((p) => p.state === 'ok').length} de ${list.length} etapas`;
}

const versionCell = (env, ex, strong, behind) => {
  if (!env) return h`<td class="cell-none"><span class="sr">Sem este ambiente</span></td>`;
  const [k, l] = ENV_STATE[env.state];
  return h`<td class="cell-version${strong ? ' is-prod' : ''}"><span class="sig sig-${k}${ex ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span><span>${env.version}</span>${behind && h`<span class="behind">Atrás de ${behind}</span>`}${env.moving && h`<span class="behind" title="A tag pode apontar para outra imagem amanhã">Tag móvel</span>`}</td>`;
};

function board() {
  const cols = [['conta', 'Conta'], ['segredos', 'Segredos'], ['host', 'Hospedagem'], ['logs', 'Logs']];
  return h`
  <section class="board-wrap" aria-labelledby="board-title">
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
    <p class="legend"><span>${mark('ok', 'Feito')}</span><span>${mark('warn', 'Falta')}</span><span>${mark('err', 'Com problema')}</span><span>${mark('off', 'Não usa')}</span></p>
  </section>`;
}

function viewQuadro() {
  const pending = pendingChecks();
  const list = attention();
  return h`
  ${connBar()}
  <header class="hero">
    <h1>${headline()}</h1>
    <p class="key"><span class="key-item"><span class="solid" aria-hidden="true"></span>Sólido: ${connected() ? `lido agora nesta máquina e ${where().em}` : 'lido agora nesta máquina'}</span><span class="key-item"><span class="hatch" aria-hidden="true"></span>Hachurado: exemplo, até o go-live trocar pelo dado real</span></p>
  </header>
  <div class="two">
    <section aria-labelledby="att-title">
      <div class="sec-head"><h2 id="att-title">Precisa de atenção</h2>${areaNote('apps')}</div>
      <ul class="rows is-ex-list">
        ${list.slice(0, 6).map((a) => h`<li><a class="row-link" href="${a.to}">${mark(a.kind, a.label, a.ex)}<span class="row-main"><b>${a.title}</b><span class="muted">${a.sub}</span><span class="next">${a.next}</span></span></a></li>`)}
        ${list.length > 6 && h`<li class="row-more">${list.length === 7 ? 'Mais 1 item' : `Mais ${list.length - 6} itens`} nas telas de contas e clientes.</li>`}
        ${!list.length && h`<li class="row-empty">Nada pendente.</li>`}
      </ul>
    </section>
    <section aria-labelledby="dev-title">
      <div class="sec-head"><h2 id="dev-title">O que falta nesta máquina</h2></div>
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
function viewClientes(id) {
  const c = S.data.clients.find((x) => x.id === id) || S.data.clients[0];
  const rollout = S.data.rollout[c.id] || [];
  const realClient = rollout.some((p) => !rowEx(p));
  const found = S.data.discoveries?.[c.id] || [];
  const diverge = S.data.diverge.filter((d) => d.client === c.id);
  return h`
  <header class="head-row"><div><h1>Clientes</h1><p class="lede">Cada cliente tem contas e tokens próprios. Aqui fica o que falta para ele estar completo.</p></div><a class="btn btn-pri" href="#/novo-cliente">Novo cliente</a></header>
  ${realClient ? h`<p class="muted">Implantação lida agora ${where().de}. Exemplos continuam hachurados.</p>` : exNote('A implantação deste cliente é exemplo.')}
  <nav class="tabs" aria-label="Escolher cliente">${S.data.clients.map((x) => h`<a class="tab${x.id === c.id ? ' is-on' : ''}" href="#/clientes/${x.id}"${x.id === c.id ? h` aria-current="page"` : ''}>${x.name}</a>`)}</nav>
  <p class="lede"><b>Onde roda:</b> ${c.hosting}.</p>
  <div class="two">
    <section aria-labelledby="ro-title"><div class="sec-head"><h2 id="ro-title">Implantação: ${rolloutText(c.id)}</h2></div>
      ${realClient && canAct() && c.id !== 'easygoal' && h`<div class="btns">${realBtn('Terminar a preparação', { action: 'client_prepare', label: `Terminar a preparação de ${c.name}`, client: c.id })}</div>`}
      <ol class="checklist">${rollout.map((p) => { const [k, l] = READY[p.state]; return h`<li>${mark(k, l, rowEx(p))}<span class="row-main"><b>${p.title}</b>${p.hint && (p.state === 'todo' || !rowEx(p)) && h`<span class="${p.state === 'todo' ? 'next' : 'muted'}">${p.hint}</span>`}${p.state === 'todo' && p.cmd && copyBlock(p.cmd)}${p.state === 'todo' && p.to && h`<a class="inline-link" href="${p.to}">${p.toLabel}</a>`}${p.state === 'todo' && p.real && canAct() && realBtn(p.real.button, p.real)}${p.state === 'todo' && p.action === 'prod' && h`<button class="btn btn-small" data-act="ask" data-verb="Levar para prod os projetos de" data-name="${c.id}" data-env="prod" data-client="${c.id}" data-kind="prod">Levar para prod</button>`}</span></li>`; })}</ol>
    </section>
    <section aria-labelledby="ac-title"><div class="sec-head"><h2 id="ac-title">Contas deste cliente</h2></div>
      <ul class="rows">${accountsOf(c.id).map((a) => { const [k, l] = ACCOUNT_STATE[a.state]; return h`<li><a class="row-link" href="#/contas/${a.id}">${mark(k, l, rowEx(a))}<span class="row-main"><b>${PROVIDERS[a.provider].name}</b><span class="muted">${a.label}. ${a.expires}.</span></span></a></li>`; })}</ul>
      ${canAct() && (S.data.connection.plans || []).includes(c.id) && !diverge.some((d) => !rowEx(d)) && h`<div class="sec-head sec-next"><h2>Destinos divergentes</h2></div>${mark('ok', 'Nenhuma divergência na última conferência')}`}
      ${canAct() && realClient && h`<div class="btns sec-next">${realBtn('Conferir diferenças', { action: 'sync_plan', label: `Conferir diferenças de ${c.name}`, client: c.id })}${realBtn('Buscar projetos', { action: 'discover', label: `Buscar projetos nas contas de ${c.name}`, client: c.id })}</div>`}
      ${found.length > 0 && h`<div class="sec-head sec-next"><h2>O que as contas enxergam</h2></div><ul class="rows">${found.map((f) => h`<li class="row-plain"><span class="row-main"><b>${f.name}</b><span class="muted">${f.provider}. <code>${f.id}</code></span></span></li>`)}</ul>`}
      ${diverge.length > 0 && h`<div class="sec-head sec-next"><h2>Destinos divergentes</h2></div>
      ${diverge.map((d) => h`<div class="panel"><p><b>${d.target}</b></p><p class="muted">Chaves, só os nomes: ${d.keys.join(', ')}. Decida qual valor vence.</p>
        <div class="btns">${!rowEx(d) && canAct() ? realBtn('Levar o valor do cofre', { action: 'sync_apply', label: `Levar o valor do cofre para ${d.targetId}`, client: d.client, target: d.targetId, env: d.env, confirm: d.env === 'prod' ? d.targetId : '' }, 'btn') : h`<button class="btn" data-act="ask" data-verb="Levar o valor do cofre para" data-name="${d.target}" data-env="prod" data-diverge="${d.id}">Levar o valor do cofre</button>`}<a class="btn btn-ghost" href="#/ferramentas">O do destino é o certo: gravar no cofre</a></div></div>`)}`}
    </section>
  </div>
  <section aria-labelledby="ap-title"><div class="sec-head"><h2 id="ap-title">Aplicações</h2></div>${appList(S.data.apps.filter((a) => a.client === c.id))}</section>
  ${c.id !== 'easygoal' && h`<div><button class="btn btn-danger" data-act="offboard" data-client="${c.id}">Encerrar este cliente</button></div>`}`;
}

// ---------- Aplicações ----------
function appList(apps) {
  if (!apps.length) return h`<p class="row-empty">Nenhuma aplicação com esses filtros.</p>`;
  return h`<ul class="rows">${apps.map((a) => {
    const prod = a.envs.prod || Object.values(a.envs)[0];
    const [k, l] = ENV_STATE[prod.state];
    return h`<li><a class="row-link" href="#/aplicacoes/${a.id}">${mark(k, l, rowEx(a))}<span class="row-main"><b>${a.name}</b><span class="muted">${clientName(a.client)}. ${typeName(a.type)}.</span></span><span class="row-side"><b>${prod.version}</b><span class="muted">${prod.when}</span></span></a></li>`;
  })}</ul>`;
}

const APP_FILTER_STATE = (a, st) => {
  const envs = Object.values(a.envs);
  if (st === 'problem') return envs.some((e) => e.state === 'degraded' || e.state === 'unread' || e.backupFailed);
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
  return h`<article class="panel env${name === 'prod' ? ' env-prod' : ''}">
    <header class="env-head"><h3>${name === 'prod' ? 'Em produção' : name}</h3>${mark(k, l, ex)}</header>
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
      <a class="btn btn-small" href="#/logs" data-act="seelogs" data-client="${a.client}" data-env="${name}" data-q="${a.name}">Ver logs</a>
      ${ex && coolify && h`<button class="btn btn-small" data-act="ask" data-verb="Reiniciar" data-name="${a.name}" data-env="${name}">Reiniciar</button>`}
      ${ex && coolify && a.type !== 'db-coolify' && h`<button class="btn btn-small" data-act="ask" data-verb="Fazer deploy de" data-name="${a.name}" data-env="${name}">Fazer deploy</button>`}
      ${!ex && canAct() && e.state !== 'unread' && a.type.endsWith('coolify') && realBtn('Reiniciar', { action: 'restart', label: `Reiniciar ${a.name} em ${name}`, client: a.client, app: a.id, env: name, confirm: name === 'prod' ? a.name : '' })}
      ${!ex && canAct() && name === 'prod' && previousEnv(a)?.tag && previousEnv(a).tag !== e.tag && realBtn(`Promover ${previousEnv(a).tag}`, { action: 'promote', label: `Promover ${a.name} para ${previousEnv(a).tag} em prod`, client: a.client, app: a.id, env: 'prod', confirm: a.name })}
      ${!ex && canAct() && e.state !== 'unread' && a.type === 'api-coolify' && realBtn('Fazer deploy', { action: 'deploy', label: `Fazer deploy de ${a.name} em ${name}`, client: a.client, app: a.id, env: name, confirm: name === 'prod' ? a.name : '' })}
      ${!ex && canAct() && a.type === 'db-coolify' && realBtn('Fazer backup', { action: 'backup', label: `Fazer backup de ${a.name} em ${name}`, client: a.client, app: a.id, env: name })}
      ${!ex && canAct() && e.target && realBtn('Levar os segredos', { action: 'sync_apply', label: `Levar os segredos para ${e.target}`, client: a.client, target: e.target, confirm: name === 'prod' ? e.target : '', env: name })}
      ${ex && e.backupFailed && h`<button class="btn btn-small" data-act="ask" data-verb="Fazer backup de" data-name="${a.name}" data-env="${name}" data-backup="${a.id}">Fazer backup</button>`}
      ${pl.url ? h`<a class="btn btn-small btn-ghost" href="${pl.url}" target="_blank" rel="noopener">${pl.label}</a>` : h`<a class="btn btn-small btn-ghost" href="#/ferramentas">${pl.label}</a>`}
    </div>
  </article>`;
}

function viewAplicacoes(id) {
  const app = id && S.data.apps.find((a) => a.id === id);
  if (app) {
    const order = ['prod', 'staging', 'dev'].filter((n) => app.envs[n]);
    return h`
    <p class="crumb"><a href="#/aplicacoes">Aplicações</a></p>
    <header class="head"><h1>${app.name}</h1><p class="lede">${clientName(app.client)}. ${typeName(app.type)}: ${APP_TYPES[app.type]?.when}</p></header>
    ${rowEx(app) ? exNote() : h`<p class="muted">Lido agora ${where().de}.${canAct() ? ' Os botões abaixo executam de verdade.' : ` Para agir pelo painel: ${actionHint()}`}</p>`}
    <div class="envs">${order.map((n) => envPanel(app, n, app.envs[n]))}</div>
    ${!app.type.endsWith('coolify') && h`<p class="muted">Esta plataforma cuida do próprio container. O painel mostra versão e estado e leva até lá.</p>`}`;
  }
  const f = S.fApps;
  const q = f.q.trim().toLowerCase();
  const apps = S.data.apps.filter((a) => (!f.client || a.client === f.client) && (!f.type || a.type === f.type) && APP_FILTER_STATE(a, f.state) && (!q || a.name.includes(q)));
  const containers = S.device?.containers || [];
  return h`
  <header class="head"><h1>Aplicações</h1><p class="lede">Versão, estado e deploy de cada aplicação, por cliente e por tipo.</p></header>
  ${containers.length > 0 && h`<section aria-labelledby="ct-title"><div class="sec-head"><h2 id="ct-title">Containers nesta máquina</h2><p class="muted">Lido agora do Docker: ${containers.length}.</p></div>
    <details class="fold"><summary>Ver os containers</summary><ul class="rows">${containers.map((c) => h`<li class="row-plain">${mark(c.state === 'running' ? 'ok' : 'off', c.state === 'running' ? 'Rodando' : 'Parado')}<span class="row-main"><b>${c.names}</b><span class="muted">${c.status}</span></span></li>`)}</ul></details></section>`}
  <section aria-labelledby="al-title"><div class="sec-head"><h2 id="al-title">Todas as aplicações</h2>${areaNote('apps')}</div>
  <div class="filters">
    ${select('f-client', 'Cliente', 'fApps.client', f.client, [['', 'Todos'], ...S.data.clients.map((c) => [c.id, c.name])])}
    ${select('f-type', 'Tipo', 'fApps.type', f.type, [['', 'Todos'], ...Object.entries(APP_TYPES).map(([k, v]) => [k, v.name])])}
    ${select('f-state', 'Situação', 'fApps.state', f.state, [['', 'Todas'], ['problem', 'Com problema'], ['behind', 'Produção atrás do ambiente anterior']])}
    <label class="fld fld-grow" for="f-q">Buscar<input id="f-q" type="search" data-bind="fApps.q" value="${f.q}" placeholder="Nome da aplicação"></label>
  </div>
  ${appList(apps)}</section>`;
}

function select(id, label, bind, value, opts) {
  return h`<label class="fld" for="${id}">${label}<select id="${id}" data-bind="${bind}">${opts.map(([v, n]) => h`<option value="${v}"${v === value ? h` selected` : ''}>${n}</option>`)}</select></label>`;
}

// ---------- Logs ----------
function viewLogs() {
  const f = S.fLogs;
  const q = f.q.trim().toLowerCase();
  const rows = S.data.logs.filter((l) => (!f.client || l.client === f.client) && (!f.env || l.env === f.env) && (!f.level || l.level === f.level) && (!q || `${l.app} ${l.event} ${l.route}`.toLowerCase().includes(q)));
  const lv = { info: 'off', warn: 'warn', error: 'err' };
  return h`
  <header class="head"><h1>Logs</h1><p class="lede">Vêm já filtrados pela allowlist, sem mensagem de erro e sem dado sensível. Para o log bruto, o caminho é o Coolify.</p></header>
  ${connBar()}
  ${areaNote('logs')}
  <div class="filters">
    ${select('l-client', 'Cliente', 'fLogs.client', f.client, [['', 'Todos'], ...S.data.clients.map((c) => [c.id, c.name])])}
    ${select('l-env', 'Ambiente', 'fLogs.env', f.env, [['', 'Todos'], ['dev', 'dev'], ['staging', 'staging'], ['prod', 'prod']])}
    ${select('l-level', 'Nível', 'fLogs.level', f.level, [['', 'Todos'], ['info', 'info'], ['warn', 'warn'], ['error', 'error']])}
    <label class="fld fld-grow" for="l-q">Buscar<input id="l-q" type="search" data-bind="fLogs.q" value="${f.q}" placeholder="Aplicação, evento ou rota"></label>
    <button class="btn" data-act="clearlogs">Limpar filtros</button>
  </div>
  <p class="muted" role="status">${rows.length === 1 ? '1 registro' : `${rows.length} registros`}</p>
  <ul class="rows logs">
    ${rows.map((l) => h`<li><button class="row-link" data-act="openlog" data-id="${l.id}" aria-expanded="${S.openLog === l.id}">
      ${mark(lv[l.level], l.level, rowEx(l))}<span class="row-main"><b><code>${l.event}</code> ${l.route}</b><span class="muted">${clientName(l.client)}, ${l.app}, ${l.env}</span></span><span class="row-side"><b>${l.status || 'Sem status'}</b><span class="muted">${l.time}</span></span></button>
      ${S.openLog === l.id && h`<div class="row-detail"><dl class="facts"><div><dt>Duração</dt><dd>${l.ms === '' ? 'Não informada' : `${l.ms} ms`}</dd></div>${l.rid && h`<div><dt>Request</dt><dd><code>${l.rid}</code></dd></div>`}<div><dt>Marcação de segurança</dt><dd>${l.flag || 'Nenhuma'}</dd></div></dl><p class="muted">A mensagem de erro não vem para cá, porque pode trazer valores. Para investigar, procure este horário e esta rota no log bruto do Coolify.</p></div>`}</li>`)}
    ${!rows.length && h`<li class="row-empty">Nenhum log com esses filtros. <button class="link-btn" data-act="clearlogs">Limpar filtros</button></li>`}
  </ul>`;
}

// ---------- Atividade ----------
function viewAtividade() {
  const res = { ok: ['ok', 'Sucesso'], err: ['err', 'Falhou'], sim: ['off', 'Simulado'], running: ['warn', 'Em andamento'] };
  return h`
  <header class="head"><h1>Atividade</h1><p class="lede">O que foi feito pelo painel e o resultado de cada etapa. Quem leu qual segredo fica no audit do cofre.</p></header>
  ${actionsOn() ? exNote('Linhas sólidas são ações reais no laboratório. As hachuradas são exemplos e simulações.') : exNote('Exemplo. As ações que você simular neste painel entram aqui.')}
  <ul class="rows">
    ${S.data.activity.map((a) => h`<li><button class="row-link" data-act="openact" data-id="${a.id}" aria-expanded="${S.openAct === a.id}">${mark(res[a.result][0], res[a.result][1], rowEx(a))}<span class="row-main"><b>${a.action}</b><span class="muted">${a.who}, ${a.where}</span></span><span class="row-side muted">${a.time || hhmm(a.at)}</span></button>
      ${S.openAct === a.id && h`<div class="row-detail">${a.steps.length ? h`<ol class="steps">${a.steps.map((s) => h`<li>${s}</li>`)}</ol>` : h`<p class="muted">Aguardando a primeira saída.</p>`}</div>`}</li>`)}
  </ul>
  <div><button class="link-btn" data-act="resetdemo">Voltar os exemplos ao início</button></div>`;
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
      ${url ? h`<a class="btn" href="${url}" target="_blank" rel="noopener">${p.urlLabel}</a>` : p.toolCheck && h`<p class="muted">O Coolify ainda não está no ar nesta máquina. <a href="#/configurar/maquina#containers">Veja como subir</a>.</p>`}
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
  const selected = S.data.accounts.find((a) => a.id === id) || S.data.accounts.find((a) => ['expired', 'missing', 'soon'].includes(a.state)) || S.data.accounts[0];
  return h`
  <header class="head-row"><div><h1>Contas</h1><p class="lede">Cada plataforma de cada cliente é uma conta separada, com login e token próprios. Escolha uma para ver o que ela atende e o que falta.</p></div><button class="btn btn-pri" data-act="newacc">Conectar conta</button></header>
  ${connBar()}
  ${areaNote('accounts')}
  <div class="master">
    <nav class="master-list" aria-label="Contas por cliente">
      ${S.data.clients.map((c) => h`<div class="master-group"><h2>${c.name}</h2>
        ${accountsOf(c.id).map((a) => { const [k, l] = ACCOUNT_STATE[a.state]; return h`<a class="master-item${a.id === selected?.id ? ' is-on' : ''}" href="#/contas/${a.id}"${a.id === selected?.id ? h` aria-current="true"` : ''}><span class="sig sig-${k}${rowEx(a) ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span><span class="master-text"><b>${PROVIDERS[a.provider].name}</b><span class="muted">${a.expires}</span></span></a>`; })}
        ${!accountsOf(c.id).length && h`<p class="muted">Nenhuma conta ainda.</p>`}</div>`)}
    </nav>
    ${selected && accountDetail(selected)}
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
      <p class="btns">${c.guide && h`<a class="inline-link" href="#/guias/${c.guide}">Abrir o guia completo</a>`}${c.doc && h`<span class="muted">Mais em <code>${c.doc}</code>.</span>`}</p></details>`}
  </li>`;
}

function tabMaquina() {
  const d = S.device;
  if (!d) return h`<p class="muted" role="status">Lendo esta máquina.</p>`;
  const rows = visibleChecks().map(checkView);
  const desired = d.desired;
  return h`
  <p class="lede">O painel funciona mesmo que falte tudo abaixo. Esta lista mostra o que este device tem e o que fazer se ele for operar também.</p>
  <fieldset class="segmented"><legend>Ver como</legend>
    ${['local', 'lab', 'vps'].map((t) => h`<label class="${S.target === t ? 'is-on' : ''}"><input type="radio" name="target" value="${t}" data-act="target"${S.target === t ? h` checked` : ''}>${targetName[t]}</label>`)}
  </fieldset>
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

function viewConfigurar(tab) {
  const tabs = [['maquina', 'Esta máquina'], ['tipos', 'Por tipo de aplicação'], ['real', 'Do exemplo ao real']];
  const cur = tabs.some(([t]) => t === tab) ? tab : 'maquina';
  return h`
  <header class="head"><h1>Configurar</h1></header>
  <nav class="tabs" aria-label="Seções de configuração">${tabs.map(([t, n]) => h`<a class="tab${t === cur ? ' is-on' : ''}" href="#/configurar/${t}"${t === cur ? h` aria-current="page"` : ''}>${n}</a>`)}</nav>
  ${cur === 'maquina' ? tabMaquina() : cur === 'tipos' ? tabTipos() : tabReal()}`;
}

// ---------- Guias ----------
function viewGuias(id) {
  const q = S.gQuery.trim().toLowerCase();
  const rows = GUIDES.filter((g) => (S.gKind === 'all' || g.k === S.gKind) && (!q || `${g.title} ${g.when} ${g.steps.join(' ')}`.toLowerCase().includes(q)));
  const open = id && GUIDES.find((g) => g.id === id);
  return h`
  <header class="head"><h1>Guias</h1><p class="lede">O que fazer em cada situação, onde fazer e o comando equivalente no terminal.</p></header>
  <div class="filters"><div class="tabs" role="group" aria-label="Filtrar por tipo">${GUIDE_KINDS.map(([k, n]) => h`<button class="tab${S.gKind === k ? ' is-on' : ''}" data-act="gkind" data-k="${k}" aria-pressed="${S.gKind === k}">${n}</button>`)}</div>
  <label class="fld fld-grow" for="g-q">Buscar situação<input id="g-q" type="search" data-bind="gQuery" value="${S.gQuery}" placeholder="Vazou, reiniciar, logs, Neon"></label></div>
  <ul class="rows guides">
    ${rows.map((g) => { const on = open?.id === g.id; return h`<li id="guia-${g.id}"><a class="row-link" href="#/guias${on ? '' : `/${g.id}`}" aria-expanded="${on}"><span class="row-main"><b>${g.title}</b><span class="muted">${g.when}</span></span><span class="row-side muted">${g.where}</span></a>
      ${on && h`<div class="row-detail"><ol class="steps">${g.steps.map((s) => h`<li>${s}</li>`)}</ol>
        ${g.warn && h`<p class="caution"><b>Cuidado:</b> ${g.warn}</p>`}
        ${copyBlock(g.cmd)}
        <div class="btns">${g.to && h`<a class="btn btn-pri" href="${g.to}">${g.goLabel}</a>`}${g.link && h`<a class="btn" href="${g.link}" target="_blank" rel="noopener">${g.linkLabel}</a>`}</div></div>`}</li>`; })}
    ${!rows.length && h`<li class="row-empty">Nenhum guia para essa busca.</li>`}
  </ul>`;
}

// ---------- Ferramentas ----------
function viewFerramentas() {
  const all = S.device?.checks || [];
  return h`
  <header class="head"><h1>Ferramentas</h1><p class="lede">Cada uma mantém o próprio login. O painel diz para que ir até lá e leva à ferramenta quando ela está no ar nesta máquina.</p></header>
  <ul class="tools">${TOOLS.map((t) => {
    const ids = t.checks[S.target];
    const c = ids && all.find((x) => x.id === ids);
    const up = c && (c.state === 'ok' || c.sealed);
    const url = t.id === 'cofre' ? c?.url : (t.baseBy?.[S.target] || t.base);
    return h`<li class="tool${t.id === 'cofre' ? ' tool-vault' : ''}"><div class="tool-main"><h2>${t.name}</h2><p>${t.purpose}</p><p><b>Vá até lá para:</b> ${t.goFor}</p><p><b>Login:</b> ${t.login}</p></div>
      <div class="tool-side">${c ? mark(up ? (c.sealed ? 'warn' : 'ok') : 'off', up ? (c.sealed ? 'Selado' : 'No ar') : 'Não está aqui') : mark('off', `Sem ${t.name} em ${targetName[S.target].toLowerCase()}`)}
        ${up ? h`<a class="btn" href="${url}" target="_blank" rel="noopener">Abrir</a>` : h`<a class="inline-link" href="#/configurar/maquina">Como configurar</a>`}</div></li>`;
  })}</ul>`;
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
const wizLabels = (w) => [
  'Snapshot do cofre', 'Gravar o arquivo do cliente', 'Criar policies e identidades', 'Gerar os segredos internos',
  ...(w.logs ? ['Ligar os logs'] : []),
];
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
    <header class="head"><h1>Novo cliente</h1><p class="lede">Do contrato até o cliente pronto para receber as contas. Depois, o checklist dele mostra o que falta, passo a passo.</p></header>
    ${real ? h`<div class="info">Isto cria o cliente de verdade no laboratório: grava <code>openbao/clients/${slug || 'cliente'}.toml</code> e prepara o cofre. Nenhum token passa por esta tela.</div>` : exNote('Simulação: nada é gravado. Para criar de verdade no laboratório, abra com scripts/cp-lab cp-panel --acoes.')}
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

    ${w.step === 5 && (w.jobId ? h`<section class="panel"><h2>${job?.result === 'ok' ? 'Cliente preparado' : job?.result === 'err' ? 'A preparação parou' : 'Preparando o cliente'}</h2>
        <div class="row-detail"><ol class="steps" role="status">${(job?.steps || []).map((s) => h`<li>${s}</li>`)}</ol></div>
        ${job?.result === 'err' && h`<p class="caution">O arquivo do cliente já foi gravado. Abra o cliente e use Terminar a preparação depois de corrigir: o que já foi feito não se repete.</p>`}</section>
        ${job && job.result !== 'running' && h`<div><a class="btn btn-pri" href="#/clientes/${w.slugDone}">Abrir o cliente</a></div>`}`
    : h`<section class="panel"><h2>${simDone ? 'Simulação concluída' : 'Simulando a preparação'}</h2>
      <ul class="rows" role="status">${labels.map((l, i) => { const st = i < w.run ? ['ok', 'Feito'] : i === w.run ? ['warn', 'Rodando'] : ['off', 'Na fila']; return h`<li class="row-plain">${mark(st[0], st[1], true)}<span class="row-main">${l}</span></li>`; })}</ul></section>
      ${done && h`<div class="info"><b>${w.name.trim()} entrou nas telas como exemplo.</b> Nada foi gravado no cofre nem no repositório.</div>
      <div><a class="btn btn-pri" href="#/clientes/${slug}">Abrir o cliente</a></div>`}`)}

    ${w.step < 5 && h`<footer class="wiz-nav"><a class="btn btn-ghost" href="#/clientes" data-act="wcancel">Cancelar</a>
      <span class="btns">${w.step > 1 && h`<button class="btn" data-act="wback">Voltar</button>`}<button class="btn btn-pri" data-act="wnext" data-block="${block}"${block ? h` disabled` : ''}>${w.step === 4 ? (real ? 'Criar o cliente' : 'Simular') : 'Continuar'}</button></span></footer>
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
function modalView() {
  const m = S.modal;
  if (!m) return '';
  if (m.type === 'real') {
    return h`<dialog id="modal" aria-labelledby="m-title"><form method="dialog" class="modal-body">
      <h2 id="m-title">${m.label}</h2>
      <p>Isto executa de verdade no laboratório, em segundo plano. O resultado aparece em Atividade.</p>
      ${m.confirm && h`<label class="fld" for="m-confirm">Em prod, digite <code>${m.confirm}</code> para confirmar<input id="m-confirm" autocomplete="off" data-expected="${m.confirm}"></label>`}
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
      <label class="fld" for="n-client">Cliente<select id="n-client">${S.data.clients.map((c) => h`<option value="${c.id}">${c.name}</option>`)}</select></label>
      <label class="fld" for="n-prov">Plataforma<select id="n-prov">${Object.entries(PROVIDERS).map(([k, p]) => h`<option value="${k}">${p.name}</option>`)}</select></label>
      <div class="modal-foot"><button class="btn" type="button" data-act="closemodal">Cancelar</button><button class="btn btn-pri" type="button" data-act="confirmnewacc">Ver o passo a passo</button></div>
    </form></dialog>`;
  }
  if (m.type === 'offboard') {
    return h`<dialog id="modal" aria-labelledby="m-title"><form method="dialog" class="modal-body">
      <h2 id="m-title">Encerrar ${clientName(m.client)}</h2>
      <p class="muted">Exporta os segredos para o Bitwarden do cliente e tira o acesso da Easy Goal. Os containers continuam rodando na VPS dele.</p>
      <h3>O painel fará</h3><ol class="steps"><li>Snapshot do cofre.</li><li>Export dos segredos do cliente.</li><li>Revogação dos tokens que a plataforma permite.</li><li>Remoção das identidades e dos caminhos dele no cofre.</li></ol>
      <h3>Você faz depois</h3><ol class="steps"><li>Importa o export no Bitwarden do cliente e apaga o arquivo.</li><li>Remove a chave SSH de cada VPS dele.</li><li>Remove os servidores no Coolify e os nós da tailnet.</li><li>Revoga o token da Railway na plataforma, se houver.</li></ol>
      ${copyBlock(`scripts/cp-secrets backup\nscripts/cp-secrets offboard ${m.client}\nscripts/cp-obs revoke ${m.client}`)}
      <div class="modal-foot"><button class="btn" type="button" data-act="closemodal">Fechar</button></div>
    </form></dialog>`;
  }
  return '';
}

// ---------- Estado de exemplo ----------
function saveDemo() { if (!connected()) store.set(DEMO_KEY, JSON.stringify(S.data)); } // conectado, nada real vai para o navegador guardar
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
  theme() { S.theme = { auto: 'light', light: 'dark', dark: 'auto' }[S.theme]; store.set('cp-panel-theme', S.theme); applyTheme(); render(); },
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
      const res = await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CP-Key': session.get() || '' }, body: JSON.stringify(body) });
      const out = await res.json();
      if (!res.ok) { S.modal = { ...m, error: out.error || 'O painel recusou o pedido.' }; render(); return; }
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
  seelogs(el, ev) { ev.preventDefault(); S.fLogs = { client: el.dataset.client, env: el.dataset.env, level: '', q: el.dataset.q }; S.openLog = null; location.hash = '#/logs'; },
  clearlogs() { S.fLogs = { client: '', env: '', level: '', q: '' }; S.openLog = null; render(); },
  openlog(el) { S.openLog = S.openLog === el.dataset.id ? null : el.dataset.id; render(); },
  openact(el) { S.openAct = S.openAct === el.dataset.id ? null : el.dataset.id; render(); },
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
  newacc() { S.modal = { type: 'newacc' }; render(); },
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
    if (w.step === 4 && canAct()) {
      const res = await fetch('/api/actions', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CP-Key': session.get() || '' }, body: JSON.stringify({ action: 'client_create', spec: wizSpec(w) }) }).catch(() => null);
      const out = res ? await res.json().catch(() => ({})) : {};
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
  return { name: parts[0] || 'quadro', arg: parts[1], anchor: clean[1] };
}

function viewFor(r) {
  switch (r.name) {
    case 'clientes': return viewClientes(r.arg);
    case 'aplicacoes': return viewAplicacoes(r.arg);
    case 'logs': return viewLogs();
    case 'atividade': return viewAtividade();
    case 'configurar': return viewConfigurar(r.arg);
    case 'contas': return viewContas(r.arg);
    case 'guias': return viewGuias(r.arg);
    case 'ferramentas': return viewFerramentas();
    case 'novo-cliente': return viewNovoCliente();
    default: return viewQuadro();
  }
}

function render() {
  const app = document.getElementById('app');
  if (S.failed) {
    app.innerHTML = h`<main class="fatal"><h1>O servidor do painel não respondeu.</h1><p>Rode <code>scripts/cp-panel</code> na pasta do repositório e recarregue esta página.</p></main>`.s;
    return;
  }
  if (!S.data) return;
  const active = document.activeElement;
  const focusId = active?.id;
  const sel = active && 'selectionStart' in active ? [active.selectionStart, active.selectionEnd] : null;
  const r = route();
  const railRoute = r.name === 'novo-cliente' ? 'clientes' : r.name;
  app.innerHTML = h`${rail(railRoute)}<main class="main" id="main" tabindex="-1">${viewFor(r)}</main>${new Raw(ser(modalView()))}<div id="toast" class="toast" role="status"${S.toast ? '' : h` hidden`}>${S.toast}</div>`.s;
  const dlg = document.getElementById('modal');
  if (dlg) { dlg.showModal(); dlg.addEventListener('cancel', () => { S.modal = null; setTimeout(render); }); }
  if (focusId && !dlg) {
    const el = document.getElementById(focusId);
    if (el) { el.focus(); if (sel && el.setSelectionRange) { try { el.setSelectionRange(sel[0], sel[1]); } catch { /* tipo sem seleção */ } } }
  }
}

function setPath(path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  keys.reduce((o, k) => o[k], S)[last] = value;
}

function applyTheme() {
  if (S.theme === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', S.theme);
}

document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el || el.matches('input[type=radio], input[type=checkbox], input:not([type])')) return;
  ACTIONS[el.dataset.act]?.(el, ev);
});
document.addEventListener('change', (ev) => {
  const el = ev.target;
  if (el.matches('input[type=radio][data-act], input[type=checkbox][data-act]')) ACTIONS[el.dataset.act]?.(el, ev);
  if (el.matches('select[data-bind]')) { setPath(el.dataset.bind, el.value); render(); }
});
document.addEventListener('input', (ev) => {
  const el = ev.target;
  if (el.matches('input[data-bind]')) { setPath(el.dataset.bind, el.value); render(); }
  if (el.id === 'm-confirm') document.getElementById('m-ok').disabled = el.value !== el.dataset.expected;
});

let lastRoute = '';
window.addEventListener('hashchange', () => {
  const r = route();
  const key = `${r.name}/${r.arg || ''}`;
  if (r.name === 'novo-cliente' && S.wiz?.step === 5 && (S.wiz.jobId ? S.data.activity.find((a) => a.id === S.wiz.jobId)?.result !== 'running' : S.wiz.run >= wizLabels(S.wiz).length)) S.wiz = null;
  render();
  if (key !== lastRoute) {
    if (r.anchor) document.getElementById(r.anchor)?.scrollIntoView();
    else if (!(r.name === 'guias' && lastRoute.startsWith('guias/'))) window.scrollTo(0, 0);
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
    if (!res.ok) throw new Error(String(res.status));
    const next = await res.json();
    const changed = !S.device || stripTime(next) !== stripTime(S.device);
    S.device = next;
    S.failed = false;
    if (changed && !S.modal) render();
  } catch {
    S.failed = true;
    if (!S.modal) render();
  }
}

async function start() {
  applyTheme();
  try {
    const res = await fetch('/api/data');
    S.base = await res.json();
    const saved = S.base.connection?.state === 'off' ? store.get(DEMO_KEY) : null;
    S.data = saved ? { ...JSON.parse(saved), sources: S.base.sources, connection: S.base.connection } : structuredClone(S.base);
    if (['lab', 'local'].includes(S.base.connection?.target)) S.target = S.base.connection.target;
  } catch {
    S.failed = true;
  }
  render();
  await pollDevice();
  const r = route();
  lastRoute = `${r.name}/${r.arg || ''}`;
  if (r.anchor) document.getElementById(r.anchor)?.scrollIntoView();
  setInterval(pollDevice, POLL_MS);
  setInterval(pollData, POLL_MS * 2);
}

start();
