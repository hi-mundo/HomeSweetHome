"""Cardápio: lê pratos/ (catálogo de itens, panelas, pratos) e monta o plano da semana.

Não depende do banco: recebe o estoque e o histórico de planos prontos, então dá para testar
sozinho (veja test_cardapio.py).

Convenção de validade: tudo é preparado no dia 1. Algo que "dura N dias" pode ser comido
do dia 1 ao dia N. Dura 0 = só fazendo na hora (não entra em plano de semana).
"""
import heapq
import itertools
import json
import math
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path

GROUPS = ("proteína", "carboidrato", "leguminosa", "verdura")
PROTEIN_TYPES = ("bovina", "frango", "suína", "peixe", "ovo")
# Quanto trabalho um lanche/sobremesa dá: só separar no potinho, montar sem fogão, ou cozinhar.
PREPS = ("nenhum", "montar", "cozinhar")
EQUIPMENT = ("nenhum", "fogão", "forno", "pressão", "liquidificador", "micro-ondas")
DEFAULT_EMOJI = {"meal": "🍽️", "snack": "🥪", "dessert": "🍮"}
PREPAROS_FILE = "preparos.json"
INGREDIENTS_FILE = "ingredientes.json"
HOUSE_FILE = "itens-da-casa.json"
CATALOG_FILES = (INGREDIENTS_FILE, HOUSE_FILE)
LONG_LIFE = 30  # item sem "dura" no catálogo: não perecível

# Pesos da pontuação (menor é melhor). Ficam juntos para dar para calibrar.
W_MISSING = 4        # cada ingrediente que falta em casa
W_POT = 2            # cada panela diferente (mais panelas = mais trabalho)
W_DIET = 6           # cada falha de dieta (prato sem proteína/carboidrato; semana sem feijão)
# Repetição: peso de algo usado há 1, 2, 3, 4, 5 planos (semanas). Refeição não repete no mês;
# sobremesa quase; lanche só não pode repetir a semana anterior (são poucos e simples).
W_RECENT = {
    "meal": (20, 15, 10, 6, 3),
    "dessert": (12, 9, 6, 4, 2),
    "snack": (15, 5, 2, 1, 0),
}
W_REPEAT_SIDE = 3    # verdura repetida da semana passada
W_PERISHABLE = 5     # prato que dura menos de 3 dias e não congela
W_SAME_PROTEIN = 8   # cada prato além do limite com a mesma proteína (ex.: 3º de carne bovina)
W_ACTIVE_HOUR = 3    # cada hora de trabalho ativo na cozinha (só panelas das refeições)
W_LOW_KCAL = 3       # marmita abaixo de MIN_KCAL
W_HARD = 2           # panela de dificuldade "média"
W_SPOIL = 20         # porção comida depois da validade (sem poder congelar)
W_FROZEN = 1         # porção que precisa ir ao freezer
W_SAME_DAY = 30      # mesmo prato no almoço e na janta do mesmo dia
W_BACK_TO_BACK = 10  # janta de hoje = almoço de amanhã
W_SHARED_POT = 1     # almoço e janta do mesmo dia com panela em comum
EFFORT = {"nenhum": 0, "montar": 1, "cozinhar": 3}
MIN_KCAL = 550       # marmita "caprichada" (com a verdura)
SIDE_KCAL = 60       # verdura média, para estimar antes de escolher
# Roteiro do dia de cozinha: quantas coisas cabem ao mesmo tempo em cada equipamento.
CAPACITY = {"pressão": 1, "forno": 2, "fogão": 4, "liquidificador": 1, "nenhum": 9, "micro-ondas": 1}


