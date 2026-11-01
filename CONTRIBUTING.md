# Contributing

Thanks for helping! Recipes, translations, bug fixes and ideas are all welcome.

## Adding dishes

1. Add any new ingredient to the catalog (`pratos/ingredientes.json` or
   `pratos/itens-da-casa.json`). Every ingredient used by a pot or dish must be there.
2. Reuse an existing pot from `pratos/preparos.json` when you can, or add a new one.
3. Add the dish as a JSON file in `pratos/`. The format is in
   [`pratos/LEIA-ME.md`](pratos/LEIA-ME.md).
4. Run the app and check the home screen: format errors show up there.

## Code changes

- No dependencies: keep it Python 3 standard library + plain HTML/CSS/JS.
- Run the tests before opening a pull request:

  ```bash
  python3 -m unittest test_cardapio.py
  ```

- Keep pull requests small and describe what changed and why.

## Language

The app interface and recipes are in Brazilian Portuguese. Issues and pull requests can be
in English or Portuguese.
