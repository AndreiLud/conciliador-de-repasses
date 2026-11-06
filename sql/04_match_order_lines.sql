-- 04_match_order_lines.sql
-- What it does: matches statement order lines to the recalculated orders by
-- order id. When an order shows up more than once, the occurrence in the
-- expected week is the original and the others are repetitions. It also
-- brings the previous contract, so the old plan hypothesis can be tested.

CREATE OR REPLACE TABLE stmt_order_lines AS
SELECT s.*,
       e.semana AS semana_esperada,
       row_number() OVER (PARTITION BY s.pedido_id
                          ORDER BY (s.semana = e.semana) DESC NULLS LAST, s.semana, s.linha_id) AS ocorrencia
FROM stg_statement s
LEFT JOIN expected_order_lines e USING (pedido_id)
WHERE s.tipo_linha = 'pedido';

CREATE OR REPLACE TABLE order_line_comparison AS
SELECT e.*,
       s.linha_id, s.repasse_id, s.semana AS semana_extrato, s.layout, s.descricao,
       s.valor_itens AS s_itens, s.taxa_entrega AS s_entrega, s.cupom_restaurante AS s_cupom,
       s.comissao AS s_comissao, s.taxa_pagamento AS s_taxa, s.valor_liquido AS s_liquido,
       s.valor_liquido - e.e_liquido AS dif_liquido,
       pc.plano_anterior, pc.plano_anterior_nome, pc.data_troca,
       pc.ant_comissao_bps, pc.ant_taxa_bps, pc.ant_entrega,
       CASE WHEN pc.plano_anterior IS NULL THEN NULL ELSE
            e.valor_itens
            + CASE WHEN pc.ant_entrega = 'propria' THEN e.taxa_entrega ELSE 0 END
            - e.e_cupom
            - (e.valor_itens * pc.ant_comissao_bps + 5000) // 10000
            - (e.valor_total * pc.ant_taxa_bps + 5000) // 10000 END AS ant_liquido
FROM expected_order_lines e
LEFT JOIN stmt_order_lines s ON s.pedido_id = e.pedido_id AND s.ocorrencia = 1
LEFT JOIN order_previous_contract pc ON pc.pedido_id = e.pedido_id;
