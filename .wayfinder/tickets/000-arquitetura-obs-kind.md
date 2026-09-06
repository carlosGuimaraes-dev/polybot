# Arquitetura da extensão obs_kind

Labels: wayfinder:grilling
Status: CLOSED (resolvido na sessão de análise de 2026-09-06, aprovado pelo usuário)

## Question

Como estender o bot (hoje hardcoded para máxima diária) para operar também mercados de mínima diária, sem quebrar o fluxo existente?

## Resolution

Parametrizar tudo com `obs_kind: 'high' | 'low'` (default 'high' — compatibilidade total). Plano em 3 fases:

**Fase 1 — Fundação de dados**

1. data/polymarket.py — parse_question detecta "lowest/low/coldest" e seta obs_kind no dict parseado.
2. db.py — coluna obs_kind TEXT DEFAULT 'high' em historical_obs, model_forecasts, bias_corrections, climatology, trades (ALTER TABLE, sem quebrar nada).
3. data/openmeteo.py — fetch_forecast_one_model e fetch_historical_actuals ganham obs_kind → temperature_2m_min.
4. data/noaa.py + data/wunderground.py — get_running_min_today (ASOS min(temps)) e get_running_min_wu (chaves tempLow/minTemp).

**Fase 2 — Sinais** 5. signals/nowcaster.py — get_running_min_c (METAR+ASOS+WU) + compute_nowcast_bucket_prob versão min: final_min ~ min(running_min, modelo); hard-one se running_min ≤ bucket_lo − margem; truncamento effective_hi = min(hi, running_min); temp_rate com semântica invertida (temp subindo = mínima já passou → confiança ↑). 6. signals/bias_corrector.py + data/climatology.py — viés e baseline por obs_kind (bias_corrections ganha obs_kind na unique key). 7. signals/edge_calculator.py — compute_edge lê market['obs_kind']; desativa rain-chill penalty para mínimas (chuva resfria a máxima, não a mínima). 8. main.py — agrupamento (city, target_date) separa por obs_kind; --resolve busca actual_low_c. 9. config.py — bloco conservador próprio p/ mínimas (LOW_MARKET_MIN_EDGE ≈ 0.30, sem NO no início).

**Fase 3 — Validação**: re-backfill tmin (180 dias), scan paper end-to-end, observação por alguns dias.

Mapa de acoplamento "high" (arquivo/função/linha): data/openmeteo.py L52-108, L68, L96, L115, L182-213; data/noaa.py L25-87, L91-146, L192-222; signals/ensemble.py L43-155 (agnóstico); signals/bias_corrector.py L24-211; db.py L64, L75, L73-81, L83-95, L127, L146-157, L343-351, L378-394, L456, L470, L507, L627-727; signals/edge_calculator.py L182, L317-336, L246-258; signals/nowcaster.py L49-106, L109-207; data/wunderground.py L119-160, L245-258; data/climatology.py L22-105; main.py L373, L394-405, L443-450, L461, L501-503, L536-580, L849, L1011; backtest.py L67, L76; real_backtest.py L279, L289, L811; simulate.py L222, L230.
