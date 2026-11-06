# Dicionário de dados

Todos os arquivos são gerados por `python -m src.generator.generate` com semente fixa e ficam em `data/raw/`. Os formatos imitam o que um time financeiro recebe de verdade.

## pedidos.csv

Exportação do sistema de pedidos. UTF-8, vírgula como separador, ponto decimal, datas `AAAA-MM-DD hh:mm:ss`.

| Coluna | Tipo | Descrição |
|---|---|---|
| pedido_id | texto | Identificador único do pedido (9 dígitos) |
| restaurante_id | texto | Restaurante no formato R0000 (algumas linhas vêm em minúsculas) |
| criado_em | data e hora | Criação do pedido. Define o contrato vigente |
| concluido_em | data e hora | Entrega. Define a semana do repasse. Vazio se cancelado |
| status | texto | entregue ou cancelado |
| cancelado_em, etapa_cancelamento | data e hora, texto | Só em cancelados. Todos antes do preparo, sem cobrança |
| valor_itens | dinheiro | Subtotal dos itens |
| taxa_entrega | dinheiro | Taxa de entrega paga pelo cliente |
| cupom_codigo, cupom_valor | texto, dinheiro | Cupom aplicado |
| cupom_custeio | texto | Quem paga o cupom: plataforma ou restaurante |
| forma_pagamento | texto | pix, credito, debito ou vale_refeicao (com grafias variadas) |
| valor_total | dinheiro | itens + entrega − cupom: o que o cliente pagou |

A exportação traz 12 linhas repetidas por inteiro, removidas na ingestão.

## estornos.csv

| Coluna | Tipo | Descrição |
|---|---|---|
| estorno_id | texto | EST-000000 |
| pedido_id, restaurante_id | texto | Pedido e restaurante |
| processado_em | data e hora | Define a semana em que o estorno entra no repasse |
| valor_estornado | dinheiro | Valor devolvido ao cliente |
| responsavel | texto | restaurante ou plataforma. **Vazio em parte dos estornos** |
| motivo | texto | Nota livre do atendimento, com gíria e abreviações |

Só estornos de responsabilidade do restaurante são descontados do repasse.

## repasse_extrato.csv

Extrato de repasse linha a linha. Ponto e vírgula como separador, vírgula decimal, deduções com sinal negativo, datas `dd/mm/aaaa hh:mm`.

| Coluna | Descrição |
|---|---|
| repasse_id | REP-AAAAWss-R0000 |
| restaurante_id, semana | Restaurante e semana ISO |
| linha_id | Identificador da linha |
| tipo_linha | pedido, estorno ou ajuste |
| pedido_id, referencia | Pedido; referência é o id do estorno ou o chamado do ajuste |
| data_referencia | Conclusão do pedido ou processamento do estorno |
| valor_itens, taxa_entrega, cupom_restaurante, comissao, taxa_pagamento | Componentes. **Vazios no layout legado** |
| valor_liquido | Valor da linha |
| descricao | Texto do sistema. No layout legado traz plano, forma de pagamento e às vezes a comissão |

Cerca de um quarto dos restaurantes vem do sistema antigo e recebe só o líquido de cada linha.

## repasses.csv

Uma linha por repasse: período, data prevista de pagamento (quarta seguinte ao fechamento), quantidade de linhas e total.

## extrato_bancario.csv

Extrato da conta do marketplace. Latin-1, ponto e vírgula, `dd/mm/aaaa`, valores como `1.234,56`, cabeçalho e rodapé do banco antes e depois da tabela.

| Coluna | Descrição |
|---|---|
| Data | Data do lançamento |
| Lançamento | Histórico bagunçado: Pix, TED, lote, pagamento de fornecedor, com nome cortado, abreviado, CNPJ parcial, agência e conta ou referência do repasse |
| Documento | Número do documento, às vezes vazio |
| Valor (R$) | Negativo para saídas |
| Saldo (R$) | Saldo corrente, usado para confirmar que nada se perdeu na leitura |

Também traz tarifas, recebimentos de cartão, aplicações e boletos, que não são repasse.

## contratos.xlsx

| Aba | Conteúdo |
|---|---|
| planos | Versões de cada plano com vigência: comissão, entrega (própria ou da plataforma) e taxa por forma de pagamento, em células de porcentagem |
| restaurante_plano | Plano de cada restaurante com vigência. 20 restaurantes trocam de plano no meio do mês |
| cadastro | Nome fantasia, razão social, CNPJ (com dígitos verificadores propositalmente inválidos), cidade, categoria, agência e conta |

## Gabarito (data/answer_key/)

* `gabarito.csv`: cada erro plantado com caso_id, tipo, unidade, chave, restaurante, semana e valor em centavos (positivo quando o restaurante recebeu a mais).
* `armadilhas.csv`: cada armadilha, no mesmo formato, com valor zero.
* `generator_config.json`: parâmetros usados.

O motor nunca lê esta pasta. Só a avaliação.

## Planos ilustrativos

| Plano | Comissão | Entrega | Pix | Débito | Crédito | Vale-refeição |
|---|---|---|---|---|---|---|
| Essencial (até 14/10) | 12% | própria | 0,99% | 1,59% | 3,19% | 4,90% |
| Essencial (a partir de 15/10) | 12% | própria | 0,99% | 1,59% | 2,99% | 4,90% |
| Completo | 23% | plataforma | 0,99% | 1,59% | 3,19% | 4,90% |
| Parceiro Plus | 20% | plataforma | 0,79% | 1,29% | 2,79% | 4,50% |
