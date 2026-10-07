# Especificação — Relatório Diário do Competitive Intelligence Radar

> Status: **especificação (nada implementado)**. Este documento é o contrato para a futura implementação do relatório e da
> classificação por IA. Não altera o comportamento atual do sistema.

**Pergunta que o relatório responde:** *"O que aconteceu com os concorrentes e o que disso merece nossa atenção?"*
Leitor: Planejamento Estratégico da Lorenzetti. Leitura alvo: **até 3 minutos**. Concorrentes: Deca, Roca, Celite, Docol, Tigre, Kohler, Dexco.

Princípios (valem para todas as seções):
1. **Menos é mais.** Um dia calmo gera um relatório curto, e isso é o resultado correto. Nunca preencher espaço.
2. **Fato ≠ interpretação ≠ impacto.** Cada um aparece separado e rotulado (seção 5).
3. **Assunto principal manda.** A notícia é do concorrente de quem ela fala, não de quem apenas é citado (seção 4).
4. **"Não foi possível determinar" é uma resposta válida.** O sistema nunca inventa impacto, tendência ou recomendação.

---

## 1. Estrutura do relatório diário

Ordem fixa. Seções vazias **são omitidas** (exceto o Resumo Executivo, que sempre existe).

| # | Seção | Conteúdo | Limite |
|---|---|---|---|
| 1 | **Resumo executivo** | N movimentos relevantes (por nível); 2–4 linhas com os principais acontecimentos; o principal sinal competitivo (1 frase, ou "nenhum sinal relevante hoje"); aviso se houver item Crítico | ≤ 6 linhas |
| 2 | **Alertas prioritários** | Só itens **Crítico** e **Alto**, ordenados por pontuação | 3–5 itens |
| 3 | **Movimentos por concorrente** | Itens **Médio** (e Alto/Crítico que excederam o limite de alertas), agrupados por concorrente, só concorrentes com movimento | ≤ 2 itens por concorrente, ≤ 8 no total |
| 4 | **Notícias monitoradas** | Itens **Baixo** relevantes: uma linha cada (concorrente · título · fonte · link) | ≤ 5 linhas |
| 5 | **Sinais e tendências** | Padrões com evidência suficiente (regra abaixo) | ≤ 3 itens; omitida se não houver |

**Regra de evidência para "Sinais e tendências"** (determinística): um sinal só é publicado se houver **≥ 3 itens
Médio+ independentes** (fontes/artigos distintos, não duplicados) com o mesmo concorrente + categoria, ou a mesma
categoria em ≥ 3 concorrentes, dentro de **30 dias**. Cada sinal lista as notícias que o sustentam, marcadas como
**"Interpretação"**. Uma notícia isolada nunca gera tendência. Com a base atual (poucas notícias casadas por semana),
espera-se que esta seção fique vazia durante semanas — isso é correto.

Cabeçalho: data, janela coberta (padrão: últimas 24h, `published_at` em fuso America/Sao_Paulo) e uma linha de
cobertura: *"Fontes consultadas: X de Y"* (detalhes no relatório operacional, seção 9).

---

## 2. Classificação de impacto

Pontuação interna **0–100** (armazenada); o relatório mostra só o nível.
`pontuação = base_do_tipo_de_evento + ajustes` (limitada a 0–100). Os valores abaixo são o ponto de partida e ficam em
configuração, para calibrar com dados reais.

### Níveis

