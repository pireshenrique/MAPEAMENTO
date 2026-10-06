# Competitive Intelligence Radar

Sistema de inteligência competitiva que monitora concorrentes da **Lorenzetti** (Deca, Roca, Celite, Docol, Tigre, Kohler, Dexco):
coleta notícias, elimina ruído e duplicatas, classifica com IA (categoria, relevância 1–5, impacto sob a ótica da Lorenzetti,
resumo executivo) e apresenta tudo em uma interface web com filtros e busca.

## Arquitetura

```
COLLECT → NORMALIZE → VALIDATE → MATCH → DEDUP → STORE        (radar collect)
                                          STORE → CLASSIFY → SAVE ANALYSIS   (radar analyze)
                                                         DISPLAY (API + web)  (radar serve)
```

| Módulo | Responsabilidade |
|---|---|
| `radar/settings.py` | `.env` (segredos) + YAML (regras) validados com Pydantic |
| `radar/collectors/` | Contrato `SourceCollector`, `QueryStrategy`, coletor News API, registro de fontes |
| `radar/pipeline/` | `normalize`, `validate`, `match` (concorrente por contexto), `runner` (orquestração) |
| `radar/dedup/` | Deduplicação em 4 camadas |
| `radar/ai/` | `LLMProvider`, adapter Anthropic, `FakeLLMProvider`, prompt versionado, parser/schema, `Analyzer`, serviço |
| `radar/db/` | SQLAlchemy 2.0 (tabelas, repositórios, consultas), Alembic |
| `radar/api/` | FastAPI: API JSON (`/api/*`) e páginas HTML (Jinja2 + HTMX) |
| `radar/cli.py` | `collect`, `analyze`, `run`, `reprocess`, `serve` |

**Tecnologias:** Python 3.11+, FastAPI, Jinja2 + HTMX (servido localmente, sem CDN), SQLAlchemy 2 + Alembic, SQLite, Pydantic v2,
httpx, rapidfuzz, Typer, pytest.

### Decisões arquiteturais
- **Persistir antes de classificar.** A IA roda sobre notícias já gravadas (`analysis_status`: `pending|done|failed|skipped`).
  Se a IA falhar, nada se perde e `radar reprocess` tenta de novo. Após 3 falhas seguidas do provedor a análise é interrompida.
- **Banco portável.** Só tipos genéricos do SQLAlchemy; para PostgreSQL basta mudar `DATABASE_URL` (e instalar o driver). A busca textual usa `LIKE`, sem recursos específicos do SQLite.
- **Deduplicação conservadora** (sempre dentro do mesmo concorrente e de uma janela de ±3 dias): (1) URL normalizada e (2) `external_id`+fonte iguais → não reinsere; (3) título normalizado igual → grava como `duplicate` (oculta no feed, não vai para a IA); (4) similaridade ≥ 90 → grava como `possible_duplicate` (aparece com selo e continua sendo analisada). Nada é apagado.
- **Match por contexto.** Aliases fortes identificam sozinhos; aliases ambíguos (ex.: "Roca", "Tigre") exigem escrita capitalizada **e** termos de contexto do setor; `exclude_terms` (futebol, felino…) rejeitam homônimos. Uma notícia pode pertencer a mais de um concorrente.
- **Impacto sempre sob a ótica da Lorenzetti**; incerteza ⇒ `neutral` com explicação. `is_relevant` é derivado da nota (≥ 3).
- **Auditoria:** a resposta bruta da IA, o modelo e a versão do prompt são gravados em `news_analysis`.
- **Sem JS próprio e sem segredos no navegador.** Texto externo é escapado; URLs que não sejam http(s) são neutralizadas.
- **Gráficos honestos:** a página *Inteligência* só renderiza um gráfico quando a amostra ≥ `ui.min_chart_sample`.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env     # preencha NEWS_API_KEY e AI_API_KEY
```

## Variáveis de ambiente (`.env`, nunca versionado)

| Variável | Descrição | Padrão |
|---|---|---|
| `NEWS_API_KEY` | Chave da News API | — |
| `AI_PROVIDER` | `anthropic` (único implementado) | `anthropic` |
| `AI_API_KEY` | Chave do provedor de IA | — |
| `AI_BASE_URL` | Reservada para provedores OpenAI-compatíveis | — |
| `DATABASE_URL` | URL SQLAlchemy | `sqlite:///data/radar.db` |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `text` ou `json` | `INFO` / `text` |
| `APP_HOST` / `APP_PORT` | Servidor web | `127.0.0.1` / `8000` |
| `CONFIG_DIR` | Pasta dos YAMLs | `config` |

