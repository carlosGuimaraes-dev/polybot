# Gates de risco e liquidez para mercados lowest

Labels: wayfinder:grilling

## Question

Quais gates de risco para mercados de mínima — edge mínimo, regras de NO, threshold de volume (a maioria dos lowest ativos tem $148-158, abaixo do MIN_MARKET_VOLUME_USDC=500) e exposição correlacionada máxima/mínima da mesma cidade?

Blocked by: nenhuma (frontier)

## O que decidir

1. LOW_MARKET_MIN_EDGE inicial (proposta: 0.30, mais alto que 0.25, dado cold start de calibração).
2. NO para mínima: herdar NO_ENTRY_MIN/MAX_PRICE e NO_MIN_ENSEMBLE_STD ou desabilitar NO no início?
3. Liquidez: manter $500 (só buckets grandes como HK 24°C a $3.5k passam) ou reduzir (ex. $250)? O filtro de spread >20% já protege books secos.
4. Correlação high/low: MAX_CITY_DATE_FRACTION (15%) deve somar exposição de máxima + mínima da mesma cidade+data? (uma previsão ruim pode errar ambas)
5. NOWCAST edge override (0.02) — aplicar à mínima só depois do nowcast de mínima implementado e validado.
