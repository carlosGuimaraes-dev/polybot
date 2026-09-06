# Map: Operar mercados "lowest temperature" end-to-end em paper

Labels: wayfinder:map

## Destination

O polybot opera os mercados "lowest temperature" da Polymarket de ponta a ponta em modo paper — parse correto dos buckets, ensemble de tmin, nowcast de mínima com física própria, gates de risco dedicados, resolve com actual_low_c e visibilidade no dashboard — com o mesmo nível de conservadorismo do fluxo atual de máximas.

## Notes

- Domínio: polybot (fork de polymarket-weather-bot) — Python 3, Flask, SQLite, Open-Meteo, Polymarket CLOB/Gamma. Venv em ./venv; daemon paper rodando em background (log: logs/daemon.log).
- Skills a consultar: /grilling e /domain-modeling para tickets de decisão; /research para verificação externa (regras de resolução da Polymarket).
- Fatos verificados na sessão de análise (2026-09-06):
  - 132 mercados "lowest" ativos (Hong Kong, Seoul, Tokyo, Shanghai, Austin), todos daily, negRisk, ~11 buckets/evento; todas as cidades em CITY_ALIASES (config.py:542).
  - O parser parse_question/\_parse_bucket (data/polymarket.py:25-160) reconhece os formatos "between X-Y", "X or below", "X or higher" e "be X on" — city/unit/data extraídos corretamente.
  - **Bug latente descoberto**: bounds de bucket possivelmente off-by-one/off-by-half vs. convenção de resolução (ver ticket "Semântica de resolução dos buckets de temperatura") — afeta TAMBÉM os mercados de máxima existentes.
  - Mapa completo de acoplamento "high" (arquivo/função/linha) está no ticket fechado "Arquitetura da extensão obs_kind".
- **Standing rule**: This map is for investigation and planning only. Do not implement the final production fix while resolving Wayfinder tickets. Experiments and disposable prototypes are allowed only when necessary to validate a hypothesis. Stop when the root cause, selected solution, affected files, implementation steps, risks, and validation criteria are clear. Then create or update a separate implementation issue and hand it off to the appropriate implementation workflow.

## Decisions so far

- [Arquitetura da extensão obs_kind](tickets/000-arquitetura-obs-kind.md) — parametrizar dados/sinais/DB com obs_kind 'high'|'low' (default 'high' preserva comportamento); plano em 3 fases aprovado pelo usuário; mapa de acoplamento anexado.
- [Formatos de mercado lowest verificados](tickets/001-formatos-mercados-lowest.md) — parser reconhece todos os formatos atuais (between / or below / or higher / valor exato), cidades cobertas, mercados daily; lacuna pendente é só a semântica de bounds.

## Not yet specified

- Backtest histórico para tmin: cold start de model_forecasts para mínima (não há histórico de previsões tmin) — como calibrar/validar antes de confiar?
- Pesos de modelo específicos para tmin (skill dos modelos difere na mínima?).
- Risco de portfólio entre máxima e mínima da mesma cidade/data (correlação — MAX_CITY_DATE_FRACTION deve somar ambos?).
- Exibição de obs_kind (high/low) no dashboard e no TUI.
- Mercados semanais "lowest" — existem? vale suportar?

## Out of scope

- Modo live para mercados lowest (destino desta rodada é paper).
- Mercados TSA/crypto com mínima.
- Alterações no projeto polyweather.