| Nível | Pontuação | Critério objetivo |
|---|---|---|
| **Crítico** | 85–100 | Movimento que pode alterar a estrutura do mercado ou o posicionamento da Lorenzetti no curto prazo: M&A/fusão/venda envolvendo concorrente principal; nova fábrica ou fechamento de fábrica relevante; investimento declarado ≥ R$ 100 mi; entrada em nova categoria **diretamente concorrente** das linhas da Lorenzetti; mudança regulatória que atinge o concorrente de forma assimétrica |
| **Alto** | 65–84 | Mudança estratégica clara ou movimento material: reestruturação/mudança de modelo; investimento ou expansão de capacidade declarados (valor < R$ 100 mi ou sem valor); lançamento de linha/produto importante; troca de CEO/diretoria relevante; resultado financeiro com desvio material (guidance, queda/alta forte, prejuízo); movimento de preço/canal amplo (reajuste geral, novo canal ou varejista-chave) |
| **Médio** | 40–64 | Informação útil para acompanhamento: lançamento pontual de produto; resultado financeiro em linha; campanha/patrocínio de grande porte; parceria; premiação; mudança de liderança de segunda linha; inovação/tecnologia sem data de lançamento |
| **Baixo** | 15–39 | Relacionada, mas sem decisão associada: ações institucionais, ESG genérico, participação em feiras, comentário de analista, citação em matéria de mercado |
| *(fora)* | 0–14 | Não entra no relatório (seção 4: irrelevante, contextual ou falso positivo) |

### Cálculo (deterministicamente auditável)
- **Base** pelo tipo de evento: M&A 80 · fábrica (abertura/fechamento) 75 · investimento/expansão de capacidade 65 ·
  mudança estratégica/reestruturação 65 · entrada em nova categoria 65 · resultado financeiro 55 · liderança (C-level) 55 ·
  preço/canal 50 · lançamento 50 · regulatório 50 · inovação 40 · marca/campanha 30 · ESG 25 · demais 20.
- **Ajustes:** `+15` valor/escala declarados e materiais (ex.: ≥ R$ 100 mi); `+10` concorrente de maior peso para a
  Lorenzetti (campo `weight`) ou sobreposição direta de portfólio; `+10` fonte tier 1 (CVM/oficial) confirmando;
  `+5` confirmação por ≥ 2 fontes independentes; `−15` apenas rumor/"segundo fontes"; `−20` sem dado concreto
  (intenção vaga, sem prazo/valor); `−10` assunto secundário na matéria.
- **Tetos:** nada é **Crítico** sem fato concretizado/anunciado (rumor limita a **Alto**); nada é **Alto/Crítico** se a
  pontuação de relevância (seção 4) for inferior a "A".
- **Não é impacto:** mera menção ao concorrente, cotação/recomendação de analista sem fato novo, notícia reciclada de
  mais de 7 dias sem fato novo.

> Observação: o campo atual `competitive_impact` (positive/neutral/negative) mede **direção** para a Lorenzetti, não
> **magnitude**. São eixos diferentes; o relatório precisa da magnitude (nível/pontuação). A direção pode continuar,
> mas só deve ser mostrada quando houver base (seção 5).

---

## 3. Taxonomia de categorias

Proposta enxuta: **11 categorias + Outros** (a configuração atual tem 19, com sobreposições).

| Categoria | Cobre | Substitui hoje |
|---|---|---|
| Estratégia | Mudança de rumo, reestruturação, entrada/saída de segmento, parcerias estratégicas | Estratégia, Parceria |
| M&A | Fusões, aquisições, desinvestimentos, joint ventures | M&A |
| Investimentos e Expansão | CAPEX, aportes, expansão de capacidade, geográfica ou de canais | Investimento, Expansão |
| Produtos e Inovação | Lançamentos, novas linhas, tecnologia, P&D | Produto, Lançamento, Tecnologia |
| Fábricas e Operações | Abertura, fechamento, paradas, mudanças logísticas/cadeia | Fábrica |
| Resultados financeiros | Balanços, guidance, rating, dívida | Resultado financeiro |
| Preço e Canais | Reajustes, política de preço, varejo, distribuição, e-commerce | Preços, Distribuição |
| Marca e Marketing | Campanhas, patrocínios, posicionamento | Marketing |
| ESG | Sustentabilidade, governança, relatórios e metas | Sustentabilidade, ESG |
| Liderança | Mudanças de executivos/conselho | Gestão |
| Regulatório | Normas, tributos, antidumping, litígios com efeito setorial | Regulamentação |
| Outros | Não se enquadra (uso residual; meta < 10 % dos itens) | Outro, Mercado |

