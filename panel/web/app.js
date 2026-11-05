// Painel do control plane. Sem build e sem dependências.
// "Sólido" vem de /api/device, lido agora. "Hachurado" vem de /api/data enquanto a área for exemplo.
import { ACCOUNT_STATE, APP_TYPES, CHECKS, GUIDES, GUIDE_KINDS, PROVIDERS, REPLACE, TOOLS, TRACKS, WIZ_PLATFORMS } from './content.js';

const DEMO_KEY = 'cp-panel-demo-v1';
const POLL_MS = 15000;

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

const emptyWiz = () => ({ step: 1, name: '', plat: { vercel: true, railway: false, github: false, coolify: true, droplet: false }, done: {}, extra: '', projOff: {}, projExtra: [], logs: true, analytics: true, run: 0 });
const toSlug = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

// ---------- Marcas de estado: forma + cor + texto; hachura = exemplo ----------
const mark = (kind, label, ex = false) => h`<span class="mark mark-${kind}${ex ? ' is-ex' : ''}"><i aria-hidden="true"></i>${label}</span>`;
const SOLID = { ok: ['ok', 'Pronto'], warn: ['warn', 'Atenção'], missing: ['todo', 'Falta'], off: ['off', 'Opcional aqui'] };
const READY = { ok: ['ok', 'Feito'], todo: ['warn', 'Falta'], err: ['err', 'Com problema'], na: ['off', 'Não usa'] };
const ENV_STATE = { running: ['ok', 'Rodando'], degraded: ['err', 'Health falhando'], waiting: ['warn', 'Aguardando'] };
const typeName = (t) => APP_TYPES[t]?.name || t;
const isDemo = (area) => S.data?.sources?.[area] === 'demo';
const clientName = (id) => S.data.clients.find((c) => c.id === id)?.name || id;
const accountsOf = (client) => S.data.accounts.filter((a) => a.client === client);
const targetName = { local: 'Stack local', lab: 'Laboratório', vps: 'VPS' };

const copyBlock = (text, label = 'Copiar comando') => h`
  <div class="cmd"><pre tabindex="0"><code>${text}</code></pre>
    <button class="btn btn-small" data-act="copy" data-text="${text}">${label}</button></div>`;
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

// ---------- Quadro ----------
function attention() {
  if (!S.data) return [];
  const out = [];
  for (const a of S.data.apps) {
    for (const [env, e] of Object.entries(a.envs)) {
      if (e.state === 'degraded') out.push({ kind: 'err', label: 'Fora do ar', title: `${a.name} em ${env}`, sub: `${clientName(a.client)}. ${e.health}.`, next: 'Ver os logs filtrados.', to: `#/aplicacoes/${a.id}` });
      if (e.backupFailed) out.push({ kind: 'err', label: 'Backup', title: `${a.name} em ${env}`, sub: `${clientName(a.client)}. ${e.backup}.`, next: 'Fazer um backup agora.', to: `#/aplicacoes/${a.id}` });
    }
  }
  for (const c of S.data.accounts) {
    if (['expired', 'missing', 'soon'].includes(c.state)) {
      const [k, l] = ACCOUNT_STATE[c.state];
      out.push({ kind: k, label: l, title: `${PROVIDERS[c.provider].name} de ${clientName(c.client)}`, sub: c.expires + '.', next: c.state === 'soon' ? 'Crie um token novo e troque antes de vencer.' : 'Crie o token na conta do cliente e grave no cofre.', to: `#/contas/${c.id}` });
    }
  }
  for (const d of S.data.diverge) out.push({ kind: 'warn', label: 'Divergente', title: d.target, sub: `${clientName(d.client)}. O cofre e o destino têm valores diferentes.`, next: 'Decidir qual valor vence.', to: `#/clientes/${d.client}` });
  return out;
}

function rolloutText(id) {
  const list = (S.data.rollout[id] || []).filter((p) => p.state !== 'na');
  return `${list.filter((p) => p.state === 'ok').length} de ${list.length} etapas`;
}

const versionCell = (env, ex, strong, behind) => {
  if (!env) return h`<td class="cell-none"><span class="sr">Sem este ambiente</span></td>`;
  const [k, l] = ENV_STATE[env.state];
  return h`<td class="cell-version${strong ? ' is-prod' : ''}"><span class="sig sig-${k}${ex ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span><span>${env.version}</span>${behind && h`<span class="behind">Atrás de dev</span>`}</td>`;
};

