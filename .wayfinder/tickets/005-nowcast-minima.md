# Nowcast de mínima: física e janela horária

Labels: wayfinder:grilling

## Question

Como o nowcast de MÍNIMA deve funcionar — em que horas a mínima "trava", quais horários de nowcast fazem sentido (14h/15h30 servem à máxima), e como fica a semântica do temp_rate?

Blocked by: nenhuma (frontier)

## O que decidir

1. Física: a mínima diária ocorre de madrugada/amanhecer — a partir de quando o running_min é preditivo da mínima final? (analisar obs ASOS de madrugada vs tmin final ERA5 nas 181 days já no DB)
2. Horários de nowcast para low (ex.: 06:00/08:00 locais) e como o daemon agenda por obs_kind (NOWCAST_LOCAL_HOURS é global em daemon.py:55-56).
3. Confirmar física invertida: hard-one se running_min ≤ lo − margem; truncamento effective_hi = min(hi, running_min); temp_rate subindo = mínima passou → confiança ↑.
4. Cross-check WU/METAR para mínima (chaves tempLow do WU são confiáveis?).
