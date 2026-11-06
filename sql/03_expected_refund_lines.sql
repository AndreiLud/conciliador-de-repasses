-- 03_expected_refund_lines.sql
-- What it does: lists the refunds of the period and what the statement
-- should do with each one. Refunds owed by the restaurant must be deducted;
-- refunds owed by the platform must not. When the support ticket left the
-- owner blank, the owner is 'indefinido' and is decided later from the
-- ticket text (keyword rule first, language model for the rest).

CREATE OR REPLACE TABLE expected_refund_lines AS
SELECT estorno_id, pedido_id, restaurante_id, semana,
       'REP-' || replace(semana, '-', '') || '-' || restaurante_id AS repasse_esperado,
       valor_estornado AS e_valor,
       coalesce(responsavel, 'indefinido') AS responsavel,
       motivo, processado_em,
       row_number() OVER (PARTITION BY pedido_id, valor_estornado ORDER BY processado_em, estorno_id) AS n_par
FROM stg_refunds
WHERE no_periodo;
