# NBA Analysis API

Backend de análise de estatísticas da NBA para inteligência de apostas.

---

## Instalação

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows
source .venv/bin/activate        # Linux/macOS

pip install -r requirements.txt
```

---

## Como rodar

```bash
uvicorn src.main:app --reload
```

- API: `http://localhost:8000`
- Docs interativos: `http://localhost:8000/docs`

---

## Endpoints

### Health
```
GET /health
```

---

## Jogadores

### Buscar jogador pelo nome
```
GET /players/search?name=lebron
```
Retorna `id`, `full_name`, `is_active`. Use o `id` nas demais rotas.

### Game log da temporada
```
GET /players/2544/gamelog?season=2024-25
```

### Estatísticas jogo a jogo (para gráficos)
```
GET /players/2544/stats/games?season=2024-25
```

### Análise geral da temporada
```
GET /players/2544/analysis/season?season=2024-25
```
Médias gerais, últimos 5/10 jogos e trend.

### Média de pontos por quarto
```
GET /players/2544/analysis/points-by-period?season=2024-25&last_games=10
```
> Faz 1 chamada PBP por jogo — pode levar 30–120 s com `last_games=10`.

### Dashboard completo
```
GET /players/2544/dashboard?season=2024-25&last_games=10
```
Combina temporada, últimos jogos, pontos por quarto e tendência.

### Play-by-play (jogo já finalizado)
```
GET /games/0022400001/play-by-play
```

### Pontos por quarto (jogo único)
```
GET /players/2544/games/0022400001/points-by-period
```

---

## Live / Tempo Real

> **Nota:** Os endpoints live usam `nba_api.live` e têm cache em memória (boxscore: 15 s, scoreboard: 30 s, médias da temporada: 10 min). A análise é marcada como `"analysis_type": "experimental_live_analysis"`.

### 1. Listar jogos do dia
```
GET /games/live/today
```
Retorna todos os jogos do dia com placar, período, clock e status.

### 2. Boxscore live de um jogo
```
GET /games/{game_id}/live-boxscore
```
Retorna estatísticas em tempo real de todos os jogadores que já entraram em quadra.

**Como obter um `game_id` live:**
1. Chame `/games/live/today`
2. Copie o `game_id` do jogo desejado (ex: `"0022500001"`)

### 3. Análise live de todos os jogadores
```
GET /games/0022500001/live-analysis?season=2025-26
```
Para cada jogador que já jogou:
- Busca média da temporada
- Calcula expectativa proporcional aos minutos jogados
- Compara com estatísticas atuais
- Classifica como `hot` / `above_average` / `normal` / `below_average` / `cold`

**Fórmulas:**
```
expected_points   = season_avg_points   × (current_minutes / season_avg_minutes)
shooting_impact   = bônus por acertos/volume acima do esperado
                  - penalidade por erros acima do esperado
score             = (pts_diff × 0.85)
                  + (reb_diff × 0.6)
                  + (ast_diff × 0.7)
                  + shooting_impact
```

O `shooting_impact` considera, ao vivo vs esperado por minutos:
- `FGM` e `3PM` acima da média esperada (bônus)
- `FGA` acima da média esperada (bônus leve de volume)
- erros de arremesso (`FGA-FGM`) acima do esperado (penalidade)
- `FTM` acima do esperado (bônus) e erros de lance livre (`FTA-FTM`) acima do esperado (penalidade)

**Status por score:**
| Score | Status |
|---|---|
| ≥ 5 | hot |
| ≥ 2 | above_average |
| > -2 | normal |
| > -5 | below_average |
| ≤ -5 | cold |

> **Aviso de performance:** A primeira chamada buscará médias da temporada de cada jogador (uma chamada à NBA API por jogador). Com ~20 jogadores, pode levar 1–3 minutos. Chamadas subsequentes dentro de 10 minutos usam cache e são instantâneas.

### 4. Comparar um jogador específico
```
GET /players/2544/games/0022500001/live-comparison?season=2025-26
```
Retorna a comparação individual de um jogador com sua média da temporada.

### 5. Ranking dos mais quentes
```
GET /games/0022500001/live-hot-ranking?season=2025-26&limit=5
```
Retorna os N jogadores com maior `score` no jogo atual, ordenados do melhor para o pior.

---

## Como obter um `game_id`

**Para jogos históricos:**
1. `/players/search?name=lebron` → `id: 2544`
2. `/players/2544/gamelog?season=2024-25` → copie `game_id`

**Para jogos ao vivo:**
1. `/games/live/today` → copie `game_id` do jogo desejado

---

## Estrutura do projeto

```
src/
  main.py
  services/
    nba_service.py               # Acesso à nba_api (retry, fetch)
    player_analysis_service.py   # Médias históricas, dashboard
    live_game_service.py         # Scoreboard e boxscore live + cache
    live_analysis_service.py     # Comparação live vs histórico
  schemas/
    nba_schemas.py               # Schemas base
    analysis_schemas.py          # Schemas de análise histórica
    live_schemas.py              # Schemas live
  utils/
    converters.py                # Parsing de eventos play-by-play
    stats.py                     # Médias, score, status, trend
    time_utils.py                # parse_minutes_to_float, format_game_clock
    cache.py                     # SimpleCache com TTL
requirements.txt
README.md
```

---

## Limitações da `nba_api` para dados em tempo real

| Limitação | Detalhe |
|---|---|
| Delay | Os dados live têm atraso de ~30–60 s em relação ao jogo real |
| Rate limiting | Muitas chamadas seguidas podem ser bloqueadas pela NBA.com |
| Instabilidade | Endpoints live podem retornar erro durante jogos com alta carga |
| Dados inconsistentes | `minutes` e outros campos podem vir em formato diferente ao longo da temporada |
| Sem suporte oficial | A `nba_api` usa endpoints não documentados — podem mudar sem aviso |

### Quando migrar para API paga?

Se o produto evoluir para uso em produção, considere:
- **SportsDataIO** — dados live com delay < 5 s, bem documentado
- **Sportradar** — API premium com dados de arbitragem e odds integrados
- **Stats Perform** — solução enterprise

---

## Próximos passos

1. **Cache persistente** — Redis para compartilhar cache entre instâncias
2. **PostgreSQL** — persistir game logs e evitar chamadas repetidas à NBA API
3. **Jobs de ingestão** — atualizar histórico automaticamente após cada rodada
4. **Odds / player props** — cruzar análise live com linhas de aposta
5. **WebSocket** — push de atualizações live para o frontend sem polling
6. **Frontend** — gráficos de desempenho consumindo `/stats/games` e `/live-hot-ranking`
7. **Docker** — containerizar para deploy
8. **Auth JWT** — proteger a API em produção
