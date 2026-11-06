-- 07_repasse_totals.sql
-- What it does: compares each payout total with the recalculated total and
-- checks that the line-level findings explain the whole difference. Manual
-- adjustments with a ticket and a justification are accepted as they are.
-- A residual above the payout tolerance becomes a divergence for review.

CREATE OR REPLACE TABLE repasse_totals AS
WITH exp_orders AS (
    SELECT repasse_esperado AS repasse_id, restaurante_id, semana, sum(e_liquido) AS esperado_pedidos,
           count(*) AS qtd_pedidos
    FROM expected_order_lines GROUP BY ALL
), exp_refunds AS (
    SELECT repasse_esperado AS repasse_id, -sum(e_valor) AS esperado_estornos
    FROM expected_refund_lines WHERE responsavel = 'restaurante' GROUP BY ALL
), deducted_unknown AS (
    -- refunds with unknown owner already deducted are accepted as deducted
    SELECT m.repasse_id, sum(m.valor_liquido) AS estornos_dono_indefinido
    FROM refund_line_match m JOIN expected_refund_lines e ON e.estorno_id = m.estorno_id
    WHERE e.responsavel = 'indefinido' AND NOT m.repetida GROUP BY ALL
), adjustments AS (
    SELECT repasse_id, sum(valor_liquido) AS ajustes, count(*) AS qtd_ajustes
    FROM stg_statement WHERE tipo_linha = 'ajuste' GROUP BY ALL
), explained AS (
    SELECT repasse_id, sum(valor_centavos) AS explicado
    FROM line_divergences
    WHERE familia NOT IN ('pedido_ausente', 'estorno_ausente', 'estorno_ausente_dono_indefinido')
    GROUP BY ALL
), missing AS (
    SELECT repasse_id, sum(-valor_centavos) AS ausentes
    FROM line_divergences
    WHERE familia IN ('pedido_ausente', 'estorno_ausente')
    GROUP BY ALL
), rounding AS (
    SELECT repasse_id, sum(dif_liquido) AS arredondamento
    FROM order_line_comparison
    WHERE linha_id IS NOT NULL AND dif_liquido <> 0 AND pedido_id NOT IN
          (SELECT chave FROM line_divergences WHERE familia = 'linha_pedido')
    GROUP BY ALL
)
SELECT r.repasse_id, r.restaurante_id, r.semana, r.data_pagamento_prevista, r.valor_total AS total_extrato,
       coalesce(o.esperado_pedidos, 0) + coalesce(f.esperado_estornos, 0)
         + coalesce(u.estornos_dono_indefinido, 0) + coalesce(a.ajustes, 0) AS total_esperado,
       coalesce(o.qtd_pedidos, 0) AS qtd_pedidos, coalesce(a.qtd_ajustes, 0) AS qtd_ajustes,
       coalesce(a.ajustes, 0) AS ajustes,
       coalesce(x.explicado, 0) - coalesce(m.ausentes, 0) AS explicado_por_linhas,
       coalesce(rd.arredondamento, 0) AS arredondamento
FROM stg_repasses r
LEFT JOIN exp_orders o USING (repasse_id)
LEFT JOIN exp_refunds f USING (repasse_id)
LEFT JOIN deducted_unknown u USING (repasse_id)
LEFT JOIN adjustments a USING (repasse_id)
LEFT JOIN explained x USING (repasse_id)
LEFT JOIN missing m USING (repasse_id)
LEFT JOIN rounding rd USING (repasse_id);

CREATE OR REPLACE TABLE repasse_residuals AS
SELECT *, total_extrato - total_esperado AS diferenca_total,
       total_extrato - total_esperado - explicado_por_linhas - arredondamento AS residuo
FROM repasse_totals;