## Configuração (`config/`)

- `competitors.yaml` — concorrentes (aliases, domínios, palavras-chave, termos de contexto/exclusão, categorias prioritárias, peso).
- `categories.yaml` — categorias (a IA pode sugerir outras; desconhecidas viram "Outro" e o nome original vai para a subcategoria).
- `company_profile.yaml` — perfil da Lorenzetti enviado à IA. Hoje só contém os segmentos definidos; produtos, marcas, tecnologias, mercados etc. estão reservados (vazios, e omitidos do prompt).
- `settings.yaml` — backfill (7 dias), limites, deduplicação, **modelo de IA** (`ai.model`, padrão `claude-haiku-4-5-20251001`), tentativas, página, amostra mínima de gráficos.

## Execução

```bash
radar run                 # coleta + análise (1ª vez: backfill de 7 dias; depois incremental)
radar collect [--days N]  # só coleta e armazena (sem IA)
radar analyze [--limit N] # analisa pendentes e falhas com tentativas restantes
radar reprocess [--all]   # zera tentativas das falhas (--all: reanalisa tudo, ex.: prompt novo) e analisa
radar serve               # http://127.0.0.1:8000  (API em /api, docs em /api/docs)
```
As migrations rodam automaticamente. Agende `radar run` via cron/systemd (ex.: a cada 6 h, ver `collection.interval_hours`).
Cada execução registra em `collection_runs` (encontradas, novas, duplicadas, descartadas, analisadas, falhas, erros) e nos logs.
Código de saída ≠ 0 se houve erros.

**Custo de IA:** duplicatas certas e notícias com baixa confiança de match não são enviadas; `ai.max_analyses_per_run` limita cada execução; uma chamada por notícia (mais uma só se o JSON vier inválido).

## Testes

```bash
pytest          # sem internet, sem chaves, sem consumir créditos (fixtures + FakeLLMProvider)
```

## Como adicionar um concorrente
Inclua um bloco em `config/competitors.yaml` e rode `radar run` — nenhum código muda.
Nomes comuns devem ir em `ambiguous_aliases` (exigem contexto). Quem sai do YAML fica inativo; o histórico é preservado.

## Como adicionar uma nova fonte (RSS, site oficial, outra API)
1. Crie `radar/collectors/minha_fonte.py` com uma classe com `name` e `fetch(competitor, since, until) -> list[RawArticle]` (contrato `SourceCollector`; levante `CollectorError` em falhas).
2. Registre-a em `radar/collectors/registry.py::build_collectors`.
3. Todo o restante (normalização, match, dedup, IA, UI) funciona sem alterações. Se a fonte tiver ID estável, preencha `external_id` (ativa a camada 2 de dedup).
Estratégias de busca por concorrente: implemente `QueryStrategy.build(competitor)` e passe ao coletor.

## Como configurar a IA / adicionar um provedor
- Anthropic: defina `AI_API_KEY` e, se quiser, `ai.model` em `settings.yaml`.
- Novo provedor: implemente `LLMProvider.complete(system, user, *, model, max_tokens, temperature) -> str` (levante `LLMError`) em `radar/ai/` e adicione-o a `radar/ai/factory.py`. O prompt, o parser e a recuperação de JSON inválido são independentes do fornecedor.
- Alterou o prompt? Incremente `PROMPT_VERSION` em `radar/ai/prompts.py` e use `radar reprocess --all`.

## Limitações conhecidas
- **News API (plano gratuito):** uso apenas para desenvolvimento, ~100 requisições/dia, artigos com 24 h de atraso e `content` truncado (~200 caracteres); a cobertura de portais brasileiros é irregular. Para uso real, use plano pago ou outra fonte (o coletor é isolado para isso).
- A News API não fornece ID estável; a camada 2 de dedup só atua em fontes futuras que forneçam.
- Busca textual do SQLite diferencia acentos (ex.: "fabrica" não encontra "fábrica").
- O peso de relevância por concorrente (`weight`) já é configurável, mas ainda não influencia o ranking.
- Sem autenticação (uso local).
