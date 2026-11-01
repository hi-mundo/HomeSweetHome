# Lar Doce Lar

App para quem cozinha em casa, pensado para ficar aberto num iPad (funciona também no celular e
no computador, com o conteúdo centralizado e 2 colunas em telas largas): **planejar a comida da semana** com o que tem,
ver **quais pratos dá pra fazer**, marcar o **estoque** por nomes genéricos ("Arroz", "Leite",
não a marca) e montar a **lista de compras**.

## Rodar

```bash
python3 server.py          # http://<ip-desta-máquina>:8080
PORT=9000 python3 server.py
```

Sem dependências (Python 3 + SQLite). No celular, abra `http://<ip>:8080` na mesma rede
Wi-Fi e use "Adicionar à tela inicial" para virar um ícone de app.

- Banco: `data/lar.db` (criado com itens comuns na primeira vez).
- Catálogo de itens, panelas e pratos (com metadados de validade, tempo, calorias…): pasta `pratos/` — formato em `pratos/LEIA-ME.md`.
- Testes do planejador: `python3 -m unittest test_cardapio.py`.

## Como funciona para a cozinheira

A interface evita listas longas: cada tela mostra primeiro o que precisa de atenção e o
resto fica a um toque, em blocos.

| Aba | O que faz |
|---|---|
| 🏠 **Início** | Alerta se o estoque não dá para a semana (com **Pedir o que falta**). Card **Hoje**: almoço, sobremesa, lanche e janta do dia, e o que tirar do freezer para amanhã. Cardápio em 3 blocos: Refeições, Sobremesas, Lanches. |
| 🧺 **Cozinha** | **Precisa de atenção** (o que está Pouco/Acabou) e, embaixo, blocos de categoria (🥬 Hortifruti · 16 itens) que abrem os cards com ícone e **Tem / Pouco / Acabou**. |
| 🧽 **Casa** | O mesmo para limpeza, utensílios (vassoura, rodo…) e higiene (shampoo, sabonete…). |
| 🛒 **Compras** | Uma lista só, por categoria; o que já está no carrinho desce para "No carrinho". **Enviar lista** manda pelo WhatsApp; **Comprei** devolve ao estoque. |

**🗑 Remover itens** só exclui itens que vocês adicionaram. Os originais (que vêm com o app
e os ingredientes dos pratos) não podem ser excluídos nem renomeados.

## Cozinhar pra semana

A cozinheira escolhe quantos **dias** (padrão 5) e quantos **tipos de sobremesa** (0 a 2).
Tudo é preparado no dia 1. Cada dia tem **almoço, sobremesa, lanche da tarde e janta**.
O algoritmo (`cardapio.py`, testes em `test_cardapio.py`):

1. **Escolhe os pratos** — pré-seleciona os ~18 mais promissores e testa todas as combinações
   entre eles, pontuando (menor é melhor): ingredientes que faltam, panelas diferentes, falhas de
   dieta, **proteína repetida** (no máx. 2 do mesmo tipo em 5 dias), **horas de trabalho**,
   panelas de dificuldade média, marmitas leves, pratos perecíveis que não congelam e
   **repetição no último mês**. Nenhuma panela vai em mais de ~metade dos pratos.
2. **Distribui nos dias** — testa todas as ordens: cada prato vira um almoço e uma janta em
   dias diferentes, nunca a janta de hoje e o almoço de amanhã; o que estraga antes vai para o
   começo; marmita que passaria da validade vai **para o freezer** (com lembrete de
   descongelar na véspera).
3. **Verduras** — prato sem verdura ganha uma, escolhida por refeição e só se ainda estiver na
   validade naquele dia. Frescas primeiro; legumes congelados só para o fim da semana.
4. **Reforço** — marmita abaixo de 550 kcal ganha um extra que dura (farofa ou ovo cozido).
5. **Sobremesas** — no máximo 2 tipos, receita inteira; o par ideal é uma caseira no começo da
   semana + uma que dura no fim.
6. **Lanches** — 1 por dia, preferindo só separar no potinho; os perecíveis no começo.
7. **Roteiro do dia de cozinha** — começa pelo que demora sozinho (pressão, forno), respeitando
   uma panela de pressão e o forno para 2 assadeiras; mostra o horário de cada etapa e o tempo
   total.
8. **Checklist** — proteína, carboidrato, marmitas caprichadas, proteínas variadas, verdura em
   todo prato, leguminosa, frutas e "nada passa da validade".

O plano tem 3 abas: **Semana** (resumo e um dia por vez, com kcal), **Cozinhar** (roteiro com
horários, panelas com porções, receitas, validade e a partir de que dia congelar; sobremesas;
lanches) e **Conferir** (o que falta comprar, avisos de validade e dieta).

## Variedade

O cardápio tem **53 refeições, 18 sobremesas e 20 lanches** sobre 43 panelas — comida de casa, brasileira e simples. Com o
histórico de planos salvos, o app garante (e os testes conferem, simulando 4 semanas):

- nenhuma **refeição** repetida no mês (20 por mês com 5 dias/semana; 28 com 7);
- nenhuma **sobremesa** repetida no mês;
- nenhum **lanche** repetido de uma semana para a outra.

Para mais variedade, basta adicionar pratos em `pratos/` — de preferência combinando panelas
que já existem (cada panela nova em 2–3 pratos é o que deixa a semana com menos trabalho).

## Alerta da semana

Sem plano salvo, o app calcula o melhor plano possível e mostra o que falta para ele — é o
mínimo a comprar para ter uma semana de comida. Com um plano em andamento, confere o que esse
plano precisa.

## Observação

Não tem senha: qualquer um na rede de casa consegue abrir. Não exponha a porta para a internet.
