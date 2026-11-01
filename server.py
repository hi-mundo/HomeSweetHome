#!/usr/bin/env python3
"""Home Sweet Home: estoque genérico, pratos, plano da semana e lista de compras da casa.

Servidor sem dependências (stdlib + SQLite). Rode com:
    python3 server.py            # porta 8080
    PORT=9000 python3 server.py
"""
import json
import os
import re
import sqlite3
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cardapio
from cardapio import clean_name, name_key

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DISHES_DIR = Path(os.environ.get("LAR_PRATOS", BASE / "pratos"))
DB_PATH = Path(os.environ.get("LAR_DB", BASE / "data" / "lar.db"))
PORT = int(os.environ.get("PORT", "8080"))

LEVELS = ("ok", "low", "out")
CATEGORIES = (
    "Hortifruti", "Frutas", "Carnes e ovos", "Laticínios e frios", "Padaria",
    "Despensa", "Lanches", "Temperos", "Bebidas", "Congelados", "Outros",
    "Limpeza", "Utensílios", "Higiene",
)
DEFAULT_PLAN = {"days": 5, "desserts": 2}

_lock = threading.Lock()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_dishes() -> dict:
    return cardapio.load(DISHES_DIR, CATEGORIES)


_catalog_cache = {"stamp": None, "data": {}}


def catalog() -> dict:
    """Catálogo de itens (ícone, unidade…), relido só quando os arquivos mudam."""
    files = [DISHES_DIR / f for f in cardapio.CATALOG_FILES]
    stamp = tuple(f.stat().st_mtime if f.exists() else 0 for f in files)
    if stamp != _catalog_cache["stamp"]:
        _catalog_cache.update(stamp=stamp, data=cardapio.load_catalog(DISHES_DIR, CATEGORIES))
    return _catalog_cache["data"]


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                name_key TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL DEFAULT 'Outros',
                level TEXT NOT NULL DEFAULT 'ok',
                on_list INTEGER NOT NULL DEFAULT 0,
                in_cart INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                custom INTEGER NOT NULL DEFAULT 1,
                last_bought_at REAL,
                updated_at REAL NOT NULL
            )"""
        )
        if "custom" not in {r["name"] for r in conn.execute("PRAGMA table_info(items)")}:
            conn.execute("ALTER TABLE items ADD COLUMN custom INTEGER NOT NULL DEFAULT 1")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                data TEXT NOT NULL
            )"""
        )
        if conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            # Primeira vez: todo o catálogo entra como "tem"; quem cozinha ajusta o que falta.
            now = time.time()
            conn.executemany(
                "INSERT INTO items (name, name_key, category, custom, updated_at) VALUES (?, ?, ?, 0, ?)",
                [(c["name"], k, c["category"], now) for k, c in catalog().items()],
            )
        sync_originals(conn, load_dishes())


def sync_originals(conn, data: dict) -> None:
    """Garante que o estoque tem todos os itens originais (catálogo + ingredientes dos pratos).

    Os que faltam entram como "acabou"; um item personalizado com o mesmo nome de um
    ingrediente passa a ser original (não pode mais ser excluído nem renomeado).
    """
    now = time.time()
    originals = [(c["name"], c["category"]) for c in data["catalog"].values()]
    originals += [(i["name"], i["category"]) for i in cardapio.all_ingredients(data)]
    for name, cat in originals:
        cur = conn.execute("UPDATE items SET custom = 0 WHERE name_key = ? AND custom = 1", (name_key(name),))
        if not cur.rowcount and not conn.execute("SELECT 1 FROM items WHERE name_key = ?", (name_key(name),)).fetchone():
            conn.execute(
                """INSERT INTO items (name, name_key, category, level, custom, updated_at)
                   VALUES (?, ?, ?, 'out', 0, ?)""",
                (name, name_key(name), cat, now),
            )


def row(r: sqlite3.Row) -> dict:
    d = dict(r)
    info = catalog().get(d.pop("name_key"), {})
    d["emoji"] = info.get("emoji", "")
    d["unit"] = info.get("unit", "")
    for k in ("on_list", "in_cart", "custom"):
        d[k] = bool(d[k])
    return d


def all_items(conn) -> list:
    return [row(r) for r in conn.execute("SELECT * FROM items ORDER BY name COLLATE NOCASE")]


def last_plan(conn):
    r = conn.execute("SELECT * FROM plans ORDER BY id DESC LIMIT 1").fetchone()
    return {**json.loads(r["data"]), "saved_at": r["created_at"]} if r else None


def recent_plans(conn, days: int = 35) -> list:
    """Planos salvos nas últimas ~5 semanas, do mais novo para o mais antigo."""
    since = time.time() - days * 86400
    return [json.loads(r["data"]) for r in conn.execute(
        "SELECT data FROM plans WHERE created_at >= ? ORDER BY id DESC", (since,))]


