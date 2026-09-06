# Calibração de incerteza para tmin (base std da mínima)

Labels: wayfinder:grilling

## Question

Que valor inicial usar para o buffer de incerteza inerente do forecast de MÍNIMA (equivalente do BASE_FORECAST_STD_C, calibrado para máximas), dado que não existe histórico de previsões tmin (cold start)?

Blocked by: nenhuma (frontier)

## O que decidir

1. Estimar empiricamente: tmin real (ERA5) vs. skill de modelos de literatura — a incerteza da mínima é maior ou menor que a da máxima?
2. Definir LOW_BASE_FORECAST_STD_C inicial conservador e estratégia de recalibração (após ~30 dias de model_forecasts obs_kind='low', rodar scripts/calibrate_forecast_std.py parametrizado).
3. ENSEMBLE_STD_MIN/MAX (sweet spot 0.5–2.0°C) se aplicam intactos à mínima?
4. Cold start: como o bot se comporta nos primeiros dias (ex.: exigir edge maior até N dias de histórico tmin)?
