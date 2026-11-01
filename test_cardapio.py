"""Testes do planejador da semana. Rode com: python3 -m unittest test_cardapio.py"""
import unittest
from pathlib import Path

import cardapio
from server import CATEGORIES

DATA = cardapio.load(Path(__file__).parent / "pratos", CATEGORIES)
FULL_STOCK = [{"name": c["name"], "category": c["category"], "level": "ok"} for c in DATA["catalog"].values()]


def plan(stock=FULL_STOCK, history=(), days=5, desserts=2, variant=0):
    return cardapio.suggest_plan(DATA, stock, list(history), days, desserts, variant)


def month(days=5, weeks=4):
    """Simula semanas seguidas, cada uma vendo os planos anteriores (mais novo primeiro)."""
    history = []
    for _ in range(weeks):
        history.insert(0, plan(history=history, days=days))
    return history[::-1]


def without(*names):
    out = {cardapio.name_key(n) for n in names}
    return [{**s, "level": "out" if cardapio.name_key(s["name"]) in out else s["level"]} for s in FULL_STOCK]


def by_id(p):
    return {x["id"]: x for k in ("meals", "desserts", "snacks") for x in p[k]}


class Dataset(unittest.TestCase):
    def test_loads_without_errors(self):
        self.assertEqual(DATA["errors"], [])
        kinds = {d["type"] for d in DATA["dishes"]}
        self.assertEqual(kinds, {"meal", "dessert", "snack"})

    def test_life_comes_from_ingredients(self):
        dishes = {d["name"]: d for d in DATA["dishes"]}
        self.assertEqual(dishes["Vitamina de banana com aveia"]["life"], 0)
        # Só separar: banana inteira dura 5 dias, não 1.
        self.assertEqual(dishes["Banana com pasta de amendoim"]["life"], 5)
        self.assertTrue(dishes["Carne com caldo e cuscuz"]["freeze"])


class Week(unittest.TestCase):
    def test_shape(self):
        p = plan()
        self.assertEqual(len(p["days"]), 5)
        self.assertEqual(len(p["meals"]), 5)
        self.assertLessEqual(len(p["desserts"]), 2)
        self.assertTrue(all(d["dessert"] and d["snack"] for d in p["days"]))

    def test_no_repeat_in_a_row(self):
        for variant in range(4):
            days = plan(variant=variant)["days"]
            for i, d in enumerate(days):
                self.assertNotEqual(d["lunch"]["id"], d["dinner"]["id"])
                if i + 1 < len(days):
                    self.assertNotEqual(d["dinner"]["id"], days[i + 1]["lunch"]["id"])

    def test_nothing_spoils_with_full_stock(self):
        for days in (3, 5, 7):
            p = plan(days=days)
            self.assertEqual(p["warnings"], [], days)
            items = by_id(p)
            for n, d in enumerate(p["days"], 1):
                for slot in ("lunch", "dinner"):
                    meal = items[d[slot]["id"]]
                    # Passou da validade -> tem que estar marcado para o freezer.
                    self.assertEqual(d[slot]["frozen"], n > meal["life"])
                for slot in ("dessert", "snack"):
                    self.assertLessEqual(n, items[d[slot]]["life"], (days, slot, items[d[slot]]["name"]))

    def test_never_uses_made_to_order_items(self):
        names = {x["name"] for k in ("desserts", "snacks") for x in plan(days=7)[k]}
        self.assertNotIn("Vitamina de banana com aveia", names)
        self.assertNotIn("Tapioca com queijo", names)

    def test_sides_within_life(self):
        lives = {p["name"]: p["life"] for p in DATA["preparos"]}
        for n, d in enumerate(plan(days=7)["days"], 1):
            for slot in ("lunch", "dinner"):
                if d[slot]["side"]:
                    self.assertLessEqual(n, lives[d[slot]["side"]])

    def test_diet_checks_pass(self):
        self.assertTrue(all(c["ok"] for c in plan()["checks"]))

    def test_at_most_two_desserts_and_whole_recipes(self):
        p = plan(days=7)
        self.assertLessEqual(len(p["desserts"]), 2)
        for d in p["desserts"]:
            self.assertTrue(d["factor"] is None or d["factor"] >= 1)

    def test_prefers_what_is_at_home(self):
        p = plan(stock=without("Carne bovina"))
        self.assertFalse(any("Carne cozida" in m["preparos"] for m in p["meals"]))

    def test_next_week_varies(self):
        first = plan()
        second = plan(history=[first])
        self.assertFalse({m["id"] for m in first["meals"]} & {m["id"] for m in second["meals"]})

    def test_variants_differ(self):
        self.assertNotEqual([m["id"] for m in plan()["meals"]], [m["id"] for m in plan(variant=1)["meals"]])



class Month(unittest.TestCase):
    """Um mês sem repetir refeição (e sem repetir sobremesa nem lanche de uma semana para a outra)."""

    def check(self, days):
        weeks = month(days=days)
        meals = [m["id"] for w in weeks for m in w["meals"]]
        self.assertEqual(len(meals), len(set(meals)), f"refeição repetida no mês ({days} dias/semana)")
        desserts = [d["id"] for w in weeks for d in w["desserts"]]
        self.assertEqual(len(desserts), len(set(desserts)), "sobremesa repetida no mês")
        for a, b in zip(weeks, weeks[1:]):
            self.assertFalse({x["id"] for x in a["snacks"]} & {x["id"] for x in b["snacks"]},
                             "lanche repetido de uma semana para a outra")
        for w in weeks:
            self.assertEqual(w["warnings"], [])
            self.assertTrue(all(c["ok"] for c in w["checks"]), [c["label"] for c in w["checks"] if not c["ok"]])

    def test_month_5_days(self):
        self.check(5)

    def test_month_7_days(self):
        self.check(7)

    def test_enough_variety_for_a_month(self):
        kinds = {t: [d for d in DATA["dishes"] if d["type"] == t and d["life"] > 0] for t in ("meal", "dessert", "snack")}
        self.assertGreaterEqual(len(kinds["meal"]), 28)     # 7 refeições x 4 semanas
        self.assertGreaterEqual(len(kinds["dessert"]), 8)   # 2 x 4 semanas
        self.assertGreaterEqual(len(kinds["snack"]), 14)    # sem repetir de uma semana para a outra


if __name__ == "__main__":
    unittest.main()