def name_key(name: str) -> str:
    """Chave para comparar nomes: sem acento, minúscula, espaços normalizados."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "")).strip()[:60]
    return name[:1].upper() + name[1:]


def hash_key(text: str) -> float:
    """Desempate estável e sem ordem alfabética (para não favorecer sempre os mesmos nomes)."""
    return random.Random(text).random()


def half_up(x: float) -> float:
    """Arredonda para cima em meias receitas (0,5; 1; 1,5…)."""
    return math.ceil(x * 2) / 2


# ------------------------------------------------------------------ leitura

def _reader(errors):
    def read(path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{path.name}: {e}")
            return default
    return read


def load_catalog(folder: Path, categories, errors=None) -> dict:
    """Catálogo de itens (comida e casa): categoria, ícone, unidade de compra e validade."""
    errors = [] if errors is None else errors
    read = _reader(errors)
    catalog = {}
    for fname in CATALOG_FILES:
        for name, info in read(folder / fname, {}).items():
            if name.startswith("_"):
                continue
            try:
                cat = info["categoria"]
                if cat not in categories:
                    raise ValueError(f"categoria “{cat}” não existe")
                catalog[name_key(name)] = {
                    "name": clean_name(name),
                    "category": cat,
                    "emoji": str(info.get("emoji", "")),
                    "unit": str(info.get("unidade", "")),
                    "open": int(info.get("dura", LONG_LIFE)),
                    "whole": int(info.get("dura_inteiro", LONG_LIFE)),
                    "food": fname == INGREDIENTS_FILE,
                }
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                errors.append(f"{fname} ({name}): {e}")
    return catalog


def load(folder: Path, categories) -> dict:
    """Lê a pasta de pratos. Arquivos com erro viram mensagens em "errors", não exceções.

    Devolve catalog (todos os itens: comida e casa), preparos, dishes e errors.
    """
    errors = []
    read = _reader(errors)
    catalog = load_catalog(folder, categories, errors)

    def ingredient(x, where):
        if isinstance(x, str):
            x = {"item": x}
        name = clean_name(x["item"])
        if not name:
            raise ValueError("ingrediente sem nome")
        info = catalog.get(name_key(name))
        if not info:
            # Não impede o prato, mas avisa: sem cadastro não tem categoria, ícone nem validade.
            errors.append(f"{where}: “{name}” não está em {INGREDIENTS_FILE}")
        return {"name": info["name"] if info else name, "qty": str(x.get("qtd", "")).strip(),
                "category": info["category"] if info else "Outros"}

    # Validade do que é montado com ingredientes crus. Panela cozida deve declarar "dura".
    def life_of(ings, whole=False):
        return min((catalog.get(name_key(i["name"]), {}).get("whole" if whole else "open", LONG_LIFE)
                    for i in ings), default=LONG_LIFE)

    def choice(value, options, field):
        if value not in options:
            raise ValueError(f"{field} deve ser {', '.join(options)}")
        return value

    # Panelas.
    preparos = {}
    for p in read(folder / PREPAROS_FILE, []):
        try:
            name = clean_name(p["nome"])
            ings = [ingredient(x, f"{PREPAROS_FILE} ({name})") for x in p.get("ingredientes", [])]
            group = str(p.get("grupo", "")).strip().lower()
            ptype = p.get("proteina_tipo")
            preparos[name_key(name)] = {
                "name": name,
                "group": group if group in GROUPS else "",
                "protein_type": choice(ptype, PROTEIN_TYPES, "proteina_tipo") if ptype else None,
                "tip": str(p.get("dica", "")).strip(),
                "serves": max(1, int(p.get("rende", 4))),
                "life": int(p["dura"]) if "dura" in p else life_of(ings),
                "freeze": bool(p.get("congela", False)),
                "active": int(p.get("tempo_ativo", 15)),
                "total": int(p.get("tempo_total", 30)),
                "equipment": choice(p.get("equipamento", "fogão"), EQUIPMENT, "equipamento"),
                "hard": p.get("dificuldade", "fácil") != "fácil",
                # Reforço: extra que dura (farofa, ovo cozido) para marmita que ficou leve.
                "boost": bool(p.get("reforco", False)),
                "kcal": int(p.get("kcal", 0)),
                "protein_g": int(p.get("proteina_g", 0)),
                "ingredients": ings,
            }
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            errors.append(f"{PREPAROS_FILE} ({p.get('nome', '?') if isinstance(p, dict) else '?'}): {e}")

    # Pratos.
    dishes = []
    for path in sorted(folder.glob("*.json")):
        if path.name in (PREPAROS_FILE,) + CATALOG_FILES:
            continue
        data = read(path, None)
        if data is None:
            continue
        for i, d in enumerate(data if isinstance(data, list) else [data]):
            try:
                name = clean_name(d["nome"])
                used = []
                for pname in d.get("preparos", []):
                    p = preparos.get(name_key(pname))
                    if not p:
                        raise ValueError(f"preparo “{pname}” não existe em {PREPAROS_FILE}")
                    used.append(p)
                extras = [ingredient(x, path.name) for x in d.get("ingredientes", [])]
                ingredients = merge(*(p["ingredients"] for p in used), extras)
                if not name or not ingredients:
                    raise ValueError("precisa de \"nome\" e de \"preparos\" ou \"ingredientes\"")
                tipo = str(d.get("tipo", "refeição")).strip().lower()
                kind = "snack" if tipo.startswith("lanche") else "dessert" if tipo.startswith("sobremesa") else "meal"
                prep = choice(str(d.get("preparo", "")).strip().lower()
                              or ("cozinhar" if used or kind == "meal" else "montar"), PREPS, "preparo")
                # Validade: a menor entre as panelas e os extras (inteiros, se é só separar).
                life = int(d["dura"]) if "dura" in d else min(
                    [p["life"] for p in used] + [life_of(extras, whole=prep == "nenhum")])
                freeze = bool(d.get("congela", bool(used) and all(p["freeze"] for p in used)))
                protein_types = [p["protein_type"] for p in used if p["protein_type"]]
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                errors.append(f"{path.name} (prato {i + 1}): {e}")
                continue
            dishes.append({
                "id": f"{path.stem}-{i}",
                "name": name,
                "type": kind,
                "prep": prep,
                "life": life,
                "freeze": freeze,
                "serves": max(1, int(d.get("rende", 6 if kind == "dessert" else 1))),
                "emoji": str(d.get("emoji", "") or DEFAULT_EMOJI[kind]),
                "preparos": [p["name"] for p in used],
                "groups": sorted({p["group"] for p in used if p["group"]}),
                # Metadados: o prato herda das panelas, a menos que declare os seus.
                "kcal": int(d.get("kcal", sum(p["kcal"] for p in used))),
                "protein_g": int(d.get("proteina_g", sum(p["protein_g"] for p in used))),
                "protein_type": protein_types[0] if protein_types else None,
                "active": int(d.get("tempo_ativo", sum(p["active"] for p in used))),
                "total": int(d.get("tempo_total", max((p["total"] for p in used), default=0))),
                "equipment": d.get("equipamento", "nenhum"),
                "hard": any(p["hard"] for p in used),
                "ingredients": ingredients,
                "optional": [ingredient(x, path.name) for x in d.get("opcionais", [])],
            })
    dishes.sort(key=lambda d: name_key(d["name"]))
    return {"dishes": dishes, "preparos": list(preparos.values()), "catalog": catalog,
            "errors": list(dict.fromkeys(errors))}


def merge(*lists) -> list:
    """Junta listas de ingredientes sem repetir nomes (fica a primeira ocorrência)."""
    seen, out = set(), []
    for ing in itertools.chain(*lists):
        k = name_key(ing["name"])
        if k not in seen:
            seen.add(k)
            out.append(ing)
    return out


def all_ingredients(data: dict) -> list:
    """Todos os ingredientes citados nos pratos e panelas."""
    return merge(*(p["ingredients"] for p in data["preparos"]),
                 *(d["ingredients"] + d["optional"] for d in data["dishes"]))


def pots_planned(slots) -> set:
    return {p for _, _, d in slots for p in d["preparos"]}


def cooking_schedule(tasks: list) -> dict:
    """Roteiro do dia de cozinha: começa pelo que demora sem precisar de atenção.

    tasks: [{"name", "active", "total", "equipment"}] em minutos. Quem cozinha faz uma coisa
    ativa por vez; cada equipamento tem uma capacidade (uma panela de pressão, forno para 2…).
    """
    cook_free = 0
    busy = {eq: [0] * cap for eq, cap in CAPACITY.items()}
    steps = []
    # Mais tempo "sozinho" (pressão, forno) primeiro; o que é só trabalho fica para o fim.
    for t in sorted(tasks, key=lambda t: (-(t["total"] - t["active"]), -t["total"], t["name"])):
        slots = busy[t["equipment"]]
        slot = min(range(len(slots)), key=lambda i: slots[i])
        start = max(cook_free, slots[slot])
        cook_free = start + t["active"]
        slots[slot] = start + max(t["total"], t["active"])
        steps.append({**t, "start": start, "end": start + max(t["total"], t["active"])})
    steps.sort(key=lambda s: (s["start"], s["name"]))
    return {
        "steps": steps,
        "active": sum(t["active"] for t in tasks),
        "end": max((s["end"] for s in steps), default=0),
    }


# ------------------------------------------------------------------ plano

def suggest_plan(data: dict, stock: list, history: list,
                 n_days: int, n_desserts: int, variant: int = 0) -> dict:
    """Plano da semana: por dia, almoço + sobremesa + lanche da tarde + janta.

    stock: [{"name", "category", "level"}]. history: planos salvos recentes, do mais novo para o
    mais antigo (~1 mês); o que foi comido recentemente perde prioridade, mais quanto mais recente.
    Etapas:
      1. escolher os pratos (n_days diferentes, 2 marmitas de cada);
      2. distribuir nos dias (validade, freezer, não repetir);
      3. verduras por refeição (respeitando a validade de cada uma);
      4. sobremesas (até 2 tipos, avaliadas em par com a distribuição);
      5. lanches (1 por dia, os perecíveis primeiro);
      6. panelas (porções, receitas, a partir de que dia congelar) e roteiro do dia de cozinha;
      7. checklist da dieta e avisos.
    """
    level = {name_key(s["name"]): s["level"] for s in stock}
    preparos = {p["name"]: p for p in data["preparos"]}
    used_in = [{x["id"] for k in ("meals", "snacks", "desserts") for x in p.get(k, [])}
               for p in history[:5]]
    last_sides = set(history[0].get("sides", [])) if history else set()

    def recency(d):
        return max((W_RECENT[d["type"]][i] for i, ids in enumerate(used_in) if d["id"] in ids), default=0)
    rand = lambda *parts: random.Random(":".join(map(str, (variant,) + parts))).random()

    def missing(ings):
        return {name_key(i["name"]) for i in ings if level.get(name_key(i["name"]), "out") == "out"}

    def dish_missing(dishes):
        return missing([i for d in dishes for i in d["ingredients"]])

    warnings = []

    # 1. Pratos ----------------------------------------------------------------
    meals = [d for d in data["dishes"] if d["type"] == "meal"]
    n = max(1, min(n_days, len(meals))) if meals else 0
    max_uses = max(2, math.ceil(n / 2))
    same_protein_limit = max(2, math.ceil(n / 3))

    # Tudo que não depende da combinação é calculado uma vez por prato (são dezenas de
    # milhares de combinações).
    def alone_cost(d):
        diet = ("proteína" not in d["groups"]) + ("carboidrato" not in d["groups"])
        return (W_DIET * diet + recency(d) + W_PERISHABLE * (d["life"] < 3 and not d["freeze"])
                + W_LOW_KCAL * (d["kcal"] + SIDE_KCAL < MIN_KCAL) + W_HARD * d["hard"])

    fixed = {d["id"]: (frozenset(dish_missing([d])), alone_cost(d), "leguminosa" in d["groups"], d["protein_type"])
             for d in meals}

    def combo_score(combo):
        uses = Counter(p for d in combo for p in d["preparos"])
        if uses and max(uses.values()) > max_uses:
            return None
        info = [fixed[d["id"]] for d in combo]
        missing_all = frozenset().union(*(i[0] for i in info))
        no_beans = not any(i[2] for i in info)
        proteins = Counter(i[3] for i in info if i[3])
        same_protein = sum(max(0, c - same_protein_limit) for c in proteins.values())
        active_hours = sum(preparos[p]["active"] for p in uses) / 60
        return (W_MISSING * len(missing_all) + W_POT * len(uses) + W_DIET * no_beans
                + W_SAME_PROTEIN * same_protein + W_ACTIVE_HOUR * active_hours + sum(i[1] for i in info))

    best = []  # heap com as 8 melhores: (-pontos, ids)

    def consider(combo):
        s = combo_score(combo)
        if s is None:
            return
        entry = (-s, tuple(sorted(d["id"] for d in combo)))
        if entry in best:
            return
        if len(best) < 8:
            heapq.heappush(best, entry)
        elif entry > best[0]:
            heapq.heapreplace(best, entry)

    # Pré-seleção: os ~18 pratos mais promissores sozinhos (tem em casa, não comido há pouco,
    # dieta ok). Entre eles, testa todas as combinações (no máx. C(18,7) ≈ 32 mil).
    pool = sorted(meals, key=lambda d: (W_MISSING * len(fixed[d["id"]][0]) + fixed[d["id"]][1],
                                        hash_key(d["id"])))[:max(18, n + 10)]
    for combo in itertools.combinations(pool, n):
        consider(combo)

    options = sorted(best, reverse=True)
    by_id = {d["id"]: d for d in data["dishes"]}
    chosen = [by_id[i] for i in options[variant % len(options)][1]] if options else []

    # 2. Dias ------------------------------------------------------------------
    # Prato k da ordem vai no almoço do dia k e na janta do dia k - shift. Testa todas as
    # ordens (no máx. 7! = 5040) e todos os deslocamentos; fica com a de menor custo.
    def meal_cost(dish, day):
        if day <= dish["life"]:
            return 0
        return W_FROZEN if dish["freeze"] else W_SPOIL

    def schedule_cost(order, shift):
        c, m = 0, len(order)
        for i in range(n_days):
            lunch, dinner = order[i % m], order[(i + shift) % m]
            c += meal_cost(lunch, i + 1) + meal_cost(dinner, i + 1)
            c += W_SAME_DAY * (lunch is dinner)
            c += W_SHARED_POT * len(set(lunch["preparos"]) & set(dinner["preparos"]))
            if i + 1 < n_days and dinner is order[(i + 1) % m]:
                c += W_BACK_TO_BACK
        return c

    order, shift = list(chosen), 0
    if chosen:
        # Ordem alfabética como desempate, para o resultado não depender de detalhes do heap.
        base = sorted(chosen, key=lambda d: d["name"])
        shifts = range(1, len(base)) if len(base) > 1 else [0]
        order, shift = min(((list(p), s) for p in itertools.permutations(base) for s in shifts),
                           key=lambda ps: schedule_cost(*ps))

    slots = []  # (dia, "lunch"|"dinner", prato)
    for i in range(n_days if chosen else 0):
        slots.append((i + 1, "lunch", order[i % len(order)]))
        slots.append((i + 1, "dinner", order[(i + shift) % len(order)]))

    # 3. Verduras ----------------------------------------------------------------
    # Prato sem verdura ganha uma. Escolhe ~1 verdura a cada 2 pratos e garante que pelo
    # menos uma aguenta até o último dia; cada refeição recebe a menos usada que ainda vale.
    # Verdura que dura mais que uma semana é congelada/industrializada: só entra se as frescas
    # não aguentarem até o fim.
    side_pool = sorted((p for p in data["preparos"] if p["group"] == "verdura"),
                       key=lambda p: (W_MISSING * len(missing(p["ingredients"])) + W_REPEAT_SIDE * (p["name"] in last_sides)
                                      + 10 * (p["life"] > 7), rand("side", p["name"])))
    needs_side = [s for s in slots if not any(preparos[p]["group"] == "verdura" for p in s[2]["preparos"])]
    k = min(len(side_pool), max(2, math.ceil(n / 2))) if needs_side else 0
    sides = side_pool[:k]
    if sides and max(p["life"] for p in sides) < n_days:
        lasting = sorted((p for p in side_pool if p["life"] >= n_days), key=lambda p: p["life"])
        if lasting:
            sides[-1] = lasting[0]
    side_use = Counter()
    side_at = {}
    for day, meal_slot, _ in needs_side:
        ok = [p for p in sides if p["life"] >= day] or sorted(sides, key=lambda p: -p["life"])[:1]
        lunch_side = side_at.get((day, "lunch")) if meal_slot == "dinner" else None
        pick = min(ok, key=lambda p: (side_use[p["name"]], p["name"] == lunch_side, sides.index(p)))
        side_use[pick["name"]] += 1
        side_at[(day, meal_slot)] = pick["name"]
    # Verdura que ficou com uma porção só não vale uma panela: passa a refeição para outra.
    for name in [nm for nm, c in side_use.items() if c == 1]:
        slot = next(s for s, nm in side_at.items() if nm == name)
        alt = [p for p in sides if p["name"] != name and p["life"] >= slot[0] and side_use[p["name"]] > 1]
        if alt:
            side_at[slot] = alt[0]["name"]
            side_use[alt[0]["name"]] += 1
            del side_use[name]
    sides = [p for p in sides if side_use[p["name"]]]
    for (day, _), name in side_at.items():
        life = preparos[name]["life"]
        if day > life:
            warnings.append(f"{name} do dia {day} passa da validade ({life} dias): faça na hora.")

    # Reforço: marmita abaixo de MIN_KCAL ganha um extra que dura (farofa, ovo cozido),
    # de preferência um que já vai ser feito.
    def slot_kcal(day, meal_slot, d):
        extras = [side_at.get((day, meal_slot)), boost_at.get((day, meal_slot))]
        return d["kcal"] + sum(preparos[x]["kcal"] for x in extras if x)

    boosts = [p for p in data["preparos"] if p["boost"] and not missing(p["ingredients"])]
    boost_at = {}
    for day, meal_slot, d in slots:
        if slot_kcal(day, meal_slot, d) >= MIN_KCAL:
            continue
        valid = [b for b in boosts if b["life"] >= day and b["name"] not in d["preparos"]]
        if valid:
            in_use = set(boost_at.values()) | pots_planned(slots)
            boost_at[(day, meal_slot)] = min(valid, key=lambda b: (b["name"] not in in_use, -b["kcal"]))["name"]

    # 4/5. Sobremesas e lanches ------------------------------------------------------
    pots_used = {p for d in chosen for p in d["preparos"]}

    def light_score(d):
        # Reaproveitar panela dos pratos é bom; abrir panela nova só para um lanche, não.
        return (W_MISSING * len(dish_missing([d])) + recency(d) + EFFORT[d["prep"]]
                - W_POT * len(pots_used & set(d["preparos"])) + 2 * W_POT * len(set(d["preparos"]) - pots_used))

    def spoiled(assignment):  # assignment: lista dia->prato
        return sum(day > d["life"] for day, d in enumerate(assignment, 1))

    desserts_pool = sorted((d for d in data["dishes"] if d["type"] == "dessert"),
                           key=lambda d: (light_score(d), rand("dessert", d["id"])))
    t = min(n_desserts, len(desserts_pool), n_days)
    dessert_days = []
    if t:
        # Avalia cada conjunto (todos os pares; são poucos) já com a melhor distribuição:
        # alternado (A B A B…) ou em bloco (A A A B B), com o que estraga antes primeiro.
        def patterns(group):
            if len(group) == 1:
                return [[group[0]] * n_days]
            a, b = sorted(group, key=lambda d: d["life"])
            half = math.ceil(n_days / 2)
            return [[(a, b)[i % 2] for i in range(n_days)], [(b, a)[i % 2] for i in range(n_days)],
                    [a] * half + [b] * (n_days - half), [a] * (n_days - half) + [b] * half]
        # Duas compradas prontas (paçoca, cocada…) gastam as que duram e nada é feito em casa:
        # o par ideal é uma caseira (mousse, pudim) no começo + uma que dura no fim.
        candidates = []
        for group in itertools.combinations(desserts_pool, t):
            store_bought = 4 * (t == 2 and all(d["prep"] == "nenhum" for d in group))
            for pat in patterns(group):
                candidates.append((W_SPOIL * spoiled(pat) + sum(light_score(d) for d in group) + store_bought, pat))
        dessert_days = min(candidates, key=lambda c: c[0])[1]
    desserts = list({d["id"]: d for d in dessert_days}.values())  # na ordem em que aparecem

    # Lanches: do último dia para o primeiro, o melhor que ainda vale naquele dia, sem
    # repetir enquanto der. Assim os perecíveis sobram para o começo da semana.
    snack_pool = sorted((d for d in data["dishes"] if d["type"] == "snack"),
                        key=lambda d: (light_score(d) + 3 * (d["life"] <= 2), rand("snack", d["id"])))
    snack_days = [None] * n_days
    used = set()
    for day in range(n_days, 0, -1):
        valid = [d for d in snack_pool if d["life"] >= day]
        pick = next((d for d in valid if d["id"] not in used), valid[0] if valid else None)
        if pick is None and snack_pool:
            pick = snack_pool[0]
            warnings.append(f"Nenhum lanche aguenta até o dia {day}; {pick['name']} precisa ser feito na hora.")
        if pick:
            used.add(pick["id"])
            snack_days[day - 1] = pick
    snacks = sorted({d["id"]: d for d in snack_days if d}.values(),
                    key=lambda d: snack_days.index(d))

    for day, d in enumerate(dessert_days, 1):
        if day > d["life"]:
            warnings.append(f"{d['name']} no dia {day} passa da validade ({d['life']} dias).")

    # 6. Panelas e roteiro ------------------------------------------------------------
    pot_days = {}  # panela -> lista de dias em que é comida (uma entrada por porção)
    pot_users = {}

    def eat(pot, day, who):
        pot_days.setdefault(pot, []).append(day)
        pot_users.setdefault(pot, [])
        if who not in pot_users[pot]:
            pot_users[pot].append(who)

    for day, meal_slot, d in slots:
        for p in d["preparos"]:
            eat(p, day, d["name"])
        for extra in (side_at.get((day, meal_slot)), boost_at.get((day, meal_slot))):
            if extra:
                eat(extra, day, d["name"])
    for assignment in (dessert_days, snack_days):
        for day, d in enumerate(assignment, 1):
            for p in (d["preparos"] if d else []):
                eat(p, day, d["name"])

    pots = []
    for name, days in pot_days.items():
        p = preparos[name]
        late = sorted(d for d in days if d > p["life"])
        pots.append({
            "name": name,
            "portions": len(days),
            "factor": half_up(len(days) / p["serves"]),
            "serves": p["serves"],
            "group": p["group"],
            "tip": p["tip"],
            "life": p["life"],
            "freeze": p["freeze"],
            "freeze_from": late[0] if late and p["freeze"] else None,
            "equipment": p["equipment"],
            "active": p["active"],
            "total": p["total"],
            "used_by": pot_users[name],
            "ingredients": p["ingredients"],
        })
    pots.sort(key=lambda p: (-len(p["used_by"]), p["name"]))

    # Mais de uma receita: um pouco mais de trabalho (não o dobro: corta tudo de uma vez).
    def scaled(name, active, total, equipment, factor, kind):
        extra = max(0, math.ceil(factor) - 1)
        return {"name": name, "kind": kind, "equipment": equipment,
                "active": round(active * (1 + 0.25 * extra)), "total": total + 10 * extra}

    tasks = [scaled(p["name"], p["active"], p["total"], p["equipment"], p["factor"], "panela")
             for p in pots if p["total"] > 0 and p["equipment"] != "micro-ondas"]
    for d in desserts + snacks:
        if d["prep"] != "nenhum" and not d["preparos"] and d["total"] > 0:
            factor = half_up(sum(x is d for x in dessert_days + snack_days) / d["serves"])
            tasks.append(scaled(d["name"], d["active"], d["total"], d["equipment"], max(1, factor),
                                "sobremesa" if d["type"] == "dessert" else "lanche"))
    schedule = cooking_schedule(tasks)

    # Marmitas que passam da validade e não congelam.
    for day, meal_slot, d in slots:
        if day > d["life"] and not d["freeze"]:
            warnings.append(f"{d['name']} no dia {day} passa da validade ({d['life']} dias).")

    # Frutas: cortadas só para os dias em que ainda ficam boas; depois, inteiras.
    fruits = [s["name"] for s in stock if s["category"] == "Frutas" and s["level"] != "out"]
    cut_life = {f: data["catalog"].get(name_key(f), {}).get("open", LONG_LIFE) for f in fruits}

    # 7. Checklist ----------------------------------------------------------------
    def has(day, meal_slot, d, group):
        extras = [side_at.get((day, meal_slot)), boost_at.get((day, meal_slot))]
        return any(preparos[p]["group"] == group for p in d["preparos"] + [x for x in extras if x])

    proteins = Counter(d["protein_type"] for d in order if d["protein_type"])
    checks = [
        {"label": "Proteína em todo prato", "hint": "aminoácidos e músculo",
         "ok": all(has(*s, "proteína") for s in slots)},
        {"label": "Carboidrato em todo prato", "hint": "energia e calorias",
         "ok": all(has(*s, "carboidrato") for s in slots)},
        {"label": f"Marmitas caprichadas ({MIN_KCAL}+ kcal)", "hint": "comida que sustenta o dia",
         "ok": all(slot_kcal(*s) >= MIN_KCAL for s in slots)},
        {"label": "Proteínas variadas", "hint": ", ".join(f"{c}× {t}" for t, c in proteins.most_common()) or "—",
         "ok": not proteins or max(proteins.values()) <= same_protein_limit},
        {"label": "Salada ou legume em todo prato", "hint": "fibras, vitaminas e minerais",
         "ok": all(has(*s, "verdura") for s in slots)},
        {"label": "Feijão, lentilha ou grão-de-bico na semana", "hint": "fibra e ferro; com milho/cuscuz completa os aminoácidos",
         "ok": any(has(*s, "leguminosa") for s in slots)},
        {"label": "Frutas em casa (2 ou mais)", "hint": "vitamina C e fibras — para a tarde",
         "ok": len(fruits) >= 2},
        {"label": "Nada passa da validade", "hint": "perecíveis no começo da semana; o resto no freezer",
         "ok": not warnings},
    ]

    def meal_slot_out(day, meal_slot, d):
        return {"id": d["id"], "side": side_at.get((day, meal_slot)), "boost": boost_at.get((day, meal_slot)),
                "frozen": day > d["life"] and d["freeze"], "kcal": slot_kcal(day, meal_slot, d)}

    def light_out(d, assignment):
        portions = sum(x is d for x in assignment)
        return {"id": d["id"], "name": d["name"], "emoji": d["emoji"], "prep": d["prep"], "life": d["life"],
                "kcal": d["kcal"], "portions": portions,
                # Sobremesa se faz inteira (um mousse dura a semana); lanche pode ser meia receita.
                "factor": None if d["prep"] == "nenhum"
                else max(1.0 if d["type"] == "dessert" else 0.5, half_up(portions / d["serves"]))}

    day_out = []
    for i in range(len(slots) // 2):
        (day, _, lunch), (_, _, dinner) = slots[2 * i], slots[2 * i + 1]
        lunch_out, dinner_out = meal_slot_out(day, "lunch", lunch), meal_slot_out(day, "dinner", dinner)
        dessert = dessert_days[i] if dessert_days else None
        snack = snack_days[i]
        day_out.append({
            "lunch": lunch_out,
            "dinner": dinner_out,
            "dessert": dessert["id"] if dessert else None,
            "snack": snack["id"] if snack else None,
            # Frutas que aguentam cortadas até este dia; as outras ficam inteiras.
            "fruit_cut": [f for f in fruits if day <= cut_life[f]],
            "kcal": lunch_out["kcal"] + dinner_out["kcal"] + (dessert["kcal"] if dessert else 0)
            + (snack["kcal"] if snack else 0),
        })

    users = order + desserts + snacks
    return {
        "params": {"days": n_days, "desserts": n_desserts},
        "variant": variant,
        "options": len(options),
        "days": day_out,
        "meals": [{"id": d["id"], "name": d["name"], "emoji": d["emoji"], "life": d["life"], "freeze": d["freeze"],
                   "kcal": d["kcal"], "protein_g": d["protein_g"], "protein_type": d["protein_type"],
                   "portions": sum(s[2] is d for s in slots), "preparos": d["preparos"]} for d in order],
        "desserts": [light_out(d, dessert_days) for d in desserts],
        "snacks": [light_out(d, snack_days) for d in snacks],
        "sides": [p["name"] for p in sides],
        "pots": pots,
        "schedule": schedule,
        "fruits": fruits,
        "checks": checks,
        "warnings": list(dict.fromkeys(warnings)),
        "ingredients": merge(*(p["ingredients"] for p in pots), *(d["ingredients"] for d in users)),
    }
