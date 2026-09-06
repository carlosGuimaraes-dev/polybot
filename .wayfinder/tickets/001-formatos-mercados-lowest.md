# Formatos de mercado lowest verificados

Labels: wayfinder:research
Status: CLOSED (verificação realizada 2026-09-06)

## Question

Os mercados "lowest temperature" reais da Polymarket são parseáveis pelo parser atual? Quais formatos existem?

## Resolution

**Sim, parseáveis.** Verificado contra a Gamma API ao vivo:

- 132 mercados "lowest" ativos; cidades: Hong Kong, Seoul, Tokyo, Shanghai, Austin (todas em CITY_ALIASES).
- Formatos de bucket reais: "between 72-73°F" (Austin, bins de 2°F), "22°C or below", "32°C or higher", "be 25°C on September 6" (valor exato, bins de 1°C; HK usa °C com 1 casa).
- Todos são eventos daily, negRisk, ~11 buckets por evento.
- Cidade, unidade e data são extraídas corretamente pelo parse_question.

**Limitação pendente**: os bounds produzidos podem estar off-by-one vs. a convenção de resolução da Polymarket — ver ticket "Semântica de resolução dos buckets de temperatura".