Decisões e justificativas:
- **Fundidas** por serem indistinguíveis na prática ou por gerarem inconsistência de classificação: Produto+Lançamento+Tecnologia;
  Investimento+Expansão; Sustentabilidade+ESG; Preços+Distribuição.
- **"Mercado/Concorrência" não é categoria de evento**: é tendência/contexto, tratado na seção "Sinais e tendências"
  e na regra D (menção contextual). Manter como categoria faria dela um saco de gatos.
- **"Pessoas/Liderança" → "Liderança"** (escopo: executivos e conselho; RH/contratações comuns são irrelevantes).
- **Regra de desempate:** um item tem **uma** categoria principal (o evento mais relevante). Ex.: aquisição de fábrica → M&A.
- **Ausente de propósito:** "Jurídico/Litígios" entra em Regulatório só se tiver efeito setorial; caso contrário, Outros.
  Reavaliar após 60 dias de dados: se Outros > 10 %, olhar o que há lá antes de criar categoria nova.
- Compatibilidade: a lista é só uma proposta; a implementação deve mapear categorias antigas → novas, sem apagar histórico.

---

## 4. O que entra no relatório (regras de relevância)

Cada notícia casada recebe **uma** classe, nesta ordem de avaliação (a primeira que se aplicar):

| Classe | Definição | Destino |
|---|---|---|
| **E. Falso positivo** | O alias casou com outra coisa (homônimo: "Tigre" animal/time, "Roca" geológico, "Deca" prefixo), ou o contexto setorial não confere | Descartada; contada no operacional |
| **D. Menção contextual** | O concorrente aparece, mas não é o sujeito: lista de empresas, comparação, exemplo, "como Deca e Dexco…", fala de analista; o fato principal é de outra empresa ou assunto | **Não atribuída** ao concorrente citado; fica fora do relatório (guardada para o operacional) |
| **C. Irrelevante** | Sujeito é o concorrente, mas sem relação com negócios (esporte patrocinado sem escala, sorteio, promoção de varejo trivial, nota social) ou fato antigo (> 7 dias sem fato novo) | Fora |
| **B. Relacionada, baixo valor** | Sujeito é o concorrente, tema de negócio, sem decisão associada | "Notícias monitoradas" (impacto Baixo) |
| **A. Competitivamente relevante** | Sujeito é o concorrente e há fato concreto de uma das categorias acima | Seções 2–3 (Médio ou mais) |

**Determinação do assunto principal** (sujeito), por evidência, em ordem de força:
1. o concorrente é o **sujeito do título** (ou o único nome de empresa no título);
2. concentração de menções no 1º parágrafo/descrição;
3. proporção de menções no corpo (quando existir; NeoFeed não tem corpo → depende de título+descrição);
4. fonte oficial (CVM/IPE da própria empresa) → sujeito é a emissora por definição.

Se há **dois ou mais sujeitos** legítimos (ex.: aquisição da Celite pela Dexco), a notícia é atribuída aos dois, com um
deles marcado como **principal** (`main_subject`) e o outro **relacionado**. No relatório, aparece **uma vez** (sob o
principal), citando o outro. Exemplo do enunciado: matéria sobre a Kohler que cita Deca/Dexco só como comparação →
atribuída a Kohler, **nunca** a Deca/Dexco.

Casos de borda:
- Matéria **setorial** (ex.: "mercado de louças cresce 5 %") que cita vários concorrentes: não é movimento de nenhum
  deles; vai para a análise de tendências, se tiver fato; senão, fora.
- **Duplicatas** (mesmo fato em vários veículos): 1 item, com todas as fontes listadas; a confirmação por ≥ 2 fontes
  pode elevar a pontuação.
- **Rumor/"segundo fontes":** entra rotulado como não confirmado e com teto de nível Alto.

