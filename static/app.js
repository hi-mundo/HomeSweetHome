"use strict";

const CAT_ICON = {
  "Hortifruti": "🥬", "Frutas": "🍎", "Carnes e ovos": "🥩", "Laticínios e frios": "🧀", "Padaria": "🍞",
  "Despensa": "🥫", "Lanches": "🥜", "Temperos": "🧂", "Bebidas": "🥤", "Congelados": "🧊",
  "Limpeza": "🧽", "Utensílios": "🧹", "Higiene": "🧴", "Outros": "📦",
};
// Aba "Casa": limpeza, utensílios e higiene. O resto é a aba "Cozinha".
const HOME_CATS = new Set(["Limpeza", "Utensílios", "Higiene"]);
const isHome = (item) => HOME_CATS.has(item.category);
// O ícone de cada item vem do catálogo (pratos/ingredientes.json, pratos/itens-da-casa.json).
const itemIcon = (item) => item.emoji || CAT_ICON[item.category] || "📦";
const LEVEL_LABEL = { ok: "Tem", low: "Pouco", out: "Acabou" };
const PLAN_LIMITS = { days: [1, 7], desserts: [0, 2] };
const TYPES = {
  meal: { icon: "utensils", label: "Refeições" },
  dessert: { icon: "cake", label: "Sobremesas" },
  snack: { icon: "cookie", label: "Lanches da tarde" },
};
const PREP_LABEL = { nenhum: "Só separar", montar: "Sem fogão", cozinhar: "" };
const VIEW_TITLE = { dishes: "Lar Doce Lar", stock: "Cozinha", home: "Casa", list: "Compras" };

