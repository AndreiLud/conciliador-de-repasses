-- 05_match_refund_lines.sql
-- What it does: matches statement refund lines to the refunds of the period.
-- Detailed statements carry the refund id; legacy statements only carry the
-- order id and the amount, so those lines are paired by (order, amount, n),
-- which keeps two legitimate refunds of the same value apart from a line
-- that was simply repeated.

CREATE OR REPLACE TABLE stmt_refund_lines AS
SELECT s.*,
       row_number() OVER (PARTITION BY s.pedido_id, s.valor_liquido ORDER BY s.data_referencia, s.linha_id) AS n_par,
       row_number() OVER (PARTITION BY s.referencia ORDER BY s.data_referencia, s.linha_id) AS ocorrencia_id
FROM stg_statement s
WHERE s.tipo_linha = 'estorno';

CREATE OR REPLACE TABLE refund_line_match AS
SELECT s.linha_id, s.repasse_id, s.semana, s.restaurante_id, s.pedido_id, s.referencia,
       s.valor_liquido, s.layout, s.descricao, s.n_par, s.ocorrencia_id,
       CASE WHEN s.referencia IS NOT NULL THEN k_id.estorno_id ELSE k_par.estorno_id END AS estorno_id,
       -- a repeated line: same refund id seen before, or more legacy lines than refunds of that value
       CASE WHEN s.referencia IS NOT NULL THEN s.ocorrencia_id > 1
            ELSE k_par.estorno_id IS NULL END AS repetida,
       first_par.estorno_id AS estorno_mesmo_valor
FROM stmt_refund_lines s
LEFT JOIN expected_refund_lines k_id
  ON s.referencia IS NOT NULL AND k_id.estorno_id = s.referencia
LEFT JOIN expected_refund_lines k_par
  ON s.referencia IS NULL AND k_par.pedido_id = s.pedido_id
 AND -k_par.e_valor = s.valor_liquido AND k_par.n_par = s.n_par
LEFT JOIN expected_refund_lines first_par
  ON first_par.pedido_id = s.pedido_id AND -first_par.e_valor = s.valor_liquido AND first_par.n_par = 1;

CREATE OR REPLACE TABLE refund_comparison AS
SELECT e.*,
       count(m.linha_id) FILTER (WHERE NOT m.repetida) AS linhas_no_extrato,
       min(m.linha_id) FILTER (WHERE NOT m.repetida) AS linha_id
FROM expected_refund_lines e
LEFT JOIN refund_line_match m ON m.estorno_id = e.estorno_id
GROUP BY ALL;
