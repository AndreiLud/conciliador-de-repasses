# Metodologia

## 1. Regras do repasse

Para cada pedido entregue, com o contrato vigente na **data de criação** do pedido:

```
repasse = itens − comissão − taxa de pagamento − cupom pago pelo restaurante + taxa de entrega (só no plano com entrega própria)
```

* **Comissão:** taxa do plano sobre o valor dos itens, antes de qualquer cupom.
* **Taxa de pagamento:** taxa da forma de pagamento sobre o total pago pelo cliente (itens + entrega − cupom).
* **Cupom pago pela plataforma:** não sai do restaurante.
* **Semana:** segunda 00:00 a domingo 23:59, horário de São Paulo. O pedido entra na semana em que foi **concluído**. O estorno entra na semana em que foi **processado**.
* **Pagamento:** quarta-feira seguinte ao fechamento da semana.
* **Cancelado antes do preparo:** sem cobrança e fora do repasse.
* **Estorno:** descontado do restaurante só quando a responsabilidade é dele.
* **Ajuste manual:** linha com chamado e justificativa; aceito como está.

## 2. Dinheiro sem ponto flutuante

* Valores em centavos inteiros (`int` em Python, `BIGINT` no DuckDB). Taxas em pontos-base inteiros (12% = 1200).
* Leitura sempre por `Decimal`. Um valor com mais de duas casas decimais é recusado.
* Produto valor × taxa arredondado para o centavo, metade para cima: `(valor × bps + 5000) // 10000`.
* Taxas do Excel chegam como número binário (0,0319 vira 0,031899...). São convertidas para o ponto-base mais próximo, e o código recusa sobra maior que 0,0001.
* No Excel de saída os valores são gravados como `Decimal` em reais, só para exibição.

## 3. Tolerâncias

| Regra | Valor | Por quê |
|---|---|---|
| Diferença por linha considerada arredondamento | até R$ 0,02 | Sistemas que truncam em vez de arredondar geram diferença de 1 centavo por componente |
| Resíduo por repasse | até R$ 0,10 | Acúmulo de arredondamentos numa semana |
| Janela do banco | D+0 a D+2 da data prevista | Pagamentos em lote atrasam até dois dias úteis |
| Reenvio depois de devolução | até 7 dias depois da devolução | Pix com chave errada volta e é reenviado por TED |
| Similaridade mínima de nome no banco | 0,80 (Jaro-Winkler) | Nome cortado e abreviado ainda casa; nome diferente não |
| Similaridade para identificar sozinho | 0,90 e 0,05 acima do segundo | Evita escolher entre duas unidades com nome quase igual |
| Confiança mínima da IA | 0,75 | Abaixo disso o caso vai para revisão |

## 4. Etapas do motor

Cada etapa SQL fica em `sql/`, com um comentário no topo dizendo o que faz.

| Arquivo | O que faz |
|---|---|
| 00_staging.sql | Tabelas tipadas e semana de cada pedido e estorno |
| 01_contracts.sql | Contrato vigente na data do pedido e plano anterior de quem trocou |
| 02_expected_order_lines.sql | Recálculo de cada pedido em centavos |
| 03_expected_refund_lines.sql | Estornos do período e o que o extrato deve fazer com cada um |
| 04_match_order_lines.sql | Casamento por id; ocorrências repetidas; hipótese do plano anterior |
| 05_match_refund_lines.sql | Casamento por id do estorno ou por (pedido, valor, ordem) no layout legado |
| 06_line_divergences.sql | Regras de detecção por linha |
| 07_repasse_totals.sql | Total do repasse contra o recalculado e resíduo não explicado |
| 08_bank_candidates.sql | Limpeza do histórico do banco e candidatos por CNPJ, conta, referência e nome |
| 09_aggregations.sql | Resumos por tipo, semana, restaurante e repasse |

A atribuição final dos pagamentos do banco roda em Python (`src/reconciliation/bank.py`), em ordem de data, com regras explícitas: valor exato e evidência do restaurante; devolução reabre o repasse; segundo pagamento do mesmo valor é duplicidade; restaurante identificado com valor diferente é transferência divergente.

## 5. Classificação

**Por regra**, quando a evidência aponta uma causa só:

