# Correção dos bounds off-by-one do parser

Labels: wayfinder:grilling

## Question

Dada a convenção de resolução verificada, como normalizar os bounds no \_parse_bucket (data/polymarket.py:116-150) — e qual o impacto nos mercados de MÁXIMA existentes (o bug afeta o bot atual também)?

Blocked by: [Semântica de resolução dos buckets de temperatura]

## O que decidir

1. Regras de normalização por formato: "X or below" → hi = X + bin; "between A-B°F" → hi = B + bin (bins de 2°F?); "be X on" → [X, X+bin).
2. Dados existentes: trades/markets gravados com bounds antigos — recalcular ou versionar?
3. Re-rodar backtest de máximas com bounds corrigidos: os win rates citados nos comentários do config mudam? Os gates (MIN_EDGE=0.25 etc.) continuam válidos?
4. Escrever o patch como issue de implementação separada (standing rule do mapa).
