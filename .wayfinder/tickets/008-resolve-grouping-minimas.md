# Resolve e grouping para mínimas

Labels: wayfinder:task (AFK)

## Question

Como o pipeline operacional (agrupamento, trade placement e resolução) trata obs_kind='low' — incluindo a busca de actual_low_c no resolve?

Blocked by: [Schema obs_kind + ingestão tmin + backfill]

## O que decidir/executar (protótipo)

1. main.py:394-405 — agrupamento (city, target_date) separa por obs_kind (tmax e tmin do mesmo dia usam ensembles distintos).
2. main.py --resolve e db.resolve_trade (db.py:627-727) — trades de mínima liquidam com actual_low_c (ERA5/ASOS tmin do dia).
3. trades table — coluna nova actual_low_c (preferir sobre reuso condicional de actual_high_c).
4. Protótipo em branch: resolver um mercado lowest já vencido end-to-end e registrar o resultado.