function board() {
  const ex = isDemo('apps');
  const cols = [['conta', 'Conta'], ['segredos', 'Segredos'], ['host', 'Hospedagem'], ['logs', 'Logs']];
  return h`
  <section class="board-wrap" aria-labelledby="board-title">
    <div class="sec-head"><h2 id="board-title">Quadro de aplicações</h2>${ex && exNote()}</div>
    <div class="scroll" tabindex="0" role="region" aria-labelledby="board-title">
    <table class="board${ex ? ' is-ex-table' : ''}">
      <thead><tr><th scope="col" class="col-name">Aplicação</th>${cols.map(([, n]) => h`<th scope="col" class="col-sig">${n}</th>`)}<th scope="col">Dev</th><th scope="col">Staging</th><th scope="col" class="col-prod">Em produção</th></tr></thead>
      ${S.data.clients.map((c) => h`
      <tbody>
        <tr class="group"><th colspan="8" scope="rowgroup"><a href="#/clientes/${c.id}">${c.name}</a><span class="group-meta">${rolloutText(c.id)}</span></th></tr>
        ${S.data.apps.filter((a) => a.client === c.id).map((a) => {
          const behind = a.envs.dev && a.envs.prod && a.envs.dev.version !== a.envs.prod.version;
          return h`<tr>
            <th scope="row" class="col-name"><a href="#/aplicacoes/${a.id}">${a.name}</a><span class="type">${typeName(a.type)}</span></th>
            ${cols.map(([key]) => { const [k, l] = READY[a.ready[key]]; return h`<td class="col-sig"><span class="sig sig-${k}${ex ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span></td>`; })}
            ${versionCell(a.envs.dev, ex)}${versionCell(a.envs.staging, ex)}
            ${versionCell(a.envs.prod, ex, true, behind)}
          </tr>`;
        })}
      </tbody>`)}
    </table></div>
    <p class="legend"><span>${mark('ok', 'Feito', ex)}</span><span>${mark('warn', 'Falta', ex)}</span><span>${mark('err', 'Com problema', ex)}</span><span>${mark('off', 'Não usa', ex)}</span></p>
  </section>`;
}

function viewQuadro() {
  const pending = pendingChecks();
  const list = attention();
  return h`
  <header class="hero">
    <h1>${headline()}</h1>
    <p class="key"><span class="key-item"><span class="solid" aria-hidden="true"></span>Sólido: lido agora nesta máquina</span><span class="key-item"><span class="hatch" aria-hidden="true"></span>Hachurado: exemplo, até o go-live trocar pelo dado real</span></p>
  </header>
  <div class="two">
    <section aria-labelledby="att-title">
      <div class="sec-head"><h2 id="att-title">Precisa de atenção</h2>${isDemo('apps') && exNote()}</div>
      <ul class="rows is-ex-list">
        ${list.slice(0, 6).map((a) => h`<li><a class="row-link" href="${a.to}">${mark(a.kind, a.label, isDemo('apps'))}<span class="row-main"><b>${a.title}</b><span class="muted">${a.sub}</span><span class="next">${a.next}</span></span></a></li>`)}
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
  const ex = isDemo('clients');
  const rollout = S.data.rollout[c.id] || [];
  const diverge = S.data.diverge.filter((d) => d.client === c.id);
  return h`
  <header class="head-row"><div><h1>Clientes</h1><p class="lede">Cada cliente tem contas e tokens próprios. Aqui fica o que falta para ele estar completo.</p></div><a class="btn btn-pri" href="#/novo-cliente">Novo cliente</a></header>
  ${exNote()}
  <nav class="tabs" aria-label="Escolher cliente">${S.data.clients.map((x) => h`<a class="tab${x.id === c.id ? ' is-on' : ''}" href="#/clientes/${x.id}"${x.id === c.id ? h` aria-current="page"` : ''}>${x.name}</a>`)}</nav>
  <p class="lede"><b>Onde roda:</b> ${c.hosting}.</p>
  <div class="two">
    <section aria-labelledby="ro-title"><div class="sec-head"><h2 id="ro-title">Implantação: ${rolloutText(c.id)}</h2></div>
      <ol class="checklist">${rollout.map((p) => { const [k, l] = READY[p.state]; return h`<li>${mark(k, l, ex)}<span class="row-main"><b>${p.title}</b>${p.state === 'todo' && p.hint && h`<span class="next">${p.hint}</span>`}${p.state === 'todo' && p.to && h`<a class="inline-link" href="${p.to}">${p.toLabel}</a>`}${p.state === 'todo' && p.action === 'prod' && h`<button class="btn btn-small" data-act="ask" data-verb="Levar para prod os projetos de" data-name="${c.id}" data-env="prod" data-client="${c.id}" data-kind="prod">Levar para prod</button>`}</span></li>`; })}</ol>
    </section>
    <section aria-labelledby="ac-title"><div class="sec-head"><h2 id="ac-title">Contas deste cliente</h2></div>
      <ul class="rows">${accountsOf(c.id).map((a) => { const [k, l] = ACCOUNT_STATE[a.state]; return h`<li><a class="row-link" href="#/contas/${a.id}">${mark(k, l, ex)}<span class="row-main"><b>${PROVIDERS[a.provider].name}</b><span class="muted">${a.label}. ${a.expires}.</span></span></a></li>`; })}</ul>
      ${diverge.length > 0 && h`<div class="sec-head sec-next"><h2>Destinos divergentes</h2></div>
      ${diverge.map((d) => h`<div class="panel"><p><b>${d.target}</b></p><p class="muted">Chaves, só os nomes: ${d.keys.join(', ')}. Decida qual valor vence.</p>
        <div class="btns"><button class="btn" data-act="ask" data-verb="Levar o valor do cofre para" data-name="${d.target}" data-env="prod" data-diverge="${d.id}">Levar o valor do cofre</button><a class="btn btn-ghost" href="#/ferramentas">O do destino é o certo: gravar no cofre</a></div></div>`)}`}
    </section>
  </div>
  <section aria-labelledby="ap-title"><div class="sec-head"><h2 id="ap-title">Aplicações</h2></div>${appList(S.data.apps.filter((a) => a.client === c.id))}</section>
  ${c.id !== 'easygoal' && h`<div><button class="btn btn-danger" data-act="offboard" data-client="${c.id}">Encerrar este cliente</button></div>`}`;
}

// ---------- Aplicações ----------
function appList(apps) {
  const ex = isDemo('apps');
  if (!apps.length) return h`<p class="row-empty">Nenhuma aplicação com esses filtros.</p>`;
  return h`<ul class="rows">${apps.map((a) => {
    const prod = a.envs.prod || Object.values(a.envs)[0];
    const [k, l] = ENV_STATE[prod.state];
    return h`<li><a class="row-link" href="#/aplicacoes/${a.id}">${mark(k, l, ex)}<span class="row-main"><b>${a.name}</b><span class="muted">${clientName(a.client)}. ${typeName(a.type)}.</span></span><span class="row-side"><b>${prod.version}</b><span class="muted">${prod.when}</span></span></a></li>`;
  })}</ul>`;
}

const APP_FILTER_STATE = (a, st) => {
  const envs = Object.values(a.envs);
  if (st === 'problem') return envs.some((e) => e.state === 'degraded' || e.backupFailed);
  if (st === 'behind') return a.envs.dev && a.envs.prod && a.envs.dev.version !== a.envs.prod.version;
  return true;
};

function platformLink(a, env) {
  if (a.type === 'front-vercel') return { url: 'https://vercel.com/dashboard', label: 'Abrir na Vercel' };
  if (a.type === 'api-railway') return { url: 'https://railway.com/dashboard', label: 'Abrir na Railway' };
  return { url: null, label: 'Log bruto no Coolify', env };
}

function envPanel(a, name, e) {
  const ex = isDemo('apps');
  const [k, l] = ENV_STATE[e.state];
  const pl = platformLink(a, name);
  const coolify = a.type.endsWith('coolify');
  return h`<article class="panel env${name === 'prod' ? ' env-prod' : ''}">
    <header class="env-head"><h3>${name === 'prod' ? 'Em produção' : name}</h3>${mark(k, l, ex)}</header>
    <p class="env-version">${e.version}</p>
    <dl class="facts">
      ${e.commit && h`<div><dt>Commit</dt><dd><code>${e.commit}</code></dd></div>`}
      <div><dt>Último deploy</dt><dd>${e.when}</dd></div>
      <div><dt>Onde roda</dt><dd>${e.where}</dd></div>
      ${e.health && h`<div><dt>Health check</dt><dd>${e.health}</dd></div>`}
      ${e.backup && h`<div><dt>Backup</dt><dd>${e.backup}</dd></div>`}
    </dl>
    ${e.next && h`<p class="next">${e.next}</p>`}
    <div class="btns">
      <a class="btn btn-small" href="#/logs" data-act="seelogs" data-client="${a.client}" data-env="${name}" data-q="${a.name}">Ver logs</a>
      ${coolify && h`<button class="btn btn-small" data-act="ask" data-verb="Reiniciar" data-name="${a.name}" data-env="${name}">Reiniciar</button>`}
      ${coolify && a.type !== 'db-coolify' && h`<button class="btn btn-small" data-act="ask" data-verb="Fazer deploy de" data-name="${a.name}" data-env="${name}">Fazer deploy</button>`}
      ${e.backupFailed && h`<button class="btn btn-small" data-act="ask" data-verb="Fazer backup de" data-name="${a.name}" data-env="${name}" data-backup="${a.id}">Fazer backup</button>`}
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
    ${exNote()}
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
  <section aria-labelledby="al-title"><div class="sec-head"><h2 id="al-title">Todas as aplicações</h2>${exNote()}</div>
  <div class="filters">
    ${select('f-client', 'Cliente', 'fApps.client', f.client, [['', 'Todos'], ...S.data.clients.map((c) => [c.id, c.name])])}
    ${select('f-type', 'Tipo', 'fApps.type', f.type, [['', 'Todos'], ...Object.entries(APP_TYPES).map(([k, v]) => [k, v.name])])}
    ${select('f-state', 'Situação', 'fApps.state', f.state, [['', 'Todas'], ['problem', 'Com problema'], ['behind', 'Produção atrás de dev']])}
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
  const ex = isDemo('logs');
  const rows = S.data.logs.filter((l) => (!f.client || l.client === f.client) && (!f.env || l.env === f.env) && (!f.level || l.level === f.level) && (!q || `${l.app} ${l.event} ${l.route}`.toLowerCase().includes(q)));
  const lv = { info: 'off', warn: 'warn', error: 'err' };
  return h`
  <header class="head"><h1>Logs</h1><p class="lede">Vêm já filtrados pela allowlist, sem mensagem de erro e sem dado sensível. Para o log bruto, o caminho é o Coolify.</p></header>
  ${exNote()}
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
      ${mark(lv[l.level], l.level, ex)}<span class="row-main"><b><code>${l.event}</code> ${l.route}</b><span class="muted">${clientName(l.client)}, ${l.app}, ${l.env}</span></span><span class="row-side"><b>${l.status}</b><span class="muted">${l.time}</span></span></button>
      ${S.openLog === l.id && h`<div class="row-detail"><dl class="facts"><div><dt>Duração</dt><dd>${l.ms} ms</dd></div><div><dt>Request</dt><dd><code>${l.rid}</code></dd></div><div><dt>Marcação de segurança</dt><dd>${l.flag || 'Nenhuma'}</dd></div></dl><p class="muted">A mensagem de erro não vem para cá, porque pode trazer valores. Para investigar, procure este request no log bruto do Coolify.</p></div>`}</li>`)}
    ${!rows.length && h`<li class="row-empty">Nenhum log com esses filtros. <button class="link-btn" data-act="clearlogs">Limpar filtros</button></li>`}
  </ul>`;
}

// ---------- Atividade ----------
function viewAtividade() {
  const ex = isDemo('activity');
  const res = { ok: ['ok', 'Sucesso'], err: ['err', 'Falhou'], sim: ['off', 'Simulado'] };
  return h`
  <header class="head"><h1>Atividade</h1><p class="lede">O que foi feito pelo painel e o resultado de cada etapa. Quem leu qual segredo fica no audit do cofre.</p></header>
  ${exNote('Exemplo. As ações que você simular neste painel entram aqui.')}
  <ul class="rows">
    ${S.data.activity.map((a) => h`<li><button class="row-link" data-act="openact" data-id="${a.id}" aria-expanded="${S.openAct === a.id}">${mark(res[a.result][0], res[a.result][1], ex)}<span class="row-main"><b>${a.action}</b><span class="muted">${a.who}, ${a.where}</span></span><span class="row-side muted">${a.time}</span></button>
      ${S.openAct === a.id && h`<div class="row-detail"><ol class="steps">${a.steps.map((s) => h`<li>${s}</li>`)}</ol></div>`}</li>`)}
  </ul>
  <div><button class="link-btn" data-act="resetdemo">Voltar os exemplos ao início</button></div>`;
}

// ---------- Contas: por conta de cada cliente, não por tabela de tokens ----------
function accountDetail(a) {
  const p = PROVIDERS[a.provider];
  const ex = isDemo('accounts');
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
      <p class="muted">Em <code>kv/${a.client}/_providers/${a.name}</code>. O painel mostra só se o campo existe, nunca o valor.</p>
      <ul class="fields">${a.fields.map((f) => h`<li>${mark(f.set ? 'ok' : 'warn', f.set ? 'Gravado' : 'Falta', ex)}<span><code>${f.name}</code><span class="muted"> ${p.fields[f.name] || ''}</span></span></li>`)}</ul>
      <p class="muted">${filled} de ${a.fields.length} campos gravados.</p></section>`}
    <section class="account-sec"><h3>${hasToken ? 'Como conectar ou renovar' : 'Como conectar este servidor'}</h3>
      <ol class="steps">${p.create.map((s) => h`<li>${s}</li>`)}${hasToken && !p.piped && h`<li>Rode o comando abaixo no terminal. O valor é pedido em prompt oculto e vai direto para o cofre.</li>`}</ol>
      ${url ? h`<a class="btn" href="${url}" target="_blank" rel="noopener">${p.urlLabel}</a>` : p.toolCheck && h`<p class="muted">O Coolify ainda não está no ar nesta máquina. <a href="#/configurar/maquina#containers">Veja como subir</a>.</p>`}
      ${copyBlock(p.command(a.client, a.name))}</section>
    ${hasToken && h`<section class="account-sec"><h3>Como conferir</h3>
      ${copyBlock(`scripts/cp-secrets provider list ${a.client}\nscripts/cp-secrets sync plan ${a.client}`)}</section>`}
    <section class="account-sec"><h3>Encerrar o acesso</h3><p class="muted">${p.revokeHelp}</p>
      <div class="btns">
        ${hasToken && h`<button class="btn" data-act="testacc" data-id="${a.id}">Testar a conexão</button>`}
        ${hasToken && a.state !== 'missing' && h`<button class="btn btn-danger" data-act="revokeacc" data-id="${a.id}">Revogar</button>`}
      </div>
    </section>
  </article>`;
}

function viewContas(id) {
  const selected = S.data.accounts.find((a) => a.id === id) || S.data.accounts.find((a) => ['expired', 'missing', 'soon'].includes(a.state)) || S.data.accounts[0];
  const ex = isDemo('accounts');
  return h`
  <header class="head-row"><div><h1>Contas</h1><p class="lede">Cada plataforma de cada cliente é uma conta separada, com login e token próprios. Escolha uma para ver o que ela atende e o que falta.</p></div><button class="btn btn-pri" data-act="newacc">Conectar conta</button></header>
  ${exNote()}
  <div class="master">
    <nav class="master-list" aria-label="Contas por cliente">
      ${S.data.clients.map((c) => h`<div class="master-group"><h2>${c.name}</h2>
        ${accountsOf(c.id).map((a) => { const [k, l] = ACCOUNT_STATE[a.state]; return h`<a class="master-item${a.id === selected?.id ? ' is-on' : ''}" href="#/contas/${a.id}"${a.id === selected?.id ? h` aria-current="true"` : ''}><span class="sig sig-${k}${ex ? ' is-ex' : ''}" title="${l}"><span class="sr">${l}</span></span><span class="master-text"><b>${PROVIDERS[a.provider].name}</b><span class="muted">${a.expires}</span></span></a>`; })}
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
  ${TRACKS.map((t) => { const list = rows.filter((c) => c.track === t.id); return list.length > 0 && h`
    <section id="${t.id}" class="track" aria-labelledby="t-${t.id}"><div class="sec-head"><h2 id="t-${t.id}">${t.name}</h2><p class="muted">${t.why}</p></div><ul class="checks">${list.map(checkRow)}</ul></section>`; })}
  ${desired && !desired.error && h`<section class="track" aria-labelledby="t-desired"><div class="sec-head"><h2 id="t-desired">Declarado no repositório</h2><p class="muted">Lido agora de <code>openbao/secrets.toml</code>. São só nomes.${d.draft_todos ? ` O rascunho completo ainda tem ${d.draft_todos} IDs a preencher.` : ''}</p></div>
    <ul class="rows">${desired.clients.map((c) => h`<li class="row-plain">${mark('ok', 'Declarado')}<span class="row-main"><b>${c.slug}</b><span class="muted">${c.providers.length} contas e ${c.projects.length} projetos: ${c.projects.map((p) => p.slug).join(', ')}</span></span></li>`)}</ul></section>`}`;
}

function tabTipos() {
  const ex = isDemo('apps');
  return h`
  <p class="lede">O que cada tipo de aplicação precisa, camada por camada. Os números mostram quantas aplicações do exemplo ainda têm alguma pendência.</p>
  <div class="types">${Object.entries(APP_TYPES).map(([id, t]) => {
    const apps = S.data.apps.filter((a) => a.type === id);
    const pending = apps.filter((a) => Object.values(a.ready).some((r) => r === 'todo' || r === 'err'));
    return h`<article class="type-card" id="tipo-${id}">
      <header><h2>${t.name}</h2><p class="muted">${t.when}</p>${mark(pending.length ? 'warn' : 'ok', pending.length ? `${pending.length} de ${apps.length} com pendência` : `${apps.length} sem pendência`, ex)}</header>
      ${t.layers.map((l) => h`<section class="layer"><h3>${l.track}</h3><ul class="plain">${l.items.map((i) => h`<li>${i}</li>`)}</ul>
        ${l.cmd && h`<details class="fold"><summary>Ver o comando</summary>${copyBlock(l.cmd)}</details>`}
        <p class="btns">${l.to && h`<a class="inline-link" href="${l.to}">${l.toLabel}</a>`}${l.guide && h`<a class="inline-link" href="#/guias/${l.guide}">Abrir o guia</a>`}</p></section>`)}
    </article>`;
  })}</div>`;
}

function tabReal() {
  const areas = Object.values(S.data.sources || {}).filter((v) => v === 'demo').length;
  return h`
  <p class="lede">Hoje, ${areas} áreas usam dados de exemplo. Cada uma ganha o dado real quando a fase dela chegar, sem mudar a tela. A hachura some sozinha.</p>
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
const wizLabels = (w, slug) => [
  'Snapshot do cofre', `Gravar openbao/clients/${slug}.toml`, 'Criar policies e identidades', 'Gerar os segredos internos',
  ...(w.logs ? [`Criar as orgs ${slug.replace(/-/g, '_')}_dev e ${slug.replace(/-/g, '_')}_prod`] : []),
  ...(w.analytics ? ['Criar os sites no Umami'] : []),
  'Conferir as diferenças', 'Levar os segredos para dev e fazer o redeploy', 'Conferir o health check de dev',
];
const wizToml = (w, slug, projs) => {
  const provs = Object.keys(w.plat).filter((k) => w.plat[k] && k !== 'droplet');
  return `# openbao/clients/${slug}.toml\n[[client]]\nslug = "${slug}"\n\n${provs.map((k) => `[[client.provider]]\nname = "${k}"\nkind = "${k}"`).join('\n\n')}\n\n${projs.map((p) => `[[client.project]]\nslug = "${p.slug}"\nenvironments = ["dev", "prod"]`).join('\n\n')}`;
};
const wizScript = (w, slug) => {
  const lines = Object.keys(w.plat).filter((k) => w.plat[k]).map((k) => PROVIDERS[k].command(slug, k));
  return [...lines, 'scripts/cp-secrets plan', 'scripts/cp-secrets apply', `scripts/cp-secrets sync plan ${slug}`].join('\n');
};

function viewNovoCliente() {
  if (!S.wiz) S.wiz = emptyWiz();
  const w = S.wiz;
  const slug = toSlug(w.name);
  const dup = S.data.clients.some((c) => c.id === slug);
  const chosen = Object.keys(w.plat).filter((k) => w.plat[k]);
  const hosts = chosen.filter((k) => k !== 'github');
  const projAll = wizProjects(w, slug || 'cliente');
  const projOn = projAll.filter((p) => !w.projOff[p.slug]);
  const pending = chosen.filter((k) => !w.done[k]);
  const names = ['Cliente', 'Contas', 'Projetos', 'Variáveis', 'Revisão', 'Aplicação'];
  const labels = wizLabels(w, slug || 'cliente');
  let block = '';
  if (w.step === 1) block = !slug ? 'Informe o nome do cliente.' : dup ? 'Já existe um cliente com esse identificador.' : !hosts.length ? 'Escolha ao menos uma plataforma de hospedagem.' : '';
  if (w.step === 2 && pending.length) block = `Falta marcar: ${pending.map((k) => PROVIDERS[k].name).join(', ')}.`;
  if (w.step === 3 && !projOn.length) block = 'Escolha ao menos um projeto.';
  const finished = w.step === 6 && w.run >= labels.length;
  return h`
  <div class="wizard">
    <header class="head"><h1>Novo cliente</h1><p class="lede">Um caminho único, do contrato até dev. Produção fica para quando você decidir.</p></header>
    ${exNote('Simulação: a aplicação ainda não grava nada. Os comandos e o arquivo gerados já têm o formato final.')}
    <ol class="stepper" aria-label="Etapas">${names.map((n, i) => h`<li class="${i + 1 === w.step ? 'is-on' : i + 1 < w.step ? 'is-done' : ''}"${i + 1 === w.step ? h` aria-current="step"` : ''}><span class="stepper-n">${i + 1}</span>${n}</li>`)}</ol>

    ${w.step === 1 && h`<section class="panel"><h2>Quem é o cliente</h2>
      <div class="form-grid"><label class="fld" for="w-name">Nome<input id="w-name" data-bind="wiz.name" value="${w.name}" autocomplete="off" placeholder="Loja Exemplo"></label>
      <p class="fld">Identificador gerado<output class="slug"><code>${slug || 'aparece aqui'}</code></output></p></div></section>
      <section class="panel"><h2>Onde ele roda</h2><p class="muted">Só aparecem as plataformas com esteira pronta. Todas usam a conta do próprio cliente.</p>
      ${Object.entries(WIZ_PLATFORMS).map(([k, p]) => h`<label class="check-opt"><input type="checkbox" data-act="wplat" data-k="${k}"${w.plat[k] ? h` checked` : ''}><span><b>${p.name}</b><span class="muted"> ${p.desc}</span></span></label>`)}
      ${w.plat.droplet && !w.plat.coolify && h`<p class="caution"><b>Cuidado:</b> o Droplet é operado pelo Coolify. Marque o Coolify também.</p>`}</section>`}

    ${w.step === 2 && h`<div class="info">O token nunca é digitado nesta tela. Crie na conta do cliente, rode o comando no terminal e marque como feito.</div>
      ${chosen.map((k) => { const p = PROVIDERS[k]; return h`<section class="panel"><div class="panel-head"><h2>${p.name}</h2>${mark(w.done[k] ? 'ok' : 'warn', w.done[k] ? 'Feito' : 'Falta', true)}</div>
        <p class="muted">${p.role}</p><ol class="steps">${p.create.map((s) => h`<li>${s}</li>`)}</ol>
        ${copyBlock(p.command(slug, k))}
        <div class="btns">${p.url && h`<a class="btn" href="${p.url}" target="_blank" rel="noopener">${p.urlLabel}</a>`}<label class="check-opt"><input type="checkbox" data-act="wdone" data-k="${k}"${w.done[k] ? h` checked` : ''}>Já fiz esta conta</label></div></section>`; })}`}

    ${w.step === 3 && h`<section class="panel"><h2>Projetos deste cliente</h2><p class="muted">Depois, esta lista virá das próprias contas, para você não precisar procurar nem colar IDs. Por enquanto, confirme ou acrescente.</p>
      ${projAll.map((p) => h`<label class="check-opt"><input type="checkbox" data-act="wproj" data-k="${p.slug}"${!w.projOff[p.slug] ? h` checked` : ''}><span><code>${p.slug}</code><span class="muted"> ${typeName(p.type)}, dev e prod</span></span></label>`)}
      <div class="form-inline"><label class="fld fld-grow" for="w-extra">Outro projeto<input id="w-extra" data-bind="wiz.extra" value="${w.extra}" autocomplete="off" placeholder="lp-exemplo"></label>
      ${select('w-extra-type', 'Tipo', 'wiz.extraType', w.extraType || 'front-vercel', Object.entries(APP_TYPES).map(([k, v]) => [k, v.name]))}
      <button class="btn" data-act="waddproj"${!toSlug(w.extra) ? h` disabled` : ''}>Adicionar</button></div></section>`}

    ${w.step === 4 && h`<section class="panel"><h2>Variáveis que cada projeto precisa</h2><p class="muted">Só o que está nesta lista chega ao destino. Os valores não passam por esta tela.</p>
      <ul class="fields"><li><code>NODE_ENV</code><span class="muted">Definido no arquivo</span></li><li><code>JWT_SECRET</code><span class="muted">Gerado no cofre</span></li><li><code>DATABASE_URL</code><span class="muted">Você grava no cofre</span></li><li><code>RESEND_API_KEY</code><span class="muted">Você grava no cofre</span></li></ul></section>
      <section class="panel"><h2>Logs e analytics</h2>
      <label class="check-opt"><input type="checkbox" data-act="wlogs"${w.logs ? h` checked` : ''}><span><b>Ligar logs</b><span class="muted"> Cria as orgs por ambiente e o token de envio.</span></span></label>
      <label class="check-opt"><input type="checkbox" data-act="wanalytics"${w.analytics ? h` checked` : ''}><span><b>Ligar analytics</b><span class="muted"> Cria um site no Umami para cada front.</span></span></label></section>`}

    ${w.step === 5 && h`<section class="panel"><h2>O que será feito</h2><ol class="steps">${labels.map((l) => h`<li>${l}</li>`)}</ol>
      <p class="caution"><b>Fica com você:</b> levar para prod, preencher no cofre os valores vindos de painéis externos${w.plat.droplet ? ' e rodar o instalador dentro do Droplet' : ''}.</p></section>
      <section class="panel"><h2>Estado desejado, só com nomes</h2>${copyBlock(wizToml(w, slug, projOn), 'Copiar arquivo')}</section>
      <section class="panel"><h2>Comandos equivalentes no terminal</h2>${copyBlock(wizScript(w, slug), 'Copiar comandos')}</section>`}

    ${w.step === 6 && h`<section class="panel"><h2>${finished ? 'Simulação concluída até dev' : 'Simulando a aplicação'}</h2>
      <ul class="rows" role="status">${labels.map((l, i) => { const st = i < w.run ? ['ok', 'Feito'] : i === w.run ? ['warn', 'Rodando'] : ['off', 'Na fila']; return h`<li class="row-plain">${mark(st[0], st[1], true)}<span class="row-main">${l}</span></li>`; })}</ul></section>
      ${finished && h`<div class="info"><b>${w.name.trim()} entrou nas telas como exemplo.</b> Produção fica para quando você decidir. Nada foi gravado no cofre nem no repositório.</div>
      <div><a class="btn btn-pri" href="#/clientes/${slug}">Abrir o cliente</a></div>`}`}

    ${w.step < 6 && h`<footer class="wiz-nav"><a class="btn btn-ghost" href="#/clientes" data-act="wcancel">Cancelar</a>
      <span class="btns">${w.step > 1 && h`<button class="btn" data-act="wback">Voltar</button>`}<button class="btn btn-pri" data-act="wnext" data-block="${block}"${block ? h` disabled` : ''}>${w.step === 5 ? 'Simular até dev' : 'Continuar'}</button></span></footer>
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
  const nextDays = 'Vence em 90 dias';
  for (const k of chosen) {
    const hasToken = k !== 'droplet';
    S.data.accounts.push({ id: `${slug}-${k}`, client: slug, provider: k, name: hasToken ? k : `vps-${slug}`, label: hasToken ? `Conta de ${name}` : `Droplet de ${name}`, state: hasToken ? 'ok' : 'notoken', expires: hasToken ? nextDays : 'Sem token', tested: 'Testada agora', fields: Object.keys(PROVIDERS[k].fields).map((f) => ({ name: f, set: true })), serves: projs.map((p) => p.slug) });
  }
  for (const p of projs) {
    const where = p.type.endsWith('coolify') ? `vps-${slug}` : p.type === 'front-vercel' ? 'Vercel' : 'Railway';
    S.data.apps.push({ id: `${slug}--${p.slug}`, client: slug, name: p.slug, type: p.type, ready: { conta: 'ok', segredos: 'todo', host: 'ok', logs: w.logs ? 'ok' : 'todo' }, envs: { dev: { state: 'running', version: '0.1.0', commit: '0000000', when: 'agora', where, health: 'Saudável' }, prod: { state: 'waiting', version: 'Aguardando prod', commit: '', when: 'Sem deploy', where, next: 'Confira os valores no cofre e leve para prod.' } } });
  }
  S.data.rollout[slug] = [
    { title: 'Contas conectadas', state: 'ok' }, { title: 'Projetos declarados', state: 'ok' }, { title: 'Segredos internos gerados', state: 'ok' },
    { title: 'Valores vindos de painéis externos', state: 'todo', hint: 'Preencha DATABASE_URL e as demais no cofre.', to: '#/ferramentas', toLabel: 'Abrir ferramentas' },
    { title: 'Logs e analytics ligados', state: w.logs || w.analytics ? 'ok' : 'todo', hint: 'Ligue quando o app estiver pronto.', to: '#/guias/ligar-logs', toLabel: 'Ver guia' },
    { title: 'VPS cadastrada no Coolify', state: w.plat.coolify ? 'todo' : 'na', hint: 'Rode o instalador na VPS do cliente.', to: '#/guias/vps-nova', toLabel: 'Ver guia' },
    { title: 'Segredos levados para dev', state: 'ok' },
    { title: 'Segredos levados para prod', state: 'todo', hint: 'Leve quando os valores estiverem conferidos.', action: 'prod' },
  ];
  record(`Cliente ${name} criado até dev`, wizLabels(w, slug));
  saveDemo();
}

// ---------- Janelas ----------
function modalView() {
  const m = S.modal;
  if (!m) return '';
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
function saveDemo() { store.set(DEMO_KEY, JSON.stringify(S.data)); }
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
  wdone(el) { S.wiz.done[el.dataset.k] = el.checked; render(); },
  wproj(el) { S.wiz.projOff[el.dataset.k] = !el.checked; render(); },
  wlogs(el) { S.wiz.logs = el.checked; render(); },
  wanalytics(el) { S.wiz.analytics = el.checked; render(); },
  waddproj() {
    const w = S.wiz;
    const slug = toSlug(w.extra);
    if (slug && !wizProjects(w, toSlug(w.name)).some((p) => p.slug === slug)) w.projExtra.push({ slug, type: w.extraType || 'front-vercel' });
    w.extra = '';
    render();
  },
  wback() { S.wiz.step -= 1; render(); window.scrollTo(0, 0); },
  wcancel() { S.wiz = null; },
  wnext() {
    const w = S.wiz;
    if (w.step === 5) {
      w.step = 6; w.run = 0; render();
      const total = wizLabels(w, toSlug(w.name)).length;
      const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
      clearInterval(ACTIONS.timer);
      ACTIONS.timer = setInterval(() => {
        w.run = reduce ? total : w.run + 1;
        if (w.run >= total) { clearInterval(ACTIONS.timer); finishWizard(); }
        if (location.hash === '#/novo-cliente') render();
      }, reduce ? 1 : 450);
    } else { w.step += 1; render(); }
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
  if (r.name === 'novo-cliente' && S.wiz?.step === 6 && S.wiz.run >= wizLabels(S.wiz, toSlug(S.wiz.name)).length) S.wiz = null;
  render();
  if (key !== lastRoute) {
    if (r.anchor) document.getElementById(r.anchor)?.scrollIntoView();
    else if (!(r.name === 'guias' && lastRoute.startsWith('guias/'))) window.scrollTo(0, 0);
  }
  lastRoute = key;
});

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
    const saved = store.get(DEMO_KEY);
    S.data = saved ? { ...JSON.parse(saved), sources: S.base.sources } : structuredClone(S.base);
  } catch {
    S.failed = true;
  }
  render();
  await pollDevice();
  const r = route();
  lastRoute = `${r.name}/${r.arg || ''}`;
  if (r.anchor) document.getElementById(r.anchor)?.scrollIntoView();
  setInterval(pollDevice, POLL_MS);
}

start();