const state = {
  items: [],
  dishes: [],
  dishErrors: [],
  categories: Object.keys(CAT_ICON),
  view: "dishes",
  dishType: null,      // null = blocos do cardápio; "meal" | "dessert" | "snack" = lista do tipo
  openDish: null,
  stockCat: null,      // null = blocos de categoria; nome = itens da categoria
  editStock: false,
  weekStatus: null,
  todayDay: null,      // dia escolhido no card "Hoje" (null = dia de hoje)
  savedPlan: null,
  plan: null,          // plano exibido na tela do plano
  planMode: null,      // "new" (sugestão) | "saved" (plano da semana) | null (fechado)
  planTab: "week",
  planDay: 0,
  planParams: { days: 5, desserts: 2 },
  planVariant: 0,
  pending: 0,
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Mesma chave do servidor: sem acento, minúscula — "Feijao" acha "Feijão".
const key = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
const byId = (id) => state.items.find((i) => i.id === id);
const stockByKey = () => new Map(state.items.map((i) => [key(i.name), i]));
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const isStockView = () => state.view === "stock" || state.view === "home";
const icon = (name, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const kcal = (n) => `${Math.round(n).toLocaleString("pt-BR")} kcal`;
// 75 -> "1h15"; 40 -> "40 min"
const duration = (min) => min >= 60 ? `${Math.floor(min / 60)}h${String(min % 60).padStart(2, "0")}` : `${min} min`;
const clock = (min) => `${Math.floor(min / 60)}:${String(min % 60).padStart(2, "0")}`;

// Transição suave entre telas, quando o navegador suporta (Safari 18+, Chrome).
function transition(fn) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (document.startViewTransition && !reduce) document.startViewTransition(fn); else fn();
}

// ---------------------------------------------------------------- API

async function api(method, path, body) {
  state.pending++;
  try {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Erro ao salvar");
    setSync(true);
    return data;
  } catch (e) {
    if (e instanceof TypeError) setSync(false);
    throw e;
  } finally {
    state.pending--;
  }
}

async function load() {
  try {
    const data = await api("GET", "/api/items");
    state.items = data.items;
    state.categories = data.categories;
    render();
    refreshWeekStatus();
  } catch { /* indicador de sync já mostra */ }
}

async function loadDishes() {
  try {
    const [dishes, plan] = await Promise.all([api("GET", "/api/dishes"), api("GET", "/api/plan")]);
    state.dishes = dishes.dishes;
    state.dishErrors = dishes.errors;
    // Planos salvos antes do formato atual (por dia, com roteiro) são ignorados.
    const p = plan.plan;
    state.savedPlan = p && p.days && p.days.length && typeof p.days[0].lunch === "object" && p.schedule ? p : null;
    renderDishes();
  } catch { /* idem */ }
}

// O estoque dá para uma semana? Recalcula um pouco depois da última mudança.
let weekTimer;
function refreshWeekStatus() {
  clearTimeout(weekTimer);
  weekTimer = setTimeout(async () => {
    try {
      state.weekStatus = await api("GET", "/api/week-status");
      renderAlerts();
    } catch { /* idem */ }
  }, 600);
}

function upsert(item) {
  const i = state.items.findIndex((x) => x.id === item.id);
  if (i >= 0) state.items[i] = item; else state.items.push(item);
}

function setSync(ok) {
  const el = $("#sync");
  el.textContent = ok ? "" : "Sem conexão…";
  el.classList.toggle("err", !ok);
}

// Atualização otimista: aplica localmente, envia, e reverte se der erro.
async function patch(item, changes, { toastMsg, undoable = true } = {}) {
  const before = { ...item };
  Object.assign(item, localRules(item, changes));
  render();
  try {
    const { item: saved } = await api("PATCH", `/api/items/${item.id}`, changes);
    upsert(saved);
    render();
    refreshWeekStatus();
    if (toastMsg) toast(toastMsg, undoable ? () => restore(before) : null);
  } catch (e) {
    upsert(before);
    render();
    toast(e.message);
  }
}

function restore(snapshot) {
  const { id, name, category, level, on_list, in_cart, note } = snapshot;
  const current = byId(id);
  if (!current) return;
  patch(current, { name, category, level, on_list, in_cart, note }, { undoable: false });
}

// Espelha a regra do servidor para a tela responder na hora.
function localRules(item, c) {
  const out = { ...c };
  if ("level" in c && !("on_list" in c) && c.level !== item.level) {
    out.on_list = c.level !== "ok";
    if (c.level === "ok") { out.in_cart = false; out.note = ""; }
  }
  if (c.on_list === false) { out.in_cart = false; out.note = ""; }
  return out;
}

async function addManyToList(entries, msg) {
  try {
    const data = await api("POST", "/api/list/add", { items: entries });
    state.items = data.items;
    render();
    refreshWeekStatus();
    toast(msg);
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- Render

function grouped(items) {
  const groups = new Map(state.categories.map((c) => [c, []]));
  for (const it of items) (groups.get(it.category) || groups.get("Outros")).push(it);
  return [...groups].filter(([, list]) => list.length);
}

function render() {
  renderDishes();
  renderStock();
  renderList();
  renderAlerts();
  if (state.planMode && state.plan) renderPlan();
  const pendingCount = state.items.filter((i) => i.on_list && !i.in_cart).length;
  const badge = $("#list-badge");
  badge.textContent = pendingCount;
  badge.hidden = pendingCount === 0;
  $("#btn-edit-stock").hidden = !isStockView() || state.editStock;
  // Barra "ver lista" nas outras abas, como a sacola de um app de delivery.
  const showBar = pendingCount > 0 && state.view !== "list" && !state.planMode && !state.editStock;
  $("#cart-bar").hidden = !showBar;
  $("#cart-bar-count").textContent = plural(pendingCount, "item", "itens");
  document.body.classList.toggle("has-cart-bar", showBar);
}

// ---------- Alerta: o estoque dá para a semana?

function renderAlerts() {
  const ws = state.weekStatus;
  let html = "";
  if (ws && !ws.ok) {
    const toAsk = ws.missing.filter((m) => !m.on_list);
    if (ws.missing.length) {
      const names = ws.missing.map((m) => esc(m.name)).join(", ");
      html = `<div class="alert">${icon("alert")}<div class="alert-body">
        <h3>${ws.source === "saved" ? "Falta coisa para o plano desta semana" : `Falta comida para ${plural(ws.days, "dia", "dias")}`}</h3>
        <p>${ws.source === "saved" ? "Os pratos do plano precisam de" : "Para montar a semana ainda falta"}: ${names}.</p>
        ${toAsk.length
          ? `<button class="btn danger small" data-action="week-request" type="button">${icon("cart", "sm")}Pedir o que falta (${toAsk.length})</button>`
          : `<small>Já está tudo na lista de compras — falta comprar.</small>`}
        ${ws.low.length ? `<small>Acabando: ${ws.low.map((m) => esc(m.name)).join(", ")}</small>` : ""}
      </div></div>`;
    } else if (ws.warnings.length) {
      html = `<div class="alert warn">${icon("clock")}<div class="alert-body"><h3>Atenção à validade</h3>
        <p>${ws.warnings.map(esc).join("<br>")}</p></div></div>`;
    }
  }
  $("#week-alert").innerHTML = html;
  // Na Cozinha o alerta também aparece; na Casa não faz sentido.
  $("#stock-alert").innerHTML = state.view === "stock" ? html : "";
}

function requestWeekMissing() {
  const toAsk = state.weekStatus.missing.filter((m) => !m.on_list);
  addManyToList(toAsk.map(({ name, note, category }) => ({ name, note, category })),
    `${plural(toAsk.length, "item pedido", "itens pedidos")} para a semana`);
}

// ---------- Início: card "Hoje" + cardápio em blocos

// Um ingrediente "falta" se acabou ou nem existe no estoque. "Pouco" ainda dá.
function dishStatus(dish) {
  const byKey = stockByKey();
  const check = (ing) => {
    const item = byKey.get(key(ing.name));
    return { ...ing, item, level: item ? item.level : "out" };
  };
  const ingredients = dish.ingredients.map(check);
  const missing = ingredients.filter((i) => i.level === "out");
  return {
    ingredients,
    optional: dish.optional.map(check),
    missing,
    low: ingredients.filter((i) => i.level === "low"),
    allRequested: missing.length > 0 && missing.every((i) => i.item && i.item.on_list),
  };
}

function planLookup(plan) {
  return new Map(["meals", "desserts", "snacks"].flatMap((k) => plan[k].map((x) => [x.id, x])));
}

// O plano é feito no dia 1 (dia em que foi salvo); hoje é o dia N.
function planToday(plan) {
  const n = Math.floor((Date.now() / 1000 - plan.saved_at) / 86400);
  return Math.max(0, Math.min(plan.days.length - 1, n));
}

function dayRowsHTML(plan, i) {
  const look = planLookup(plan);
  const d = plan.days[i];
  const row = (ic, label, x, extra = "", cal = null) => x ? `<div class="meal-row">
      <span class="when ${ic}">${icon(ic)}</span>
      <span class="what"><span class="label">${label}</span><strong>${esc(x.name)}</strong>${extra}</span>
      ${cal ? `<span class="kcal">${kcal(cal)}</span>` : ""}</div>` : "";
  const meal = (slot) => {
    const s = d[slot];
    const extras = [s.side, s.boost].filter(Boolean).map((x) => x.toLowerCase());
    return (extras.length ? `<span class="extra">+ ${esc(extras.join(" + "))}</span>` : "")
      + (s.frozen ? `<span class="tag info">${icon("snow")}Do freezer</span>` : "");
  };
  // Frutas: as que ainda aguentam cortadas neste dia (no máx. 2 nomes); depois, inteiras.
  const cut = d.fruit_cut || [];
  const fruits = cut.length ? `<span class="extra">+ fruta cortada: ${esc(cut.slice(0, 2).join(" ou ").toLowerCase())}</span>`
    : plan.fruits.length ? `<span class="extra">+ uma fruta inteira</span>` : "";
  const dessert = look.get(d.dessert), snack = look.get(d.snack);
  return row("sun", "Almoço", look.get(d.lunch.id), meal("lunch"), d.lunch.kcal)
    + row("cake", "Sobremesa", dessert, "", dessert && dessert.kcal)
    + row("apple", "Lanche", snack, fruits, snack && snack.kcal)
    + row("moon", "Janta", look.get(d.dinner.id), meal("dinner"), d.dinner.kcal);
}

// Lembrete de descongelar: o que vem do freezer amanhã.
function thawHTML(plan, i) {
  const next = plan.days[i + 1];
  if (!next) return "";
  const look = planLookup(plan);
  const names = ["lunch", "dinner"].filter((s) => next[s].frozen).map((s) => look.get(next[s].id).name);
  return names.length ? `<p class="thaw">${icon("snow")}<span>Hoje à noite, passar do freezer para a geladeira: ${esc(names.join(" e "))}.</span></p>` : "";
}

function renderWeekCard() {
  const p = state.savedPlan;
  const fresh = p && Date.now() / 1000 - p.saved_at < (p.days.length + 2) * 86400;
  if (!fresh) {
    $("#week-card").innerHTML = `<button class="hero" data-action="new-plan" type="button">
        <span class="hero-ic">${icon("pot", "lg")}</span>
        <h2>Cozinhar pra semana</h2>
        <p>Almoço, sobremesa, lanche e janta de cada dia — com o que tem em casa e sem repetir prato no mês.</p>
        <span class="cta">Montar plano ${icon("right", "sm")}</span>
      </button>`;
    return;
  }
  const today = planToday(p);
  const day = state.todayDay ?? today;
  $("#week-card").innerHTML = `<div class="card today">
      <div class="today-head">
        <div><h2>${day === today ? "Hoje" : `Dia ${day + 1}`}</h2><span class="meta">${kcal(p.days[day].kcal)} no dia</span></div>
        <button class="link" data-action="see-plan" type="button">Plano completo ${icon("right", "sm")}</button>
      </div>
      <div class="day-chips" role="group" aria-label="Escolher o dia">
        ${p.days.map((_, i) => `<button type="button" data-day="${i}" aria-pressed="${i === day}">${i === today ? "Hoje" : `Dia ${i + 1}`}</button>`).join("")}
      </div>
      ${dayRowsHTML(p, day)}
      ${thawHTML(p, day)}
      <div class="today-foot"><button class="btn secondary" data-action="new-plan" type="button">${icon("shuffle", "sm")}Fazer novo plano</button></div>
    </div>`;
}

function renderDishes() {
  if (!state.dishes.length && !state.dishErrors.length && !state.items.length) return; // ainda carregando
  renderWeekCard();
  const q = key($("#dish-search").value);
  $("#dish-search-clear").hidden = !q;
  const all = state.dishes.map((d) => ({ dish: d, st: dishStatus(d) }));

  let html = "";
  if (!state.dishes.length) {
    html = `<p class="empty"><span class="big">🍲</span>Nenhum prato cadastrado ainda.<br>Coloque arquivos na pasta <b>pratos/</b>.</p>`;
  } else if (!q && !state.dishType) {
    // Cardápio em 3 blocos, em vez de uma lista enorme.
    html = `<div class="section-head"><h2>Cardápio</h2><small>${plural(state.dishes.length, "prato", "pratos")}</small></div>
      <div class="tiles">${Object.entries(TYPES).map(([type, t]) => {
        const list = all.filter((x) => x.dish.type === type);
        const can = list.filter((x) => !x.st.missing.length).length;
        return `<button class="tile-cat" data-type="${type}" type="button">
          <span class="tile-ic">${icon(t.icon)}</span><strong>${t.label}</strong>
          <small>${can} de ${list.length} dá pra fazer</small></button>`;
      }).join("")}</div>`;
  } else {
    const shown = all
      .filter((x) => q ? key(x.dish.name).includes(q) || x.dish.preparos.some((p) => key(p).includes(q)) : x.dish.type === state.dishType)
      .sort((a, b) => a.st.missing.length - b.st.missing.length || a.dish.name.localeCompare(b.dish.name, "pt-BR"));
    if (!q) {
      const can = shown.filter((x) => !x.st.missing.length).length;
      html += `<div class="back-row"><button data-action="types" type="button">${icon("left", "sm")}Cardápio</button></div>
        <div class="section-head" style="margin-top:4px"><h2>${TYPES[state.dishType].label}</h2><small>${can} de ${shown.length} dá pra fazer</small></div>`;
    }
    html += shown.map(dishCardHTML).join("") || `<p class="empty">Nenhum prato encontrado.</p>`;
  }
  if (state.dishErrors.length) {
    html += `<p class="notice">Arquivos de pratos com problema:<br>${state.dishErrors.map(esc).join("<br>")}</p>`;
  }
  $("#dish-list").innerHTML = html;
}

function dishCardHTML({ dish, st }) {
  const ok = !st.missing.length;
  const open = state.openDish === dish.id;
  const names = (list) => list.map((i) => esc(i.name)).join(", ");
  const tags = [
    dish.kcal ? `<span class="tag neutral">${kcal(dish.kcal)}</span>` : "",
    PREP_LABEL[dish.prep] ? `<span class="tag ok">${PREP_LABEL[dish.prep]}</span>` : "",
    dish.life < 3 ? `<span class="tag low">${icon("clock")}Dura ${plural(dish.life, "dia", "dias")}</span>` : "",
    dish.type === "meal" && dish.freeze ? `<span class="tag info">${icon("snow")}Congela</span>` : "",
  ].join("");
  return `<article class="card dish ${ok ? "" : "cannot"} ${open ? "open" : ""}" data-dish="${esc(dish.id)}">
    <button class="dish-head" data-action="toggle" aria-expanded="${open}">
      <span class="thumb" aria-hidden="true">${esc(dish.emoji)}</span>
      <span class="dish-info">
        <span class="title"><strong>${esc(dish.name)}</strong>${icon("right", "chev sm")}</span>
        ${dish.type === "meal" ? `<span class="sub">${esc(dish.preparos.join(" + "))}</span>` : ""}
        <span class="meta">${tags}</span>
        ${ok ? `<span class="status ok">${icon("check")}Dá pra fazer</span>` : `<span class="status no">${icon("alert")}Falta: ${names(st.missing)}</span>`}
        ${st.low.length ? `<span class="warn">Acabando: ${names(st.low)}</span>` : ""}
      </span>
    </button>
    ${open ? `<ul class="ingredients">
      ${st.ingredients.map(ingHTML).join("")}
      ${st.optional.length ? `<li class="sub">Se tiver</li>${st.optional.map(ingHTML).join("")}` : ""}
    </ul>` : ""}
    ${ok ? "" : `<div class="dish-actions">${st.allRequested
      ? `<span class="onlist">${icon("cart", "sm")}O que falta já está na lista de compras</span>`
      : `<button class="btn primary small" data-action="request">${icon("cart", "sm")}Pedir o que falta (${st.missing.length})</button>`}</div>`}
  </article>`;
}

function ingHTML(i) {
  const label = { ok: "tem", low: "pouco", out: i.item ? "acabou" : "não tem" }[i.level];
  return `<li><span class="dot ${i.level}" aria-label="${label}"></span>${esc(i.name)}
    <span class="qty">${i.qty ? esc(i.qty) + " · " : ""}${label}</span></li>`;
}

function requestMissing(dish) {
  const { missing } = dishStatus(dish);
  addManyToList(missing.map((i) => ({ name: i.name, note: i.qty, category: i.category })),
    `${plural(missing.length, "item pedido", "itens pedidos")} para ${dish.name}`);
}

// ---------- Cozinha / Casa: "precisa de atenção" + blocos de categoria

function itemCardHTML(it) {
  const action = state.editStock
    ? (it.custom
      ? `<button class="del" data-action="delete" aria-label="Excluir ${esc(it.name)}">${icon("trash", "sm")}Excluir</button>`
      : `<span class="original">Item original</span>`)
    : `<div class="seg" role="group" aria-label="Quanto tem de ${esc(it.name)}">
        ${["ok", "low", "out"].map((l) =>
          `<button data-action="level" data-level="${l}" aria-pressed="${it.level === l}">${LEVEL_LABEL[l]}</button>`).join("")}
      </div>`;
  return `<div class="item ${it.level}" data-id="${it.id}">
    ${it.on_list ? `<span class="onlist" title="Na lista de compras">${icon("cart")}</span>` : ""}
    <button class="item-top" data-action="edit">
      <span class="emoji" aria-hidden="true">${itemIcon(it)}</span>
      <span class="iname">${esc(it.name)}${it.note && it.on_list ? `<small>${esc(it.note)}</small>` : it.unit ? `<small>${esc(it.unit)}</small>` : ""}</span>
    </button>
    ${action}
  </div>`;
}

function renderStock() {
  const home = state.view === "home";
  $("#stock-search").placeholder = home ? "Buscar ou adicionar (ex: rodo)" : "Buscar ou adicionar (ex: feijão)";
  const raw = $("#stock-search").value.trim();
  const q = key(raw);
  $("#stock-search-clear").hidden = !q;
  const inScope = state.items.filter((i) => isHome(i) === home);
  const byName = (a, b) => a.name.localeCompare(b.name, "pt-BR");

  let html = "";
  if (q) {
    // Busca: resultado direto, sem categorias.
    const found = inScope.filter((i) => key(i.name).includes(q)).sort(byName);
    if (!state.items.some((i) => key(i.name) === q) && !state.editStock) {
      html += `<button class="add-new" data-action="add-new">${icon("plus")}Adicionar “${esc(raw)}”</button>`;
    }
    html += found.length ? `<div class="grid">${found.map(itemCardHTML).join("")}</div>`
      : `<p class="empty">Nada com esse nome ${home ? "na Casa" : "na Cozinha"}.</p>`;
  } else if (state.stockCat) {
    const list = inScope.filter((i) => i.category === state.stockCat).sort(byName);
    html += `<div class="back-row"><button data-action="cats" type="button">${icon("left", "sm")}${home ? "Casa" : "Cozinha"}</button></div>
      <div class="section-head" style="margin-top:4px"><h2>${esc(state.stockCat)}</h2><small>${plural(list.length, "item", "itens")}</small></div>
      <div class="grid">${list.map(itemCardHTML).join("")}</div>`;
  } else {
    // Primeiro o que precisa de atenção; o resto fica dentro das categorias.
    const attention = inScope.filter((i) => i.level !== "ok")
      .sort((a, b) => (b.level === "out") - (a.level === "out") || byName(a, b));
    if (attention.length) {
      html += `<div class="section-head" style="margin-top:8px"><h2>Precisa de atenção</h2><small>${plural(attention.length, "item", "itens")}</small></div>
        <div class="grid">${attention.map(itemCardHTML).join("")}</div>`;
    }
    html += `<div class="section-head"><h2>Categorias</h2><small>${plural(inScope.length, "item", "itens")}</small></div><div class="tiles">`;
    for (const [cat, list] of grouped(inScope)) {
      const out = list.filter((i) => i.level === "out").length;
      const low = list.filter((i) => i.level === "low").length;
      html += `<button class="tile-cat" data-cat="${esc(cat)}" type="button">
        ${out ? `<span class="tag out">${out} acabou</span>` : low ? `<span class="tag low">${low} pouco</span>` : ""}
        <span class="tile-ic">${CAT_ICON[cat] || "📦"}</span>
        <strong>${esc(cat)}</strong><small>${plural(list.length, "item", "itens")}</small></button>`;
    }
    html += `</div>`;
    if (!inScope.length) html = `<p class="empty"><span class="big">${home ? "🧽" : "🧺"}</span>Nenhum item ainda. Digite um nome acima para começar.</p>`;
  }
  $("#stock-list").innerHTML = html;
}

function setEditStock(on) {
  state.editStock = on;
  $("#edit-banner").hidden = !on;
  render();
}

async function deleteItem(item) {
  state.items = state.items.filter((i) => i !== item);
  render();
  try {
    await api("DELETE", `/api/items/${item.id}`);
    toast(`${item.name} excluído`, async () => {
      const { name, category, level, on_list, note } = item;
      const { item: back } = await api("POST", "/api/items", { name, category, level, on_list, note });
      upsert(back); render();
    });
  } catch (e) { upsert(item); render(); toast(e.message); }
}

// ---------- Compras

function renderList() {
  const items = state.items.filter((i) => i.on_list);
  const toBuy = items.filter((i) => !i.in_cart);
  const inCart = items.filter((i) => i.in_cart);

  const rowHTML = (it) => `
    <div class="row ${it.in_cart ? "done" : ""}" data-id="${it.id}">
      <button class="check" data-action="cart" aria-pressed="${it.in_cart}" aria-label="Peguei ${esc(it.name)}"><span>${icon("check")}</span></button>
      <span class="emoji" aria-hidden="true">${itemIcon(it)}</span>
      <button class="name" data-action="edit">
        <strong>${esc(it.name)}</strong>
        <small>${it.note ? esc(it.note) : it.unit ? `1 ${esc(it.unit)}` : "Toque para pôr quantidade"}</small>
      </button>
      ${it.level !== "ok" && !it.in_cart ? `<span class="tag ${it.level}">${LEVEL_LABEL[it.level]}</span>` : ""}
      <button class="remove" data-action="unlist" aria-label="Tirar ${esc(it.name)} da lista">${icon("x", "sm")}</button>
    </div>`;

  let html = "";
  if (!items.length) {
    html = `<p class="empty"><span class="big">🎉</span>Nada para comprar.<br>
      Marque itens como <b>Pouco</b> ou <b>Acabou</b> na Cozinha ou na Casa, ou adicione acima.</p>`;
  }
  for (const [cat, list] of grouped(toBuy)) {
    list.sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
    html += `<div class="group"><h3 class="group-title">${esc(cat)}</h3><div class="card">${list.map(rowHTML).join("")}</div></div>`;
  }
  // O que já está no carrinho sai do caminho.
  if (inCart.length) {
    html += `<div class="group"><h3 class="group-title">No carrinho · ${inCart.length}</h3>
      <div class="card">${inCart.map(rowHTML).join("")}</div></div>`;
  }
  $("#shop-list").innerHTML = html;
  $("#list-actions").hidden = !items.length;
  const finish = $("#btn-finish");
  finish.disabled = !inCart.length;
  finish.innerHTML = inCart.length ? `${icon("check")}Comprei (${inCart.length})` : "Comprei";
  renderSuggest();
}

function renderSuggest() {
  const raw = $("#list-add").value.trim();
  const q = key(raw);
  const box = $("#list-suggest");
  $("#list-add-clear").hidden = !raw;
  if (!q) { box.hidden = true; return; }

  const matches = state.items
    .filter((i) => key(i.name).includes(q))
    .sort((a, b) => key(a.name).indexOf(q) - key(b.name).indexOf(q) || a.on_list - b.on_list)
    .slice(0, 8);
  let html = matches.map((it) => `
    <button type="button" data-id="${it.id}" ${it.on_list ? "disabled" : ""}>
      <span aria-hidden="true">${itemIcon(it)}</span>${esc(it.name)}
      <small>${it.on_list ? "Já está na lista" : LEVEL_LABEL[it.level] + " em casa"}</small>
    </button>`).join("");
  if (!state.items.some((i) => key(i.name) === q)) {
    html += `<button type="button" data-new="1">${icon("plus")}Novo item: “${esc(raw)}”</button>`;
  }
  box.innerHTML = html;
  box.className = "suggest card";
  box.hidden = false;
}

// ---------------------------------------------------------------- Plano da semana

function factorText(f) {
  const whole = Math.floor(f), half = f % 1 ? "½" : "";
  if (!whole) return "½ receita";
  return `${whole}${half} ${f > 1 ? "receitas" : "receita"}`;
}

// O que falta para o plano inteiro, contra o estoque de agora (não o do momento da sugestão).
function planMissing(plan) {
  const byKey = stockByKey();
  const notes = new Map();
  for (const pot of plan.pots) {
    for (const ing of pot.ingredients) {
      if (ing.qty && !notes.has(key(ing.name))) {
        notes.set(key(ing.name), pot.factor === 1 ? ing.qty : `${ing.qty} × ${String(pot.factor).replace(".", ",")}`);
      }
    }
  }
  const missing = plan.ingredients
    .filter((i) => { const it = byKey.get(key(i.name)); return !it || it.level === "out"; })
    .map((i) => ({ name: i.name, note: notes.get(key(i.name)) || "", category: i.category, item: byKey.get(key(i.name)) }));
  // Frutas: garantir pelo menos 2 em casa para a tarde.
  const fruitsHave = state.items.filter((i) => i.category === "Frutas" && i.level !== "out");
  if (fruitsHave.length < 2) {
    const fruitsOut = state.items.filter((i) => i.category === "Frutas" && i.level === "out");
    for (const f of fruitsOut.slice(0, 3 - fruitsHave.length)) missing.push({ name: f.name, note: "", category: "Frutas", item: f });
  }
  return missing;
}

async function fetchPlan() {
  $("#plan-body").innerHTML = `<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>`;
  $("#plan-actions").innerHTML = "";
  try {
    const { plan } = await api("POST", "/api/plan/suggest", { ...state.planParams, variant: state.planVariant });
    state.plan = plan;
    state.planDay = 0;
    renderPlan();
  } catch (e) { toast(e.message); }
}

function openPlan(mode) {
  state.planMode = mode;
  state.planTab = "week";
  $("#plan").hidden = false;
  $("#plan-title").textContent = mode === "new" ? "Cozinhar pra semana" : "Plano desta semana";
  document.body.style.overflow = "hidden";
  if (mode === "new") {
    if (state.savedPlan) state.planParams = { ...state.planParams, ...state.savedPlan.params };
    state.planVariant = 0;
    syncSteppers();
    fetchPlan();
  } else {
    state.plan = state.savedPlan;
    state.planDay = planToday(state.savedPlan);
    renderPlan();
  }
  render();
}

function closePlan() {
  state.planMode = null;
  $("#plan").hidden = true;
  document.body.style.overflow = "";
  if (location.hash === "#plano") history.replaceState(null, "", location.pathname);
  render();
}

function syncSteppers() {
  for (const st of document.querySelectorAll(".stepper")) {
    const p = st.dataset.param, v = state.planParams[p], [lo, hi] = PLAN_LIMITS[p];
    st.querySelector("b").textContent = v;
    st.querySelector('[data-step="-1"]').disabled = v <= lo;
    st.querySelector('[data-step="1"]').disabled = v >= hi;
  }
}

function lightHTML(list) {
  return list.map((x) => {
    const parts = [x.factor ? factorText(x.factor) : "", PREP_LABEL[x.prep], `dura ${plural(x.life, "dia", "dias")}`, kcal(x.kcal)];
    return `<div class="light"><span class="thumb" aria-hidden="true">${esc(x.emoji)}</span>
      <span class="what"><strong>${esc(x.name)}</strong><small>${esc(parts.filter(Boolean).join(" · "))}</small></span>
      <span class="qty">${x.portions}×</span></div>`;
  }).join("");
}

function renderPlan() {
  const plan = state.plan;
  for (const b of $("#plan-tabs").children) b.setAttribute("aria-selected", b.dataset.tab === state.planTab);
  $("#plan-config").hidden = !(state.planMode === "new" && state.planTab === "week");
  if (!plan || !plan.days || !plan.days.length) {
    $("#plan-body").innerHTML = `<p class="empty"><span class="big">🍲</span>Sem pratos suficientes para montar um plano.</p>`;
    $("#plan-actions").innerHTML = "";
    return;
  }
  const missing = planMissing(plan);
  const problems = missing.length || plan.warnings.length || plan.checks.some((c) => !c.ok);
  $("#plan-tab-alert").hidden = !problems;
  const sched = plan.schedule;

  let html = "";
  if (state.planTab === "week") {
    html += `<div class="stats">
        <div class="card stat"><b>${plan.days.length * 2}</b><span>marmitas</span></div>
        <div class="card stat"><b>${plan.pots.length}</b><span>panelas</span></div>
        <div class="card stat"><b>${duration(sched.end)}</b><span>de cozinha no dia 1</span></div>
        <div class="card stat ${missing.length ? "bad" : "good"}"><b>${missing.length || icon("check", "lg")}</b><span>${missing.length ? "itens faltando" : "tem tudo em casa"}</span></div>
      </div>
      <div class="card today" style="margin-top:14px">
        <div class="today-head"><h2>Dia ${state.planDay + 1}</h2><span class="meta">${kcal(plan.days[state.planDay].kcal)} no dia</span></div>
        <div class="day-chips" role="group" aria-label="Escolher o dia">
          ${plan.days.map((_, i) => `<button type="button" data-plan-day="${i}" aria-pressed="${i === state.planDay}">Dia ${i + 1}</button>`).join("")}
        </div>
        ${dayRowsHTML(plan, state.planDay)}
        ${thawHTML(plan, state.planDay)}
      </div>`;
  }

  if (state.planTab === "cook") {
    html += `<h3>Roteiro do dia de cozinha <small>≈ ${duration(sched.end)} no total · ${duration(sched.active)} de trabalho</small></h3>
      <ol class="card timeline">${sched.steps.map((s) => `
        <li><time>${clock(s.start)}</time><span><strong>${esc(s.name)}</strong>
          <small>${esc(s.equipment === "nenhum" ? "Bancada" : s.equipment[0].toUpperCase() + s.equipment.slice(1))} · ${s.active} min de trabalho${s.total > s.active ? ` · pronto às ${clock(s.end)}` : ""}</small></span></li>`).join("")}
      </ol>
      <h3>Panelas <small>toque para ver os ingredientes</small></h3>
      <div class="card box">${plan.pots.map((p, i) => `
        <details class="pot">
          <summary>
            <span class="num">${i + 1}</span>
            <span class="what"><strong>${esc(p.name)}</strong>
              <small>${plural(p.portions, "porção", "porções")} · ${factorText(p.factor)} · dura ${plural(p.life, "dia", "dias")}</small>
              <span class="tags">
                ${p.group ? `<span class="tag neutral">${esc(p.group)}</span>` : ""}
                ${p.freeze_from ? `<span class="tag info">${icon("snow")}Congelar do dia ${p.freeze_from} em diante</span>` : ""}
              </span></span>
            ${icon("right", "chev sm")}
          </summary>
          ${p.tip ? `<p class="tip">${esc(p.tip)}</p>` : ""}
          <p class="tip">Vai em: ${p.used_by.map(esc).join("; ")}</p>
          <ul class="ingredients">${p.ingredients.map((ing) => {
            const it = stockByKey().get(key(ing.name));
            return ingHTML({ ...ing, item: it, level: it ? it.level : "out" });
          }).join("")}</ul>
        </details>`).join("")}</div>`;
    if (plan.desserts.length) {
      html += `<h3>Sobremesas <small>faz uma vez, dura a semana</small></h3><div class="card box">${lightHTML(plan.desserts)}</div>`;
    }
    html += `<h3>Lanches <small>deixar separados em potinhos</small></h3><div class="card box">${lightHTML(plan.snacks)}</div>`;
  }

  if (state.planTab === "check") {
    const allRequested = missing.length && missing.every((m) => m.item && m.item.on_list);
    html += `<div style="margin-top:16px">${!missing.length
      ? `<div class="alert good">${icon("check")}<div class="alert-body"><h3>Tem tudo em casa para este plano</h3></div></div>`
      : allRequested
        ? `<div class="alert warn">${icon("cart")}<div class="alert-body"><h3>O que falta já está na lista de compras</h3></div></div>`
        : `<div class="alert">${icon("alert")}<div class="alert-body"><h3>Falta comprar ${plural(missing.length, "item", "itens")}</h3>
            <p>${missing.map((m) => esc(m.name)).join(", ")}</p>
            <button class="btn danger small" data-action="plan-request" type="button">${icon("cart", "sm")}Pedir o que falta</button></div></div>`}</div>`;
    if (plan.warnings.length) {
      html += `<div class="alert warn">${icon("clock")}<div class="alert-body"><h3>Validade</h3>
        <ul class="warn-list">${plan.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div></div>`;
    }
    html += `<h3>Dieta da semana</h3><div class="card box">${plan.checks.map((c) => `
      <div class="check-row"><span class="mark ${c.ok ? "ok" : "no"}">${icon(c.ok ? "check" : "alert")}</span>
        <span>${esc(c.label)}<small>${esc(c.hint)}</small></span></div>`).join("")}</div>`;
  }

  $("#plan-body").innerHTML = html;
  $("#plan-actions").innerHTML = state.planMode === "new"
    ? `${plan.options > 1 ? `<button class="btn secondary" data-action="plan-other" type="button">${icon("shuffle", "sm")}Outra opção</button>` : ""}
       <button class="btn primary" data-action="plan-save" type="button">${icon("check", "sm")}Usar este plano</button>`
    : `<button class="btn secondary" data-action="new-plan" type="button">${icon("shuffle", "sm")}Fazer novo plano</button>`;
}

async function savePlan() {
  try {
    const { plan } = await api("POST", "/api/plan", { plan: state.plan });
    state.savedPlan = plan;
    state.todayDay = null;
    closePlan();
    refreshWeekStatus();
    toast("Plano da semana salvo");
  } catch (e) { toast(e.message); }
}

function requestPlanMissing() {
  const missing = planMissing(state.plan).filter((m) => !(m.item && m.item.on_list));
  addManyToList(missing.map(({ name, note, category }) => ({ name, note, category })),
    `${plural(missing.length, "item pedido", "itens pedidos")} para a semana`);
}

// ---------------------------------------------------------------- Ações

function setView(view) {
  transition(() => {
    if (state.view !== view) {
      $("#stock-search").value = "";
      state.stockCat = null;
    }
    state.view = view;
    if (!isStockView() && state.editStock) setEditStock(false);
    $("#view-dishes").hidden = view !== "dishes";
    $("#view-stock").hidden = !isStockView();
    $("#view-list").hidden = view !== "list";
    $("#page-title").textContent = VIEW_TITLE[view];
    for (const t of document.querySelectorAll(".tabbar [role=tab]")) {
      t.setAttribute("aria-selected", t.dataset.view === view);
    }
    window.scrollTo(0, 0);
    render();
  });
  if (view === "dishes") loadDishes();
}

function setLevel(item, level) {
  if (item.level === level) return;
  const msg = level === "ok"
    ? `${item.name}: tem em casa${item.on_list ? " — saiu da lista" : ""}`
    : `${item.name}: ${level === "out" ? "acabou" : "está acabando"}${item.on_list ? "" : " — foi para a lista"}`;
  patch(item, { level }, { toastMsg: msg });
}

function addToList(item) {
  patch(item, { on_list: true }, { toastMsg: `${item.name} na lista` });
}

async function finishShopping() {
  const bought = state.items.filter((i) => i.on_list && i.in_cart).map((i) => ({ ...i }));
  if (!bought.length) return;
  try {
    const data = await api("POST", "/api/list/finish");
    state.items = data.items;
    render();
    refreshWeekStatus();
    toast(`${plural(data.finished, "item guardado", "itens guardados")} no estoque`, () => bought.forEach(restore));
  } catch (e) { toast(e.message); }
}

async function shareList() {
  const items = state.items.filter((i) => i.on_list && !i.in_cart);
  if (!items.length) return toast("Tudo já está no carrinho");
  let text = "*Lista de compras*\n";
  for (const [cat, list] of grouped(items)) {
    text += `\n*${cat}*\n` + list.map((i) => `• ${i.name}${i.note ? ` — ${i.note}` : ""}`).join("\n") + "\n";
  }
  if (navigator.share) {
    try { await navigator.share({ text }); return; } catch (e) { if (e.name === "AbortError") return; }
  }
  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank");
}

// ---------------------------------------------------------------- Folha (adicionar / editar)

const sheet = { mode: "add", item: null, category: "Outros", level: "ok", forList: false };

function openSheet({ item = null, name = "", forList = false } = {}) {
  Object.assign(sheet, {
    mode: item ? "edit" : "add",
    item,
    forList,
    category: item ? item.category : state.stockCat || (state.view === "home" ? "Limpeza" : "Outros"),
    level: item ? item.level : "ok",
  });
  const original = item && !item.custom;
  $("#sheet-title").textContent = item ? item.name : forList ? "Novo item na lista" : "Novo item";
  $("#f-name").value = item ? item.name : name;
  // Itens originais: os pratos usam o nome, então não dá para renomear nem excluir.
  $("#f-name").readOnly = original;
  $("#f-name-hint").textContent = original
    ? "Item original do app: o nome não muda e ele não pode ser excluído."
    : "Use o nome do item, não a marca. Ex.: “Leite”, não “Leite Itambé”.";
  $("#f-note").value = item ? item.note : "";
  $("#f-delete").hidden = !item || original;
  $("#f-level-wrap").hidden = !item && forList;
  // Na Casa só categorias da casa; na Cozinha, só de comida; na lista, todas.
  const cats = state.categories.filter((c) =>
    forList || (item ? HOME_CATS.has(c) === HOME_CATS.has(item.category) : HOME_CATS.has(c) === (state.view === "home")));
  $("#f-cats").innerHTML = cats.map((c) =>
    `<button type="button" class="chip" data-cat="${esc(c)}" aria-pressed="${c === sheet.category}">${CAT_ICON[c] || ""} ${esc(c)}</button>`).join("");
  syncSheet();
  $("#sheet").hidden = $("#sheet-backdrop").hidden = false;
  if (!item && !name) $("#f-name").focus();
}

function syncSheet() {
  for (const b of $("#f-level").children) b.setAttribute("aria-pressed", b.dataset.level === sheet.level);
  for (const b of $("#f-cats").children) b.setAttribute("aria-pressed", b.dataset.cat === sheet.category);
  const willBeOnList = sheet.forList || sheet.level !== "ok" || (sheet.item && sheet.item.on_list && sheet.level === sheet.item.level);
  $("#f-note-wrap").hidden = !willBeOnList;
}

function closeSheet() {
  $("#sheet").hidden = $("#sheet-backdrop").hidden = true;
}

async function saveSheet(e) {
  e.preventDefault();
  const name = $("#f-name").value.trim();
  if (!name) return $("#f-name").focus();
  const note = $("#f-note-wrap").hidden ? "" : $("#f-note").value.trim();

  if (sheet.mode === "edit") {
    const changes = { category: sheet.category, level: sheet.level };
    if (sheet.item.custom) changes.name = name;
    if (!$("#f-note-wrap").hidden) changes.note = note;
    closeSheet();
    return patch(sheet.item, changes, { toastMsg: "Salvo" });
  }

  const body = { name, category: sheet.category, note };
  if (sheet.forList) body.on_list = true; else body.level = sheet.level;
  try {
    const { item, existed } = await api("POST", "/api/items", body);
    upsert(item);
    closeSheet();
    $("#stock-search").value = "";
    $("#list-add").value = "";
    render();
    refreshWeekStatus();
    toast(existed ? `${item.name} já existia — atualizado` : `${item.name} adicionado${item.on_list ? " à lista" : ""}`);
  } catch (err) { toast(err.message); }
}

// ---------------------------------------------------------------- Toast

let toastTimer;
function toast(msg, undo = null) {
  clearTimeout(toastTimer);
  $("#toast-msg").textContent = msg;
  const btn = $("#toast-undo");
  btn.hidden = !undo;
  btn.onclick = () => { $("#toast").hidden = true; undo(); };
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, undo ? 5000 : 2500);
}

// ---------------------------------------------------------------- Eventos

document.querySelector(".tabbar").addEventListener("click", (e) => {
  const tab = e.target.closest("[data-view]");
  if (tab) setView(tab.dataset.view);
});
$("#cart-bar").addEventListener("click", () => setView("list"));

// Alertas (Início e Cozinha)
for (const el of [$("#week-alert"), $("#stock-alert")]) {
  el.addEventListener("click", (e) => { if (e.target.closest('[data-action="week-request"]')) requestWeekMissing(); });
}

// Início
$("#week-card").addEventListener("click", (e) => {
  const day = e.target.closest("[data-day]");
  if (day) { state.todayDay = Number(day.dataset.day); return renderWeekCard(); }
  const btn = e.target.closest("[data-action]");
  if (btn) openPlan(btn.dataset.action === "see-plan" ? "saved" : "new");
});
$("#dish-search").addEventListener("input", renderDishes);
$("#dish-search-clear").addEventListener("click", () => {
  $("#dish-search").value = "";
  renderDishes();
});
$("#dish-list").addEventListener("click", (e) => {
  const tile = e.target.closest("[data-type]");
  if (tile) { transition(() => { state.dishType = tile.dataset.type; renderDishes(); }); return; }
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  if (btn.dataset.action === "types") { transition(() => { state.dishType = null; renderDishes(); }); return; }
  const dish = state.dishes.find((d) => d.id === btn.closest("[data-dish]").dataset.dish);
  if (btn.dataset.action === "toggle") {
    state.openDish = state.openDish === dish.id ? null : dish.id;
    renderDishes();
  }
  if (btn.dataset.action === "request") requestMissing(dish);
});

// Plano
$("#plan-back").addEventListener("click", closePlan);
$("#plan-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (!b) return;
  state.planTab = b.dataset.tab;
  renderPlan();
  $("#plan").scrollTo(0, 0);
});
$("#plan-config").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-step]");
  if (!btn) return;
  const p = btn.closest(".stepper").dataset.param, [lo, hi] = PLAN_LIMITS[p];
  state.planParams[p] = Math.max(lo, Math.min(hi, state.planParams[p] + Number(btn.dataset.step)));
  state.planVariant = 0;
  syncSteppers();
  fetchPlan();
});
$("#plan").addEventListener("click", (e) => {
  const day = e.target.closest("[data-plan-day]");
  if (day) { state.planDay = Number(day.dataset.planDay); return renderPlan(); }
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const a = btn.dataset.action;
  if (a === "plan-other") { state.planVariant++; fetchPlan(); $("#plan").scrollTo(0, 0); }
  if (a === "plan-save") savePlan();
  if (a === "plan-request") requestPlanMissing();
  if (a === "new-plan") openPlan("new");
});