> Atenção (comportamento atual): o MATCH hoje aceita qualquer menção forte (ex.: alias no título → 0,95) e atribui a
> notícia a **todos** os concorrentes citados. Ele não distingue sujeito de contexto. A regra D exige uma etapa nova
> (determinística + IA) — registrada na seção 8 como lacuna.

---

## 5. Fato, interpretação e possível impacto

Cada item do relatório separa três camadas, com rótulo visível:

| Camada | O que é | Origem permitida | Rótulo |
|---|---|---|---|
| **Fato** | O que a fonte afirma, sem adjetivos: quem, o quê, quanto, quando | Somente o texto da notícia; cita a fonte | *O que aconteceu* |
| **Interpretação** | Leitura do que o fato significa para a empresa/mercado | Inferência explícita a partir de fatos; precisa apontar o fato que a sustenta | *Leitura* |
| **Possível impacto** | Efeito plausível sobre a Lorenzetti (segmento, canal, preço, capacidade) | Só se houver sobreposição conhecida entre o concorrente e o perfil da Lorenzetti (`company_profile.yaml`) | *Possível impacto para a Lorenzetti* |

Regras:
1. **Fato** nunca contém opinião; números e datas são copiados da fonte, não estimados. Se a fonte não traz o dado, o dado não aparece.
2. **Interpretação** usa linguagem condicional ("indica", "sugere") e só aparece se houver pelo menos um fato que a sustente. Máx. 1 frase.
3. **Possível impacto** só é escrito quando duas condições se cumprem: (a) o fato é de nível Médio+; (b) há ligação
   verificável com o perfil da Lorenzetti (mesma categoria de produto, mesmo canal, mesmo segmento de preço). Caso contrário:
   **"Não foi possível determinar o impacto com a informação disponível."**
4. **Sem recomendação.** O sistema não diz o que a Lorenzetti deve fazer. No máximo, aponta o que acompanhar
   ("acompanhar: confirmação do investimento"), e só quando o próprio fato deixa algo em aberto.
5. Impacto é **hipótese** e vem sempre com a base: *"Possível impacto … (base: Kohler atua no segmento premium, mesmo da linha X)."*

Exemplo:
- **Fato:** "A Kohler encerrou a produção em sua fábrica no Brasil, segundo comunicado divulgado hoje."
- **Leitura:** "Indica mudança no modelo de atuação da empresa no país."
- **Possível impacto:** "Pode alterar a dinâmica competitiva no segmento premium (base: sobreposição de portfólio com a linha premium da Lorenzetti)."

---

## 6. Tamanho do relatório

Limites (rígidos, com corte por pontuação):

| Elemento | Limite | Motivo |
|---|---|---|
| Alertas prioritários | **3–5** (nunca > 5) | Mais que 5 alertas deixam de ser prioridade |
| Movimentos por concorrente | ≤ 2 por concorrente, ≤ 8 no total | Cabe em uma tela |
| Notícias monitoradas | ≤ 5 linhas de 1 frase | Só referência |
| Sinais e tendências | ≤ 3 | Só com evidência |
| **Total de itens com texto completo** | **≤ 10** | ~3 minutos de leitura |

- Excedentes **não somem**: contador "+N itens de menor prioridade disponíveis na interface" com link.
- **Dia fraco = relatório curto.** Sem itens Médio+, o relatório diz: *"Nenhum movimento relevante nas últimas 24h"* + a linha de cobertura.
- Se houver menos de 3 itens Alto/Crítico, publicar só os que existem (não completar com itens menores).
- Itens classe A/B de dias anteriores **não** se repetem; a evolução de um fato (ex.: confirmação oficial) entra como item novo, marcado "atualização".
- Cada texto de item: *o que aconteceu* ≤ 2 frases; *por que importa* ≤ 1; *possível impacto* ≤ 1 (ou a frase-padrão de indeterminado).

---

