-- 00_staging.sql
-- What it does: copies the cleaned inputs (registered by Python as raw_*)
-- into typed staging tables and assigns the payout week. An order belongs to
-- the week of its conclusion, not of its creation; a refund belongs to the
-- week it was processed. Rows outside the five weeks are kept but flagged.

CREATE OR REPLACE TABLE stg_orders AS
SELECT o.*,
       CAST(o.criado_em AS DATE) AS data_pedido,
       w.semana,
       (w.semana IS NOT NULL) AS no_periodo
FROM raw_orders o
LEFT JOIN cal_weeks w
  ON o.status = 'entregue'
 AND CAST(o.concluido_em AS DATE) BETWEEN w.inicio AND w.fim;

CREATE OR REPLACE TABLE stg_refunds AS
SELECT r.*,
       w.semana,
       (w.semana IS NOT NULL) AS no_periodo
FROM raw_refunds r
LEFT JOIN cal_weeks w
  ON CAST(r.processado_em AS DATE) BETWEEN w.inicio AND w.fim;

CREATE OR REPLACE TABLE stg_statement AS SELECT * FROM raw_statement;
CREATE OR REPLACE TABLE stg_repasses AS SELECT * FROM raw_repasses;
CREATE OR REPLACE TABLE stg_bank AS SELECT * FROM raw_bank;
CREATE OR REPLACE TABLE stg_plans AS SELECT * FROM raw_plans;
CREATE OR REPLACE TABLE stg_restaurant_plans AS SELECT * FROM raw_restaurant_plans;
CREATE OR REPLACE TABLE stg_restaurants AS SELECT * FROM raw_restaurants;
