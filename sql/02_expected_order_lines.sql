-- 02_expected_order_lines.sql
-- What it does: recalculates the payout of every delivered order of the
-- period with the contract in force on the order date. Integer arithmetic
-- only: amount * rate_bps / 10000, rounded half up to the cent.
--   net = items + delivery fee (own delivery only) - restaurant coupon
--         - commission - payment fee

CREATE OR REPLACE TABLE expected_order_lines AS
WITH base AS (
    SELECT o.pedido_id, o.restaurante_id, o.semana, o.forma_pagamento,
           o.valor_itens, o.taxa_entrega, o.cupom_codigo, o.cupom_valor, o.cupom_custeio, o.valor_total,
           o.criado_em, o.concluido_em,
           c.plano_id, c.versao, c.plano_nome, c.comissao_bps, c.entrega, c.taxa_bps
    FROM stg_orders o
    JOIN order_contract c USING (pedido_id)
    WHERE o.no_periodo
), calc AS (
    SELECT *,
           'REP-' || replace(semana, '-', '') || '-' || restaurante_id AS repasse_esperado,
           valor_itens AS e_itens,
           CASE WHEN entrega = 'propria' THEN taxa_entrega ELSE 0 END AS e_entrega,
           CASE WHEN cupom_custeio = 'restaurante' THEN cupom_valor ELSE 0 END AS e_cupom,
           (valor_itens * comissao_bps + 5000) // 10000 AS e_comissao,
           (valor_total * taxa_bps + 5000) // 10000 AS e_taxa
    FROM base
)
SELECT *, e_itens + e_entrega - e_cupom - e_comissao - e_taxa AS e_liquido
FROM calc;
