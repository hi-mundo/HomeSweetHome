# Pratos, panelas e catálogo

Tudo nesta pasta é **original**: os itens entram no estoque sozinhos e não podem ser
excluídos pelo app. O app relê a pasta sozinho — não precisa reiniciar o servidor.
Erros (campo faltando, ingrediente sem cadastro) aparecem na tela Início.

## Catálogo — `ingredientes.json` (comida) e `itens-da-casa.json` (limpeza, utensílios, higiene)

```json
"Banana": { "categoria": "Frutas", "emoji": "🍌", "unidade": "dúzia", "dura": 1, "dura_inteiro": 5 }
```

| Campo | Para quê |
|---|---|
| `categoria` | Onde aparece no estoque e na lista de compras (obrigatório). |
| `emoji` | Ícone do item. |
| `unidade` | Unidade de compra ("1 kg", "1 lata") na lista. |
| `dura` | Dias na geladeira depois de aberto, cortado ou cozido. Sem isso: não perecível. |
| `dura_inteiro` | Dias inteiro/fechado (lanches "só separar"). |

Todo ingrediente usado em panelas e pratos **precisa** estar no catálogo.

## `preparos.json` — as panelas

```json
{ "nome": "Carne cozida", "grupo": "proteína", "proteina_tipo": "bovina",
  "rende": 6, "dura": 4, "congela": true,
  "tempo_ativo": 20, "tempo_total": 60, "equipamento": "pressão", "dificuldade": "fácil",
  "kcal": 320, "proteina_g": 30,
  "dica": "opcional: aparece para a cozinheira",
  "ingredientes": [{ "item": "Carne bovina", "qtd": "1,2 kg" }, "Cebola", "Alho"] }
```

| Campo | Para quê no algoritmo |
|---|---|
| `grupo` | `proteína`, `carboidrato`, `leguminosa`, `verdura` — checklist da dieta; `verdura` é adicionada sozinha a prato sem verdura. |
| `proteina_tipo` | `bovina`, `frango`, `suína`, `peixe`, `ovo` — variar a proteína na semana. |
| `rende` | Porções por receita — quantas receitas fazer. |
| `dura` / `congela` | Dias que aguenta pronta / se a porção vai ao freezer. Declare sempre: a validade de um cozido não é a do ingrediente cru. |
| `tempo_ativo` / `tempo_total` | Minutos de trabalho / até ficar pronto — semana mais rápida e roteiro do dia de cozinha. |
| `equipamento` | `fogão`, `forno`, `pressão`, `liquidificador`, `micro-ondas`, `nenhum` — o roteiro respeita uma panela de pressão e forno para 2. |
| `dificuldade` | `fácil` ou `média` — prefere as fáceis. |
| `kcal` / `proteina_g` | Por porção (estimativa) — marmitas de 550+ kcal. |
| `reforco` | `true` em extras que duram (farofa, ovo cozido): entram sozinhos em marmita que ficou leve. |

## Um arquivo por prato

```json
{ "nome": "Carne com caldo e cuscuz", "emoji": "🍲",
  "preparos": ["Carne cozida", "Cuscuz"],
  "ingredientes": ["Cheiro-verde"],
  "opcionais": ["Pimenta"] }
```

- **preparos**: panelas de `preparos.json`. O prato herda ingredientes, validade, kcal, tempo e
  tipo de proteína delas.
- **ingredientes** (opcional): extras que não vêm de uma panela.
- **tipo**: `"refeição"` (padrão), `"sobremesa"` ou `"lanche"`.
- **preparo** (lanches e sobremesas): `"nenhum"` (só separar no potinho), `"montar"` (sem fogão)
  ou `"cozinhar"`. O plano prefere os que dão menos trabalho.
- **kcal**, **tempo_ativo**, **tempo_total**, **equipamento** (lanches e sobremesas): como nas panelas.
- **rende** (sobremesas): porções de uma receita (padrão 6). Sobremesa é feita inteira.
- **dura** / **congela** (opcional): sobrescrevem o que vem das panelas. `dura: 0` = só fazendo
  na hora (nunca entra no plano da semana).
- **opcionais**: não impedem o prato; aparecem como "se tiver".

Ingredientes usam o nome do catálogo (acentos/maiúsculas não importam). Objeto
`{ "item": "...", "qtd": "..." }` também vale; a `qtd` vai como observação na lista de compras.