// Cozinha / Casa
$("#btn-edit-stock").addEventListener("click", () => setEditStock(true));
$("#btn-edit-done").addEventListener("click", () => setEditStock(false));
$("#stock-search").addEventListener("input", renderStock);
$("#stock-search").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const raw = e.target.value.trim();
  if (raw && !state.editStock && !state.items.some((i) => key(i.name) === key(raw))) openSheet({ name: raw });
  e.target.blur();
});
$("#stock-search-clear").addEventListener("click", () => {
  $("#stock-search").value = "";
  renderStock();
});
$("#stock-list").addEventListener("click", (e) => {
  const cat = e.target.closest("[data-cat]");
  if (cat) { transition(() => { state.stockCat = cat.dataset.cat; window.scrollTo(0, 0); renderStock(); }); return; }
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const a = btn.dataset.action;
  if (a === "cats") { transition(() => { state.stockCat = null; renderStock(); }); return; }
  if (a === "add-new") return openSheet({ name: $("#stock-search").value.trim() });
  const item = byId(Number(btn.closest("[data-id]").dataset.id));
  if (a === "level") setLevel(item, btn.dataset.level);
  if (a === "edit") openSheet({ item });
  if (a === "delete") deleteItem(item);
});

// Compras
$("#shop-list").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const item = byId(Number(btn.closest("[data-id]").dataset.id));
  if (btn.dataset.action === "cart") patch(item, { in_cart: !item.in_cart });
  if (btn.dataset.action === "edit") openSheet({ item });
  if (btn.dataset.action === "unlist") patch(item, { on_list: false }, { toastMsg: `${item.name} saiu da lista` });
});
$("#list-add").addEventListener("input", renderSuggest);
$("#list-add").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const raw = e.target.value.trim();
  if (!raw) return;
  const exact = state.items.find((i) => key(i.name) === key(raw));
  if (exact) {
    if (!exact.on_list) addToList(exact);
    e.target.value = "";
    renderSuggest();
  } else {
    openSheet({ name: raw, forList: true });
  }
});
$("#list-add-clear").addEventListener("click", () => {
  $("#list-add").value = "";
  renderSuggest();
});
$("#list-suggest").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn || btn.disabled) return;
  if (btn.dataset.new) return openSheet({ name: $("#list-add").value.trim(), forList: true });
  addToList(byId(Number(btn.dataset.id)));
  $("#list-add").value = "";
  renderSuggest();
  $("#list-add").focus();
});
$("#btn-finish").addEventListener("click", finishShopping);
$("#btn-share").addEventListener("click", shareList);