## 7. Formato de cada notícia (contrato)

```
CONCORRENTE: <nome>                        [+ relacionado: <nome>, se houver]
PRIORIDADE: Crítica | Alta | Média | Baixa
CATEGORIA: <categoria da taxonomia>
CONFIANÇA: Confirmado | Não confirmado (rumor)

O que aconteceu:            (FATO — ≤ 2 frases, só o que a fonte afirma)
Por que importa:            (LEITURA — ≤ 1 frase, condicional; omitir se não houver fato que a sustente)
Possível impacto para a Lorenzetti:   (≤ 1 frase com base explícita, ou
                                       "Não foi possível determinar o impacto com a informação disponível.")
Fonte:                      <veículo> — <URL>   [+ outras fontes que confirmam]
Data:                       <data/hora de publicação, America/Sao_Paulo>
```

- **Alertas prioritários:** todos os campos.
- **Movimentos por concorrente:** sem PRIORIDADE (vem pelo agrupamento) e sem CONFIANÇA quando "Confirmado".
- **Notícias monitoradas:** uma linha — `Concorrente · título · veículo · data · link`.
- Campos de texto livre são **gerados pela IA a partir do texto da notícia**; IDs/links/datas vêm do banco.
- Todo texto de fonte externa é escapado (mesma política atual da interface).

---

## 8. Dados necessários vs. o que já existe

Legenda — **Origem**: `Já existe` · `Det.` = calculável deterministicamente · `IA` = depende de classificação por IA ·
`Enr.` = depende de enrichment (buscar texto completo/dados externos).

### 8.1 Já armazenado (tabela `news`, `news_analysis`, `competitors`, `sources`, `collection_runs`)

| Necessidade do relatório | Campo atual | Situação |
|---|---|---|
| Concorrente | `news.competitor_id` (+ `match_confidence`, `match_evidence`) | Existe, mas **sem noção de assunto principal** |
| Título, descrição, URL, data, fonte | `title`, `description`, `url`, `published_at`, `source_name`, `source_id`, `source_domain` | Existe |
| Corpo e sua qualidade | `raw_content`, `body_status` (`feed`/`none`/…) | Existe (NeoFeed = `none`) |
| Duplicidade | `dup_status`, `dup_of_id`, `dup_score` | Existe |
| Categoria | `news_analysis.category` | Existe; taxonomia atual (19) difere da proposta (11) |
| Relevância | `news_analysis.relevance_score` (1–5), `is_relevant` | Existe, mas é nota subjetiva da IA, sem critérios objetivos |
| Resumo / pontos-chave | `summary`, `key_points` | Existe |
| "Por que importa" | `strategic_reason` | Existe, mistura leitura e impacto |
| Direção para Lorenzetti | `competitive_impact` (positive/neutral/negative), `sentiment` | Existe; é direção, **não magnitude** |
| Auditoria da IA | `model_used`, `prompt_version`, `raw_response`, `analyzed_at` | Existe |
| Estado/erros por fonte | `sources.*` (`last_status`, `last_error`, `consecutive_failures`, `fetches_ok/failed`) | Existe |
| Contagem por execução | `collection_runs` (`found`, `new`, `duplicates`, `discarded`, `errors`, `source`) | Existe |
| Perfil da Lorenzetti e peso do concorrente | `config/company_profile.yaml`, `competitors[].weight` | Existe (usar na pontuação) |

### 8.2 Campos novos (futuros — **não implementar agora**)

