-- 08_bank_candidates.sql
-- What it does: prepares the bank statement for matching. Each line gets a
-- category (payout payment, returned payment, other), the identifiers that
-- may hide in the description (CNPJ root, branch and account, payout
-- reference) and the payee name with the bank prefixes removed. Then it lists
-- candidate restaurants (Jaro-Winkler similarity against the registry names
-- written in bank style) and candidate payouts within ten days of the due
-- date. The final assignment runs in Python (src/reconciliation/bank.py).

CREATE OR REPLACE TABLE bank_lines AS
WITH b AS (
    SELECT *, upper(strip_accents(historico)) AS h FROM stg_bank
)
SELECT banco_linha_id, data, historico, documento, valor, saldo,
       CASE WHEN valor < 0 AND regexp_matches(h, '^(PIX|TED|PAGTO FORNEC|TRANSF PIX)') THEN 'pagamento'
            WHEN valor > 0 AND h LIKE 'DEVOLUCAO%' THEN 'devolucao'
            ELSE 'outro' END AS categoria,
       nullif(regexp_extract(h, 'PIX ENV (\d{8})', 1), '') AS cnpj_raiz,
       nullif(regexp_extract(h, ' AG(\d{4})', 1), '') AS agencia,
       nullif(regexp_extract(h, ' CC(\d+)', 1), '') AS conta,
       nullif(regexp_extract(h, 'REPASSE (\d{4}W\d{2}R\d*)', 1), '') AS ref_repasse,
       trim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
            regexp_replace(h, '^PIX ENVIADO ', ''),
            '^PIX ENV \d{8} ', ''),
            '^TED ENVIADA ', ''),
            '^PAGTO FORNEC REPASSE \S+ ', ''),
            '^TRANSF PIX LOTE \d+ ', ''),
            '^(DEVOLUCAO PIX|PIX) ', ''),
            '( AG\d+ CC\d+| CHAVE INEXISTENTE)$', '')) AS nome_banco
FROM b;

CREATE OR REPLACE TABLE bank_candidates AS
WITH pairs AS (
    SELECT b.banco_linha_id, r.restaurante_id,
           coalesce(b.cnpj_raiz = r.cnpj_raiz, false) AS ev_cnpj,
           coalesce(b.agencia = r.agencia AND b.conta = r.conta_digitos, false) AS ev_conta,
           greatest(
               jaro_winkler_similarity(b.nome_banco, left(r.nome_banco_fantasia, length(b.nome_banco))),
               jaro_winkler_similarity(b.nome_banco, left(r.nome_banco_razao, length(b.nome_banco)))
           ) AS sim_nome
    FROM bank_lines b
    CROSS JOIN stg_restaurants r
    WHERE b.categoria IN ('pagamento', 'devolucao')
)
SELECT *, CASE WHEN ev_cnpj OR ev_conta THEN 1.0 ELSE sim_nome END AS score
FROM pairs
WHERE ev_cnpj OR ev_conta OR sim_nome >= getvariable('sim_min');

CREATE OR REPLACE TABLE bank_repasse_candidates AS
SELECT c.banco_linha_id, c.restaurante_id, c.score, c.ev_cnpj, c.ev_conta, c.sim_nome,
       r.repasse_id, r.semana, r.valor_total, r.data_pagamento_prevista,
       b.data, b.categoria, abs(b.valor) AS valor_banco,
       datediff('day', r.data_pagamento_prevista, b.data) AS dias_apos_previsto,
       (abs(b.valor) = r.valor_total) AS valor_confere,
       (b.ref_repasse IS NOT NULL
        AND replace(replace(r.repasse_id, 'REP-', ''), '-', '') LIKE b.ref_repasse || '%') AS ev_ref
FROM bank_candidates c
JOIN bank_lines b USING (banco_linha_id)
JOIN stg_repasses r ON r.restaurante_id = c.restaurante_id
WHERE datediff('day', r.data_pagamento_prevista, b.data) BETWEEN 0 AND 10;
