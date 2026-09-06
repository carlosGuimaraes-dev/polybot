# Validação paper e critérios de aceite para lowest

Labels: wayfinder:grilling

## Question

Quais critérios definem que a extensão lowest está "funcionando" em paper — quantos scans/dias, que métricas observar, e o que bloqueia concluir o esforço?

Blocked by: [Correção dos bounds off-by-one do parser], [Calibração de incerteza para tmin], [Nowcast de mínima: física e janela horária], [Gates de risco e liquidez para mercados lowest], [Resolve e grouping para mínimas]

## O que decidir

1. Critérios de aceite: N mercados lowest parseados e ranqueados por scan; ≥1 trade paper com edge legítimo; resolve liquidando com tmin real; dashboard exibindo obs_kind.
2. Janela de observação (ex. 5-7 dias de scans sem anomalia) e métricas de saúde (distribuição de edges, % skips por filtro, zero trades em books finos).
3. Critérios de rollback/abort (o que desligaria o fluxo lowest).
4. Definir o handoff: issue de implementação final com checklist consolidado (standing rule do mapa).