| Campo | Para quê | Origem |
|---|---|---|
| `main_subject` (bool por par notícia×concorrente) + `mention_role` (`subject`/`related`/`context`) | Regra D: separar sujeito de contexto | **IA** (apoiada por heurística **Det.** de título/1º parágrafo) |
| `relevance_class` (A/B/C/D/E) | Seção 4: decide o destino | **IA** + regras **Det.** (homônimos/`exclude_terms` já existem) |
| `event_type` (M&A, fábrica, lançamento, …) | Base da pontuação | **IA** |
| `impact_score` (0–100) e `impact_level` | Prioridade do relatório | **Det.** (fórmula sobre `event_type` + ajustes) |
| Ajustes: `has_amount`, `amount_value`, `is_rumor`, `confirmed_by_n_sources`, `source_tier` | Entram na fórmula | `source_tier` e confirmação por fontes: **Det.**; `amount_value`, `is_rumor`: **IA** (extração do texto) |
| `fact` (texto), `interpretation` (texto), `possible_impact` (texto) + `impact_basis` | Camadas da seção 5 (hoje `summary`/`strategic_reason` misturam) | **IA** |
| `impact_determinable` (bool) | Frase "não foi possível determinar" | **IA** com regra **Det.** (sobreposição com `company_profile`) |
| `category` (taxonomia nova) e mapa antigas→novas | Seção 3 | **IA** + mapa **Det.** |
| `report_date`, `report_rank`, `included_in_report` (ou tabela `reports`/`report_items`) | Evitar repetir itens entre dias, histórico, auditoria | **Det.** |
| `update_of_id` | Marcar "atualização" de fato anterior | **Det.** (dedup) / **IA** |
| Detalhe de descartes por motivo e fonte (`discard_reason` por execução) | Seção operacional | **Det.** (hoje só `discarded` agregado; motivos só em log) |
| Corpo completo do NeoFeed | Melhorar assunto principal e fatos | **Enr.** (buscar página; fora do escopo atual) |

### 8.3 Tendências (seção 5 do relatório)
Não precisa de campo novo: é uma **consulta determinística** sobre `impact_level`, `category`, `competitor`, `published_at`
dos últimos 30 dias (regra de evidência da seção 1). A IA só redige o texto a partir de itens já selecionados.

### 8.4 Lacunas relevantes hoje
1. **Sem sujeito vs. contexto** no MATCH (seção 4).
2. **Sem magnitude** de impacto (só direção).
3. **Itens descartados não são persistidos** — o operacional só tem contagem agregada.
4. **NeoFeed sem corpo** (`body_status = none`): a análise dessa fonte dependerá de título + descrição (~470 caracteres).
5. **Volume baixo:** na coleta inicial, 1 de 30 itens casou. A seção de tendências raramente terá dados no início.

---

## 9. Relatório operacional (separado do executivo)

Objetivo: responder *"o Radar está funcionando e posso confiar no relatório de hoje?"*. Vai em arquivo/seção separada;
o executivo mostra só a linha de cobertura e um aviso quando algo estiver degradado.

**Métricas (janela do dia e média dos últimos 7 dias):**

| Bloco | Métrica |
|---|---|
| Fontes | habilitadas · consultadas com sucesso · **indisponíveis** (com `last_error`) · falhas consecutivas |
| Coleta | itens vistos por fonte · novos · duplicados · descartados **por motivo** (`sem_concorrente`, título curto, antigo…) |
| Casamento | itens casados · por concorrente · por fonte |
| Classificação | analisados · pendentes · falhas da IA · por classe A/B/C/D/E · por nível |
| Saída | itens no relatório (por nível) · excedentes fora do relatório |
| Qualidade | `body_status` por fonte (% com corpo) · idade mediana (lag) · última publicação por fonte |

**Alertas operacionais (limiares configuráveis, sugestão inicial):**
- fonte sem sucesso há > 24h, ou ≥ 3 falhas consecutivas;
- fonte sem itens novos por > 3 dias (feed parado);
- coleta total do dia = 0;
- falhas de IA > 20 % ou análises pendentes > 24h;
- **nenhum item casado por 7 dias** (dispara revisão dos aliases — evita silêncio confundido com "dia calmo").

**Regra de honestidade:** se alguma fonte estava indisponível, o relatório executivo exibe
*"Cobertura parcial: <fonte> indisponível"*. Ausência de notícias só vale como "dia calmo" quando as fontes responderam.

