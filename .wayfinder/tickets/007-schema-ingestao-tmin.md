# Schema obs_kind + ingestão tmin + backfill

Labels: wayfinder:task (AFK)

## Question

Executar a Fase 1 (fundação) em branch/protótipo para desbloquear as decisões: schema obs_kind no DB, parser com obs_kind, fetch de temperature_2m_min e re-backfill de 180 dias de tmin.

Blocked by: nenhuma (frontier) — roda em paralelo com os tickets de decisão

## O que fazer (checklist)

1. db.py: coluna obs_kind TEXT DEFAULT 'high' em historical_obs, model_forecasts, bias_corrections, climatology, trades (+ unique keys ajustadas).
2. data/polymarket.py: parse_question seta obs_kind ('low' se "lowest" na pergunta).
3. data/openmeteo.py: obs_kind param → temperature_2m_min (forecast e archive).
4. data/noaa.py: get_running_min_today; data/wunderground.py: get_running_min_wu.
5. Re-backfill: 180 dias de tmin (ERA5) para as 26 estações → validar contagens (~181 dias/estação).
6. Tudo em branch feature/lowest-temp — NÃO aplicar na main (standing rule do mapa).

## A resolução registra

Contagens reais de linhas por tabela, erros de schema encontrados, e se o fetch de tmin da Open-Meteo funciona igual ao de tmax (mesmos modelos?).
