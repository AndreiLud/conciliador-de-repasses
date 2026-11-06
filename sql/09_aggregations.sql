-- 09_aggregations.sql
-- What it does: builds the summary tables used by the Excel report, the
-- letters and the site, from the classified divergences. Only confirmed
-- divergences count as money to settle; review cases are listed apart.

CREATE OR REPLACE TABLE summary_by_type AS
SELECT tipo,
       count(*) AS casos,
       sum(valor_centavos) FILTER (WHERE valor_centavos > 0) AS a_mais_restaurante,
       -sum(valor_centavos) FILTER (WHERE valor_centavos < 0) AS a_menos_restaurante,
       count(*) FILTER (WHERE classificado_por IN ('regra', 'regra_base')) AS por_regra,
       count(*) FILTER (WHERE classificado_por = 'ia') AS por_ia
FROM divergences
WHERE status = 'confirmada'
GROUP BY tipo
ORDER BY casos DESC;

CREATE OR REPLACE TABLE summary_by_week AS
SELECT w.semana, w.inicio, w.fim, w.data_pagamento,
       (SELECT count(*) FROM stg_repasses r WHERE r.semana = w.semana) AS repasses,
       (SELECT sum(valor_total) FROM stg_repasses r WHERE r.semana = w.semana) AS total_repassado,
       (SELECT count(*) FROM divergences d WHERE d.semana = w.semana AND d.status = 'confirmada') AS divergencias,
       (SELECT count(DISTINCT d.restaurante_id) FROM divergences d
         WHERE d.semana = w.semana AND d.status = 'confirmada') AS restaurantes_afetados,
       (SELECT coalesce(sum(valor_centavos), 0) FROM divergences d
         WHERE d.semana = w.semana AND d.status = 'confirmada' AND valor_centavos > 0) AS a_mais_restaurante,
       (SELECT coalesce(-sum(valor_centavos), 0) FROM divergences d
         WHERE d.semana = w.semana AND d.status = 'confirmada' AND valor_centavos < 0) AS a_menos_restaurante,
       (SELECT count(*) FROM divergences d WHERE d.semana = w.semana AND d.status = 'revisao') AS em_revisao
FROM cal_weeks w
ORDER BY w.semana;

CREATE OR REPLACE TABLE summary_by_restaurant AS
SELECT d.restaurante_id, r.nome_fantasia, r.cidade, r.categoria,
       count(*) AS divergencias,
       sum(d.valor_centavos) AS saldo_centavos,
       coalesce(sum(d.valor_centavos) FILTER (WHERE d.valor_centavos > 0), 0) AS a_mais_restaurante,
       coalesce(-sum(d.valor_centavos) FILTER (WHERE d.valor_centavos < 0), 0) AS a_menos_restaurante,
       string_agg(DISTINCT d.semana, ', ' ORDER BY d.semana) AS semanas
FROM divergences d
JOIN stg_restaurants r USING (restaurante_id)
WHERE d.status = 'confirmada'
GROUP BY ALL
ORDER BY abs(sum(d.valor_centavos)) DESC;

CREATE OR REPLACE TABLE repasse_overview AS
SELECT t.repasse_id, t.restaurante_id, t.semana, t.data_pagamento_prevista,
       t.total_extrato, t.total_esperado, t.qtd_pedidos, t.qtd_ajustes, t.ajustes,
       bm.banco_linha_id, bm.status AS status_banco,
       (SELECT count(*) FROM divergences d WHERE d.repasse_id = t.repasse_id AND d.status = 'confirmada') AS divergencias,
       (SELECT count(*) FROM divergences d WHERE d.repasse_id = t.repasse_id AND d.status = 'revisao') AS em_revisao
FROM repasse_residuals t
LEFT JOIN (SELECT repasse_id, min(banco_linha_id) AS banco_linha_id, min(status) AS status
           FROM bank_matches WHERE status IN ('pago', 'reenvio', 'valor_divergente')
           GROUP BY repasse_id) bm USING (repasse_id);
