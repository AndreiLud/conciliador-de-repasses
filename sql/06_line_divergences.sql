-- 06_line_divergences.sql
-- What it does: applies the explicit detection rules at line level and
-- writes one candidate divergence per finding. Amounts are signed as
-- (paid - due): positive means the restaurant received more than it should.
--   * order line whose net or any component differs beyond the tolerance
--   * order repeated in the statement
--   * delivered order of the period missing from the statement
--   * statement order line for an order that was not expected
--   * restaurant refund not deducted, refund deducted twice, unexpected refund

CREATE OR REPLACE TABLE line_divergences AS
-- value differences on matched order lines
SELECT 'linha_pedido' AS familia, pedido_id AS chave, restaurante_id, semana, repasse_id,
       dif_liquido AS valor_centavos, linha_id, pedido_id, NULL AS estorno_id
FROM order_line_comparison
WHERE linha_id IS NOT NULL
  AND (abs(dif_liquido) > getvariable('tol_line')
       OR (layout = 'detalhado' AND (abs(s_itens - e_itens) > getvariable('tol_line')
                                  OR abs(s_entrega - e_entrega) > getvariable('tol_line')
                                  OR abs(s_cupom - e_cupom) > getvariable('tol_line')
                                  OR abs(s_comissao - e_comissao) > getvariable('tol_line')
                                  OR abs(s_taxa - e_taxa) > getvariable('tol_line'))))

UNION ALL
-- same order paid more than once
SELECT 'pedido_repetido', s.pedido_id, s.restaurante_id, s.semana, s.repasse_id,
       s.valor_liquido, s.linha_id, s.pedido_id, NULL
FROM stmt_order_lines s
WHERE s.ocorrencia > 1 AND s.semana_esperada IS NOT NULL

UNION ALL
-- delivered in the period, absent from every statement
SELECT 'pedido_ausente', c.pedido_id, c.restaurante_id, c.semana, c.repasse_esperado,
       -c.e_liquido, NULL, c.pedido_id, NULL
FROM order_line_comparison c
WHERE c.linha_id IS NULL

UNION ALL
-- paid but not expected in the period (cancelled, unknown or out of period)
SELECT 'pedido_nao_esperado', s.pedido_id, s.restaurante_id, s.semana, s.repasse_id,
       s.valor_liquido, s.linha_id, s.pedido_id, NULL
FROM stmt_order_lines s
WHERE s.semana_esperada IS NULL

UNION ALL
-- refund owed by the restaurant (or with unknown owner) that was not deducted
SELECT CASE WHEN r.responsavel = 'restaurante' THEN 'estorno_ausente' ELSE 'estorno_ausente_dono_indefinido' END,
       r.estorno_id, r.restaurante_id, r.semana, r.repasse_esperado,
       r.e_valor, NULL, r.pedido_id, r.estorno_id
FROM refund_comparison r
WHERE r.responsavel IN ('restaurante', 'indefinido') AND r.linhas_no_extrato = 0

UNION ALL
-- refund line repeated (same id, or more lines than refunds of that value)
SELECT 'estorno_repetido', coalesce(m.estorno_id, m.estorno_mesmo_valor), m.restaurante_id, m.semana, m.repasse_id,
       m.valor_liquido, m.linha_id, m.pedido_id, coalesce(m.estorno_id, m.estorno_mesmo_valor)
FROM refund_line_match m
WHERE m.repetida AND coalesce(m.estorno_id, m.estorno_mesmo_valor) IS NOT NULL

UNION ALL
-- refund line that matches no refund, or a refund the platform owns
SELECT 'estorno_nao_esperado', m.linha_id, m.restaurante_id, m.semana, m.repasse_id,
       m.valor_liquido, m.linha_id, m.pedido_id, m.estorno_id
FROM refund_line_match m
LEFT JOIN expected_refund_lines e ON e.estorno_id = m.estorno_id
WHERE (m.estorno_id IS NULL AND m.estorno_mesmo_valor IS NULL)
   OR (NOT m.repetida AND e.responsavel = 'plataforma');