* layout detalhado: o componente que diverge diz a causa (comissão, taxa ou cupom); se o líquido bate com o plano anterior, é plano antigo;
* layout legado: o código calcula hipóteses (plano anterior, cupom da plataforma cobrado, taxa de outra forma de pagamento, comissão em outra taxa redonda). Se exatamente uma reproduz o valor do extrato, ela é a causa;
* linha repetida, pedido ausente, estorno ausente ou repetido, transferência divergente e repasse pago duas vezes são classificados direto;
* plano antigo é agrupado por restaurante e semana: a causa é o contrato, não cada pedido.

**Casos ambíguos** vão para o modelo local:

* **Estorno sem responsável:** a única evidência é a nota do atendimento. O modelo responde quem causou o problema (restaurante, plataforma ou indefinido), a confiança e o trecho da nota que decide. O código confere que o trecho existe na nota. Se a regra de palavras-chave tem resposta e discorda do modelo, o caso vai para revisão.
* **Linha do legado com mais de uma hipótese:** o modelo recebe as hipóteses já calculadas e escolhe uma que reproduz o valor do extrato, citando evidências que existem no caso. Se a escolha diverge da regra de prioridade, o caso vai para revisão.

O modelo nunca recebe a tarefa de calcular. Ele escolhe entre opções e escreve texto.

## 6. Textos

* **Carta:** estrutura, tabela de valores, explicação e próximo passo são do código. A explicação escrita pelo modelo (sem valores, a partir das causas em linguagem simples) foi testada: numa revisão humana de 20 cartas, 12 tinham fato errado ou inventado. Ficou desligada; `LETTERS_AI=1` liga.
* **Resumo da semana:** números, parágrafos e tabelas são do código. A leitura da semana escrita pela IA foi testada e ficou desligada: o modelo pequeno trocava o papel dos números e, mesmo sem números, afirmava fatos errados. `SUMMARY_AI=1` liga a leitura para quem usar um modelo maior.
* **Checagens:** JSON validado por schema; todo número citado precisa existir nos fatos; expressões proibidas, travessão, hífen como pausa, emoji e perguntas reprovam o texto. Uma nova tentativa com a lista de problemas; depois disso, texto fixo.

## 7. Cache e reprodutibilidade

* Cada resposta do modelo fica em `llm_cache/<tarefa>/<hash>.json`, indexada pelo SHA-256 de tarefa, modelo, prompt do sistema, entrada e schema. O arquivo guarda também tokens e segundos.
* `python run_all.py --offline` repete a execução inteira sem servidor de modelo e chega ao mesmo resultado.
* Semente fixa no gerador. Versões fixadas em `requirements.txt`.

## 8. Erros plantados

| Tipo | Casos | Oportunidades | Taxa aproximada |
|---|---|---|---|
| Comissão com taxa errada | 25 | cerca de 62 mil linhas de pedido | 0,04% |
| Plano antigo depois da troca | 8 | 20 trocas de plano | 8 de 20 restaurantes |
| Taxa de pagamento errada | 25 | linhas de pedido | 0,04% |
| Cupom da plataforma cobrado | 20 | pedidos com cupom da plataforma | cerca de 0,3% |
| Estorno não descontado | 15 | estornos do restaurante | cerca de 2,5% |
| Estorno descontado duas vezes | 10 | estornos do restaurante | cerca de 1,7% |
| Pedido pago em duplicidade | 15 | linhas de pedido | 0,02% |
| Pedido fora do repasse | 20 | pedidos entregues | 0,03% |
| Valor transferido diferente | 8 | 1.000 repasses | 0,8% |
| Repasse pago em duplicidade | 4 | 1.000 repasses | 0,4% |

Os erros aparecem em 139 dos 1.000 repasses (13,9%); os outros 861 estão certos. Os valores vão de R$ 0,13 a R$ 5.400,00.

## 9. Armadilhas

Pedido de domingo concluído depois da meia-noite, pedido concluído depois do fechamento do período, cancelamento antes do preparo, estorno assumido pela plataforma, diferença de centavos dentro da tolerância, ajuste manual com chamado, segundo estorno legítimo do mesmo pedido e Pix devolvido e reenviado. Os resultados por armadilha estão em `evaluation.md`.