// Folha
$("#sheet").addEventListener("submit", saveSheet);
$("#f-cancel").addEventListener("click", closeSheet);
$("#sheet-backdrop").addEventListener("click", closeSheet);
$("#f-delete").addEventListener("click", () => { closeSheet(); deleteItem(sheet.item); });
$("#f-level").addEventListener("click", (e) => {
  const b = e.target.closest("[data-level]");
  if (b) { sheet.level = b.dataset.level; syncSheet(); }
});
$("#f-cats").addEventListener("click", (e) => {
  const b = e.target.closest("[data-cat]");
  if (b) { sheet.category = b.dataset.cat; syncSheet(); }
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#sheet").hidden) closeSheet(); else if (state.planMode) closePlan();
});

// Sincroniza entre aparelhos (quem cozinha e quem compra veem a mesma lista).
setInterval(() => {
  if (!document.hidden && !state.pending && $("#sheet").hidden) load();
}, 8000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

const now = new Date();
const greeting = now.getHours() < 12 ? "Bom dia" : now.getHours() < 18 ? "Boa tarde" : "Boa noite";
const today = now.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
$("#hello").textContent = `${greeting} · ${today[0].toUpperCase()}${today.slice(1)}`;

const HASH_VIEW = { "#cozinha": "stock", "#casa": "home", "#compras": "list" };
if (HASH_VIEW[location.hash]) setView(HASH_VIEW[location.hash]);
load();
loadDishes().then(() => { if (location.hash === "#plano") openPlan("new"); });
