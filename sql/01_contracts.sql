-- 01_contracts.sql
-- What it does: finds the contract in force on the creation date of every
-- delivered order (restaurant plan, then the plan version valid that day),
-- and the previous plan of restaurants that switched plans. The previous
-- plan feeds the "old plan still applied" hypothesis.

CREATE OR REPLACE TABLE order_contract AS
SELECT o.pedido_id,
       rp.plano_id, p.versao, p.nome AS plano_nome, p.comissao_bps, p.entrega,
       CASE o.forma_pagamento
            WHEN 'pix' THEN p.taxa_pix_bps
            WHEN 'debito' THEN p.taxa_debito_bps
            WHEN 'credito' THEN p.taxa_credito_bps
            ELSE p.taxa_vale_refeicao_bps END AS taxa_bps
FROM stg_orders o
JOIN stg_restaurant_plans rp
  ON rp.restaurante_id = o.restaurante_id
 AND o.data_pedido >= rp.vigencia_inicio
 AND (rp.vigencia_fim IS NULL OR o.data_pedido <= rp.vigencia_fim)
JOIN stg_plans p
  ON p.plano_id = rp.plano_id
 AND o.data_pedido >= p.vigencia_inicio
 AND (p.vigencia_fim IS NULL OR o.data_pedido <= p.vigencia_fim)
WHERE o.status = 'entregue';

CREATE OR REPLACE TABLE order_previous_contract AS
SELECT o.pedido_id,
       prev.plano_id AS plano_anterior, p.nome AS plano_anterior_nome,
       p.comissao_bps AS ant_comissao_bps, p.entrega AS ant_entrega,
       CASE o.forma_pagamento
            WHEN 'pix' THEN p.taxa_pix_bps
            WHEN 'debito' THEN p.taxa_debito_bps
            WHEN 'credito' THEN p.taxa_credito_bps
            ELSE p.taxa_vale_refeicao_bps END AS ant_taxa_bps,
       cur.vigencia_inicio AS data_troca
FROM stg_orders o
JOIN stg_restaurant_plans cur
  ON cur.restaurante_id = o.restaurante_id
 AND o.data_pedido >= cur.vigencia_inicio
 AND (cur.vigencia_fim IS NULL OR o.data_pedido <= cur.vigencia_fim)
JOIN stg_restaurant_plans prev
  ON prev.restaurante_id = cur.restaurante_id
 AND prev.vigencia_fim + 1 = cur.vigencia_inicio
JOIN stg_plans p
  ON p.plano_id = prev.plano_id
 AND o.data_pedido >= p.vigencia_inicio
 AND (p.vigencia_fim IS NULL OR o.data_pedido <= p.vigencia_fim)
WHERE o.status = 'entregue';