---

## 10. Contrato final (resumo)

**A. Estrutura:** Resumo executivo → Alertas prioritários (3–5) → Movimentos por concorrente → Notícias monitoradas → Sinais e tendências; seções vazias omitidas; ≤ 10 itens com texto completo; operacional separado.

**B. Taxonomia (11 + Outros):** Estratégia · M&A · Investimentos e Expansão · Produtos e Inovação · Fábricas e Operações · Resultados financeiros · Preço e Canais · Marca e Marketing · ESG · Liderança · Regulatório · Outros.

**C. Prioridade:** pontuação 0–100 = base do evento + ajustes; Crítico ≥ 85 · Alto 65–84 · Médio 40–64 · Baixo 15–39 · fora < 15; Crítico exige fato concretizado; rumor limita a Alto.

**D. Relevância:** classes E (falso positivo) → D (contexto) → C (irrelevante) → B (baixo valor) → A (relevante); atribuição pelo **assunto principal**, nunca por mera menção.

**E. Item:** CONCORRENTE · PRIORIDADE · CATEGORIA · CONFIANÇA · O que aconteceu (fato) · Por que importa (leitura) · Possível impacto (com base, ou "não foi possível determinar") · Fonte · Data.

**F. Campos:** seção 8 (existentes, novos, origem IA / Det. / Enr.).

**G. Métricas operacionais:** seção 9.

**H. Exemplo:** abaixo.

### Revisão de complexidade (o que foi deliberadamente evitado)
- **Sem** score por dimensão, sem múltiplos eixos de prioridade: uma pontuação, quatro níveis.
- **Sem** gráficos, rankings ou tabelas de KPI no executivo; números só no resumo e no operacional.
- **Sem** recomendações estratégicas geradas; só fato, leitura e impacto com base.
- Taxonomia **reduzida de 19 para 12 valores**; "Mercado" saiu de categoria.
- Tendências por **regra de contagem simples**, não por modelo.
- A IA faz o que só ela faz (sujeito, tipo de evento, extração de valores, texto); **todo o resto é determinístico e auditável**.
- Sugestão de ordem de implementação (quando houver autorização): (1) relatório operacional (só dados existentes);
  (2) sujeito principal + classes A–E; (3) `event_type` + pontuação; (4) textos fato/leitura/impacto; (5) tendências.

---

## Exemplo completo — **FICTÍCIO** (nomes, valores e fatos inventados; não são notícias reais)

> ⚠️ **EXEMPLO ILUSTRATIVO. As notícias abaixo são fictícias e existem apenas para demonstrar o formato.**

# Radar Competitivo — Relatório Diário — 15/01/2027 *(EXEMPLO)*
Janela: 14/01 08:00 → 15/01 08:00 (America/Sao_Paulo) · Cobertura: 4 de 4 fontes consultadas

## 1. Resumo executivo
**6 movimentos relevantes:** 1 Crítico · 1 Alto · 2 Médio · 2 Baixo.
- Kohler anunciou o fechamento da fábrica brasileira; Dexco divulgou fato relevante de investimento em capacidade.
- **Principal sinal:** dois movimentos de capacidade no mesmo dia (um de saída, um de ampliação) — fatos independentes, sem tendência estabelecida.
- ⚠️ **Alerta Crítico hoje:** Kohler (ver abaixo).

## 2. Alertas prioritários

**CONCORRENTE:** Kohler · **PRIORIDADE:** Crítica · **CATEGORIA:** Fábricas e Operações · **CONFIANÇA:** Confirmado
- **O que aconteceu:** A Kohler informou que encerrará a produção em sua fábrica no Brasil até o fim do 1º semestre de 2027, mantendo a operação comercial por importação.
- **Por que importa:** Indica mudança no modelo de atuação da empresa no país, de produção local para importação.
- **Possível impacto para a Lorenzetti:** Pode alterar a dinâmica competitiva no segmento premium (base: sobreposição de portfólio com a linha premium da Lorenzetti).
- **Fonte:** Veículo Exemplo A — https://exemplo.invalid/kohler-fabrica · **Data:** 14/01/2027 17:40

