# Semântica de resolução dos buckets de temperatura

Labels: wayfinder:research

## Question

Como a Polymarket define a resolução dos mercados de temperatura? A temperatura observada é arredondada (nearest? floor?) e os buckets são intervalos [X, X+1)? "22°C or below" significa temp < 23 ou temp ≤ 22? Em "between 72-73°F", o limite superior real é 73 ou 74°F?

Blocked by: nenhuma (frontier)

## O que fazer

1. Ler as regras oficiais dos mercados (campo description na Gamma API e páginas rules dos eventos em polymarket.com, ex. "Lowest temperature in Hong Kong on September 6").
2. Amostrar mercados RESOLVIDOS de temperatura (highest e lowest) e comparar a temperatura oficial (ASOS/ERA5) com o outcome dos buckets adjacentes para deduzir a convenção empírica (floor vs round vs half-open bins).
3. Confirmar se °F usa bins de 2°F ("between 72-73" = [72,74)) e °C bins de 1°C ("25°C" = [25,26)).
4. Documentar a convenção por unidade e tipo (highest/lowest podem diferir?).