def suggest(conn, data: dict, days: int, desserts: int, variant: int) -> dict:
    stock = [dict(r) for r in conn.execute("SELECT name, category, level FROM items")]
    return cardapio.suggest_plan(data, stock, recent_plans(conn), days, desserts, variant)


def week_status(conn) -> dict:
    """O estoque dá para a semana?

    Com um plano salvo em andamento, confere o que esse plano precisa. Sem plano, usa como
    referência o melhor plano possível (o que pede menos compras): o que falta para ele é o
    mínimo a comprar para ter uma semana de comida.
    """
    saved = last_plan(conn)
    active = saved and time.time() - saved["saved_at"] < (len(saved.get("days", [])) + 2) * 86400
    if active:
        plan = saved
    else:
        params = {**DEFAULT_PLAN, **((saved or {}).get("params") or {})}
        plan = suggest(conn, load_dishes(), params["days"], params["desserts"], 0)
    level = {name_key(r["name"]): (r["level"], r["on_list"])
             for r in conn.execute("SELECT name, level, on_list FROM items")}
    qty = {}
    for pot in plan["pots"]:
        for ing in pot["ingredients"]:
            if ing["qty"]:
                qty.setdefault(name_key(ing["name"]), ing["qty"] if pot["factor"] == 1
                               else f"{ing['qty']} × {str(pot['factor']).replace('.', ',')}")
    missing, low = [], []
    for ing in plan["ingredients"]:
        lvl, on_list = level.get(name_key(ing["name"]), ("out", 0))
        entry = {"name": ing["name"], "note": qty.get(name_key(ing["name"]), ""),
                 "category": ing["category"], "on_list": bool(on_list)}
        if lvl == "out":
            missing.append(entry)
        elif lvl == "low":
            low.append(entry)
    return {
        "source": "saved" if active else "suggested",
        "days": len(plan["days"]),
        "missing": missing,
        "low": low,
        "warnings": plan.get("warnings", []),
        "ok": not missing and not plan.get("warnings"),
    }