**CONCORRENTE:** Dexco · **PRIORIDADE:** Alta · **CATEGORIA:** Investimentos e Expansão · **CONFIANÇA:** Confirmado
- **O que aconteceu:** A Dexco comunicou ao mercado (fato relevante) investimento de R$ 80 milhões para ampliar a capacidade de produção de metais sanitários, com conclusão prevista para 2028.
- **Por que importa:** Sugere aumento de oferta de metais sanitários nos próximos anos.
- **Possível impacto para a Lorenzetti:** Não foi possível determinar o impacto com a informação disponível (comunicado não informa segmento de preço nem mercados-alvo).
- **Fonte:** CVM/IPE — https://exemplo.invalid/cvm-fato-relevante (confirmado também por Veículo Exemplo B) · **Data:** 14/01/2027 19:05

## 3. Movimentos por concorrente

**Tigre**
- **O que aconteceu:** A Tigre lançou uma linha de tubos com reciclado pós-consumo para obras residenciais, com disponibilidade a partir de março.
- **Por que importa:** Possível reforço de posicionamento em produtos sustentáveis.
- **Possível impacto para a Lorenzetti:** Não foi possível determinar o impacto com a informação disponível.
- **Categoria:** Produtos e Inovação · **Fonte:** Veículo Exemplo C — https://exemplo.invalid/tigre-linha-reciclada · **Data:** 14/01/2027 10:20

**Docol**
- **O que aconteceu:** A Docol anunciou parceria de distribuição com uma rede varejista de materiais de construção para 120 lojas.
- **Por que importa:** Amplia presença da marca em canal de varejo.
- **Possível impacto para a Lorenzetti:** Pode aumentar a disputa por espaço de exposição nesse varejo (base: Lorenzetti também vende em varejo de materiais de construção).
- **Categoria:** Preço e Canais · **Fonte:** Veículo Exemplo A — https://exemplo.invalid/docol-parceria · **Data:** 14/01/2027 12:00

## 4. Notícias monitoradas
- Celite · Participação em feira de arquitetura, sem anúncio de produto · Veículo Exemplo B · 14/01 · https://exemplo.invalid/celite-feira
- Deca · Campanha institucional de verão veiculada em TV aberta · Veículo Exemplo C · 14/01 · https://exemplo.invalid/deca-campanha

## 5. Sinais e tendências
*(seção omitida: não há ≥ 3 itens independentes de mesmo concorrente/categoria nos últimos 30 dias — exemplo)*

*Descartados hoje (não aparecem acima): 1 matéria sobre a Kohler que cita Dexco apenas como comparação foi atribuída somente à Kohler (menção contextual, não conta como item da Dexco); 19 itens sem concorrente.*

---

### Relatório operacional — **FICTÍCIO** (exemplo)

| Fonte | Status | Itens vistos | Novos | Descartados | Casados |
|---|---|---|---|---|---|
| cvm-dexco | ok | 1 | 1 | 0 | 1 |
| braziljournal | ok | 10 | 7 | 5 | 2 |
| neofeed | ok (sem corpo: 0 %) | 10 | 8 | 6 | 2 |
| seudinheiro | ok | 10 | 9 | 8 | 1 |

Totais: 31 vistos · 25 novos · 19 descartados (`sem_concorrente`) · 6 casados (incluindo 1 matéria contextual que citava Dexco, atribuída apenas à Kohler).
Por concorrente: Kohler 1 · Dexco 1 · Tigre 1 · Docol 1 · Celite 1 · Deca 1 · Roca 0.
Classificação: 6 analisados · 0 pendentes · 0 falhas da IA. Erros de coleta: nenhum. Fontes indisponíveis: nenhuma.
Alertas operacionais: nenhum.