def apply_changes(current: dict, data: dict) -> dict:
    """Aplica campos editáveis + regras de negócio entre estoque e lista."""
    out = {}
    if "name" in data:
        name = clean_name(data["name"])
        if not name:
            raise ValueError("Nome vazio")
        if current and not current.get("custom", 1) and name_key(name) != current["name_key"]:
            raise ValueError("Item original não pode ser renomeado (os pratos usam esse nome)")
        out["name"], out["name_key"] = name, name_key(name)
    if "category" in data:
        out["category"] = data["category"] if data["category"] in CATEGORIES else "Outros"
    if "note" in data:
        out["note"] = str(data["note"] or "").strip()[:80]
    if "on_list" in data:
        out["on_list"] = int(bool(data["on_list"]))
        if not out["on_list"]:
            out["in_cart"] = 0
            out["note"] = ""
    if "in_cart" in data:
        out["in_cart"] = int(bool(data["in_cart"]))
    if "level" in data:
        level = data["level"]
        if level not in LEVELS:
            raise ValueError("Nível inválido")
        out["level"] = level
        # Acabando/acabou entra na lista; marcar "tem" tira (se não veio on_list explícito).
        if "on_list" not in data and level != current.get("level"):
            out["on_list"] = 0 if level == "ok" else 1
            if level == "ok":
                out["in_cart"], out["note"] = 0, ""
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt, *args):  # silencioso, exceto erros
        if not str(args[1] if len(args) > 1 else "").startswith(("2", "3")):
            super().log_message(fmt, *args)

    def end_headers(self):
        if self.path.startswith("/api/") or self.path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def item_id(self):
        m = re.fullmatch(r"/api/items/(\d+)", self.path)
        return int(m.group(1)) if m else None

    # --- rotas -------------------------------------------------------------
    def do_GET(self):
        if self.path == "/api/items":
            with db() as conn:
                return self.send_json({"items": all_items(conn), "categories": CATEGORIES})
        if self.path == "/api/dishes":
            data = load_dishes()
            with _lock, db() as conn:
                sync_originals(conn, data)  # a pasta pode ter ganhado pratos novos
            return self.send_json({"dishes": data["dishes"], "errors": data["errors"]})
        if self.path == "/api/plan":
            with db() as conn:
                return self.send_json({"plan": last_plan(conn)})
        if self.path == "/api/week-status":
            with db() as conn:
                return self.send_json(week_status(conn))
        return super().do_GET()

    def do_POST(self):
        try:
            data = self.read_json()
        except json.JSONDecodeError:
            return self.send_json({"error": "JSON inválido"}, 400)

        if self.path == "/api/items":
            name = clean_name(data.get("name", ""))
            if not name:
                return self.send_json({"error": "Informe um nome"}, 400)
            with _lock, db() as conn:
                existing = conn.execute("SELECT * FROM items WHERE name_key = ?", (name_key(name),)).fetchone()
                if existing:
                    # Mesmo item genérico já existe: só atualiza estado em vez de duplicar.
                    changes = apply_changes(dict(existing), {k: v for k, v in data.items() if k != "name"})
                    self._update(conn, existing["id"], changes)
                    item = conn.execute("SELECT * FROM items WHERE id = ?", (existing["id"],)).fetchone()
                    return self.send_json({"item": row(item), "existed": True})
                fields = {"name": name, "level": "ok", "category": "Outros", **data}
                changes = apply_changes({}, fields)
                changes["custom"] = 1  # criado por quem usa: pode ser excluído
                changes["updated_at"] = time.time()
                cols = ", ".join(changes)
                cur = conn.execute(
                    f"INSERT INTO items ({cols}) VALUES ({', '.join('?' * len(changes))})",
                    tuple(changes.values()),
                )
                item = conn.execute("SELECT * FROM items WHERE id = ?", (cur.lastrowid,)).fetchone()
                return self.send_json({"item": row(item), "existed": False}, 201)

        if self.path == "/api/list/add":
            # Pedido de vários itens de uma vez (ex.: o que falta para um prato ou para a semana).
            # Itens que ainda não existem no estoque são criados como "acabou".
            entries = data.get("items") or []
            with _lock, db() as conn:
                now = time.time()
                for e in entries:
                    name = clean_name(e.get("name", ""))
                    if not name:
                        continue
                    note = str(e.get("note") or "").strip()[:80]
                    cat = e.get("category") if e.get("category") in CATEGORIES else "Outros"
                    existing = conn.execute("SELECT * FROM items WHERE name_key = ?", (name_key(name),)).fetchone()
                    if existing:
                        if not existing["on_list"]:
                            conn.execute("UPDATE items SET on_list=1, in_cart=0, note=?, updated_at=? WHERE id=?",
                                         (note or existing["note"], now, existing["id"]))
                    else:
                        conn.execute(
                            """INSERT INTO items (name, name_key, category, level, on_list, note, updated_at)
                               VALUES (?, ?, ?, 'out', 1, ?, ?)""",
                            (name, name_key(name), cat, note, now),
                        )
                return self.send_json({"items": all_items(conn)})

        if self.path == "/api/list/finish":
            # Tudo que está no carrinho volta para o estoque como "tem".
            with _lock, db() as conn:
                now = time.time()
                n = conn.execute(
                    """UPDATE items SET level='ok', on_list=0, in_cart=0, note='',
                       last_bought_at=?, updated_at=? WHERE on_list=1 AND in_cart=1""",
                    (now, now),
                ).rowcount
                return self.send_json({"finished": n, "items": all_items(conn)})

        if self.path == "/api/plan/suggest":
            def num(k, default, lo, hi):
                try:
                    return max(lo, min(hi, int(data.get(k, default))))
                except (TypeError, ValueError):
                    return default
            with db() as conn:
                return self.send_json({"plan": suggest(
                    conn, load_dishes(), num("days", 5, 1, 7), num("desserts", 2, 0, 2), num("variant", 0, 0, 1000))})

        if self.path == "/api/plan":
            plan = data.get("plan")
            if not isinstance(plan, dict) or not plan.get("meals"):
                return self.send_json({"error": "Plano vazio"}, 400)
            plan.pop("saved_at", None)
            with _lock, db() as conn:
                now = time.time()
                conn.execute("INSERT INTO plans (created_at, data) VALUES (?, ?)",
                             (now, json.dumps(plan, ensure_ascii=False)))
            return self.send_json({"plan": {**plan, "saved_at": now}})

        self.send_json({"error": "Não encontrado"}, 404)

    def do_PATCH(self):
        item_id = self.item_id()
        if item_id is None:
            return self.send_json({"error": "Não encontrado"}, 404)
        try:
            data = self.read_json()
            with _lock, db() as conn:
                current = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
                if not current:
                    return self.send_json({"error": "Item não existe mais"}, 404)
                self._update(conn, item_id, apply_changes(dict(current), data))
                item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
                return self.send_json({"item": row(item)})
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except sqlite3.IntegrityError:
            return self.send_json({"error": "Já existe um item com esse nome"}, 409)

    def do_DELETE(self):
        item_id = self.item_id()
        if item_id is None:
            return self.send_json({"error": "Não encontrado"}, 404)
        with _lock, db() as conn:
            current = conn.execute("SELECT custom FROM items WHERE id = ?", (item_id,)).fetchone()
            if current and not current["custom"]:
                return self.send_json({"error": "Item original não pode ser excluído"}, 403)
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.send_json({"ok": True})

    @staticmethod
    def _update(conn, item_id, changes):
        if not changes:
            return
        changes["updated_at"] = time.time()
        sets = ", ".join(f"{k} = ?" for k in changes)
        conn.execute(f"UPDATE items SET {sets} WHERE id = ?", (*changes.values(), item_id))


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Home Sweet Home rodando em http://0.0.0.0:{PORT}  (banco: {DB_PATH})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
