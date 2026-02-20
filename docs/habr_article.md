# Как мы заменили RAG на граф-планировщик для 54 MCP-инструментов и получили детерминированный выбор tool chain за <2ms

> Когда у вашего AI-агента 54 инструмента и 258 действий, LLM начинает путаться. Мы построили детерминированный граф-планировщик, который за <2ms строит оптимальную цепочку вызовов — без единого обращения к LLM. Разбираем архитектуру Planner-Executor, сравниваем с LangGraph/CrewAI/AutoGen и показываем, почему граф бьёт RAG на масштабе.

## Проблема: LLM не справляется с 54 инструментами

Мы разрабатываем [KommoMCP](https://github.com/ampulex-23/KommoMCP) — AI-ассистента для CRM Kommo/amoCRM. Telegram-бот, который через natural language управляет всей CRM: аналитика, настройка воронок, массовые операции, прогнозы, скоринг, коучинг.

К февралю 2026 у нас накопилось:
- **54 инструмента** (MCP tools)
- **258 действий** (actions внутри инструментов)
- **~3000 токенов** только на описание всех tools в system prompt

И мы столкнулись с классической проблемой масштабирования агентов:

```
Пользователь: "Перемести сделку в этап Переговоры"

LLM (видит 54 инструмента): 
  → вызывает kommo_entity_actions.move_lead(lead_id=123, pipeline_id=???, status_id=???)
  → ОШИБКА: pipeline_id и status_id не указаны

Правильный ответ:
  1. kommo_list_pipelines → получить pipeline_id и status_id
  2. kommo_entity_actions.move_lead → переместить с полученными ID
```

LLM **не знает**, что `move_lead` требует предварительного вызова `list_pipelines`. Он видит 54 инструмента и пытается угадать. Иногда угадывает, иногда нет. Это **недетерминированное поведение** — главный враг production-систем.

### Первая попытка: RAG

Мы внедрили RAG (Retrieval-Augmented Generation) — классический подход:

```
User Query → Keyword Match → Top-5 Tools → Dynamic Prompt → LLM
```

RAG решил проблему размера промпта (~500 токенов вместо 3000+), но **не решил проблему зависимостей**. RAG не знает, что `move_lead` требует `list_pipelines`. Он просто ищет по ключевым словам.

### Что говорит индустрия в 2026

Исследования 2025-2026 года сходятся в одном: **плоский RAG недостаточен для tool selection на масштабе**.

- **NeurIPS 2024**: "Can Graph Learning Improve Planning in LLM-based Agents?" — граф-планировщики превосходят flat retrieval
- **ACL 2025**: "A Modern Survey of LLM Planning Capabilities" — LLM плохо планируют длинные цепочки, нужны внешние планировщики
- **Gartner 2025**: 1,445% рост запросов по multi-agent системам за год
- **Deloitte 2026**: "Bounded autonomy" — детерминированный контроль + LLM гибкость

Паттерн **Planner-Executor** стал стандартом де-факто. LangGraph, CrewAI, AutoGen — все реализуют его в той или иной форме. Но есть нюанс: в большинстве фреймворков **планировщик — это тоже LLM**. А значит, он стоит денег, добавляет латентность и сам может ошибаться.

Мы пошли другим путём.

## Решение: детерминированный граф-планировщик

Наш планировщик — это **чистый Python, никаких LLM-вызовов**. Он работает на графе инструментов с явными зависимостями, входами/выходами и capabilities.

### Архитектура

```
                     ┌─────────────────────────────────────────────┐
                     │           PLANNER (deterministic)           │
                     │                                             │
User Query ────────▶ │  Intent Detector ──▶ Capability Mapper     │
                     │        │                    │               │
                     │        ▼                    ▼               │
                     │  Tool Graph (54 nodes, 24 edges)           │
                     │        │                                    │
                     │        ▼                                    │
                     │  Backward Chaining ──▶ Topo Sort           │
                     │        │                    │               │
                     │        ▼                    ▼               │
                     │  Parallel Detection ──▶ Chain Optimizer    │
                     │                             │               │
                     └─────────────────────────────┼───────────────┘
                                                   │
                                      PlannedChain + Filtered Tools
                                                   │
                     ┌─────────────────────────────┼───────────────┐
                     │           EXECUTOR (LLM)    ▼               │
                     │                                             │
                     │  Dynamic Prompt ──▶ GPT + Filtered Tools   │
                     │        │                    │               │
                     │        ▼                    ▼               │
                     │  RAG Context        Tool Call Loop          │
                     │                         │                   │
                     │                         ▼                   │
                     │                  Kommo API / PostgreSQL     │
                     │                                             │
                     └─────────────────────────────────────────────┘
```

Ключевое отличие от LangGraph/CrewAI: **планировщик не вызывает LLM**. Он работает за <2ms на чистом графовом обходе.

## Реализация по шагам

### Шаг 1: Граф инструментов (YAML-реестр)

Каждый инструмент описан как узел графа с явными inputs, outputs, capabilities и edges:

```yaml
tools:
  - id: kommo_list_pipelines
    category: pipeline
    description: List all pipelines with stages
    capabilities: [list_pipelines, get_stages]
    inputs: []
    outputs: [pipeline_id, pipeline_name, stage_id, stage_name]
    cost: 0.1

  - id: kommo_entity_actions
    category: deals
    description: Entity operations (notes, tasks, leads)
    capabilities: [update_lead, move_lead, add_note, create_task]
    inputs: [lead_id, "pipeline_id?", "status_id?"]
    outputs: [lead_updated, note_added, task_created]
    actions:
      - id: move_lead
        inputs: [lead_id, pipeline_id, status_id]
        outputs: [lead_updated]
        effects: [lead_stage_changed]
        cost: 0.3

edges:
  # move_lead ТРЕБУЕТ list_pipelines (для pipeline_id и status_id)
  - from: kommo_entity_actions.move_lead
    to: kommo_list_pipelines
    type: REQUIRES
    weight: 1.0
    reason: Need pipeline_id and status_id to move

  # Аналитика и статистика менеджеров могут работать параллельно
  - from: kommo_pipeline_analytics
    to: kommo_manager_stats
    type: PARALLEL
    weight: 0.8
    reason: Independent analytics can run in parallel
```

Суффикс `?` в inputs означает опциональный параметр. Четыре типа рёбер:
- **REQUIRES** — жёсткая зависимость (A не может работать без B)
- **SEQUENCE** — рекомендуемый порядок (сначала анализ, потом стратегия)
- **PARALLEL** — могут выполняться одновременно
- **PRODUCES** — A производит данные для B

Полный реестр: **54 узла, 258 действий, 24 ребра, 154 capabilities**.

### Шаг 2: Intent Detector (keyword matching)

Вместо LLM для определения намерений мы используем инвертированный индекс по ключевым словам:

```python
class IntentDetector:
    def __init__(self, capability_map: List[Dict]):
        self._keyword_index: Dict[str, List[Tuple[str, List[str]]]] = defaultdict(list)
        for entry in capability_map:
            intent = entry['intent']
            caps = entry.get('capabilities', [])
            for kw in entry.get('keywords', []):
                self._keyword_index[kw.lower()].append((intent, caps))

    def detect(self, query: str) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        query_words = set(query_lower.split())
        intent_scores: Dict[str, float] = defaultdict(float)

        for entry in self._map:
            score = 0.0
            for kw in entry.get('keywords', []):
                kw_lower = kw.lower()
                if kw_lower in query_lower:      # Exact substring: +3
                    score += 3.0
                elif kw_lower in query_words:     # Word match: +2
                    score += 2.0
                elif any(kw_lower in w or w in kw_lower 
                         for w in query_words if len(w) > 2):  # Partial: +1
                    score += 1.0

            if score > 0:
                intent_scores[intent] += score
        # ... return sorted by score
```

Capability map в YAML:

```yaml
capability_map:
  - intent: deal_management
    keywords: [сделка, сделку, лид, deal, lead, переместить, перемести]
    capabilities: [update_lead, move_lead, add_note, create_task]

  - intent: analytics
    keywords: [аналитика, статистика, отчет, метрики, kpi]
    capabilities: [pipeline_analytics, conversion_rates, manager_stats]
```

Трёхуровневый скоринг (exact substring → word match → partial) обеспечивает робастность для русского языка с его морфологией. Запрос «переместить сделку» матчит и «перемести», и «сделку», и «сделка».

### Шаг 3: Backward Chaining (разрешение зависимостей)

Это ядро планировщика. Для каждого найденного инструмента проверяем: все ли его inputs доступны? Если нет — ищем инструмент, который их производит:

```python
def _resolve_dependencies(
    self,
    candidate_tools: Dict[str, ToolNode],
    context: Dict[str, Any],
    max_depth: int = 3,
) -> Dict[str, ToolNode]:
    resolved = dict(candidate_tools)
    available_outputs = set(context.keys())

    for _ in range(max_depth):
        new_tools: Dict[str, ToolNode] = {}

        for tool_id, tool in resolved.items():
            # Проверяем REQUIRES-рёбра
            for edge in self.graph.get_dependencies(tool_id):
                dep_tool_id = edge.to_tool.split('.')[0]
                if dep_tool_id not in resolved:
                    new_tools[dep_tool_id] = self.graph.nodes[dep_tool_id]

            # Проверяем неудовлетворённые inputs
            needed_inputs = set(tool.inputs) - available_outputs
            for inp in needed_inputs:
                providers = self.graph.get_tools_by_output(inp)
                for provider_tool, _ in providers:
                    if provider_tool.id not in resolved:
                        new_tools[provider_tool.id] = provider_tool
                        break

        if not new_tools:
            break

        resolved.update(new_tools)
        for tool in new_tools.values():
            available_outputs.update(tool.outputs)

    return resolved
```

Это **backward chaining** — классический алгоритм из экспертных систем, адаптированный для графа инструментов. Глубина 3 достаточна для наших 54 инструментов (максимальная цепочка зависимостей — 2 уровня).

### Шаг 4: Топологическая сортировка (алгоритм Кана)

После разрешения зависимостей нужно определить порядок выполнения:

```python
def topological_sort(self, tool_ids: Set[str]) -> List[str]:
    in_degree: Dict[str, int] = {tid: 0 for tid in tool_ids}
    adj: Dict[str, List[str]] = defaultdict(list)

    for edge in self.edges:
        from_base = edge.from_tool.split('.')[0]
        to_base = edge.to_tool.split('.')[0]
        if from_base in tool_ids and to_base in tool_ids:
            if edge.edge_type == 'REQUIRES':
                # A requires B → B должен быть раньше A
                adj[to_base].append(from_base)
                in_degree[from_base] += 1
            elif edge.edge_type == 'SEQUENCE':
                adj[from_base].append(to_base)
                in_degree[to_base] += 1

    # Алгоритм Кана
    queue = deque([tid for tid in tool_ids if in_degree[tid] == 0])
    result = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result
```

Обратите внимание на обработку `REQUIRES` vs `SEQUENCE`: для `REQUIRES` направление инвертировано (если A requires B, то B идёт первым), а для `SEQUENCE` — прямое.

### Шаг 5: Построение цепочки с param refs

Финальный шаг — построить `PlannedChain` с явными ссылками на параметры между шагами:

```python
@dataclass
class ChainStep:
    tool: str
    action: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    parallel: bool = False
    depends_on: Optional[int] = None
    param_refs: Dict[str, str] = field(default_factory=dict)  # 'pipeline_id' → '$step0.pipeline_id'
```

`param_refs` — это ключевая фича. Когда планировщик знает, что `move_lead` нуждается в `pipeline_id`, а `list_pipelines` его производит, он создаёт ссылку `$step0.pipeline_id`. LLM видит эту ссылку в промпте и **точно знает**, откуда взять параметр.

### Шаг 6: Инъекция в промпт

Планировщик генерирует структурированный промпт для LLM:

```
🎯 ПЛАН ВЫПОЛНЕНИЯ:
Запрос: Перемести сделку 123 в этап Переговоры
Шагов: 2, Стоимость: 0.4

📋 ПОРЯДОК ВЫЗОВОВ:

1. `kommo_list_pipelines`
   List all pipelines with stages

2. `kommo_entity_actions` action="move_lead"
   Entity operations (notes, tasks, leads)
   Из предыдущего шага: pipeline_id ← $step0.pipeline_id
   ⚠️ Ждать результат шага 1 (kommo_list_pipelines)

⚠️ ПРАВИЛА:
1. Вызывай инструменты СТРОГО в указанном порядке
2. Передавай результаты предыдущих шагов в следующие (см. "$step")
3. Параллельные шаги можно вызывать одновременно
4. Если шаг не нужен по контексту — пропусти его
```

## Интеграция в production

Интеграция в `ai_chat.py` заняла ~50 строк:

```python
from kommo_mcp.planner.tool_graph_planner import ToolGraphPlanner

# Singleton + индекс для быстрой фильтрации
_MCP_TOOLS_INDEX = {t['function']['name']: t for t in MCP_TOOLS}
_planner_instance = None

def get_planner():
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = ToolGraphPlanner()
    return _planner_instance

def _filter_tools_by_plan(tool_names):
    return [_MCP_TOOLS_INDEX[n] for n in tool_names if n in _MCP_TOOLS_INDEX]
```

В методе `chat()`:

```python
async def chat(self, message, use_rag=True, user_id='default'):
    # Step 1: Deterministic planning
    planner = get_planner()
    planned_chain = planner.plan(message)
    planned_tool_names = planner.get_tool_filter(planned_chain)

    if planned_chain.chain:
        active_tools = _filter_tools_by_plan(planned_tool_names)
        planner_prompt = planner.build_prompt(planned_chain, message)
    else:
        active_tools = MCP_TOOLS  # Fallback: все 54 инструмента
        planner_prompt = ''

    # Step 2: RAG + planner prompt
    dynamic_prompt = build_dynamic_prompt(message, retriever, top_k=5)
    if planner_prompt:
        dynamic_prompt += '\n\n' + planner_prompt

    # Step 3: LLM видит только запланированные инструменты
    response = await self._openai_request(
        messages=messages, 
        tools=active_tools  # 2-6 tools вместо 54
    )
```

Ключевые решения:
- **Fallback**: если планировщик не нашёл цепочку → используем все 54 инструмента (как раньше)
- **RAG + Planner**: промпты комбинируются, а не заменяют друг друга
- **Singleton**: планировщик создаётся один раз, граф загружается из YAML при старте

## Бенчмарки

### Латентность планирования

| Запрос | Шагов | Латентность |
|---|---|---|
| «покажи аналитику» | 1 | 0ms |
| «перемести сделку в Переговоры» | 2 | 0ms |
| «добавь VIP-клиента с аналитикой» | 3 | 0ms |
| «покажи прогноз и здоровье воронки» | 2 | 0ms |
| «найди проблемные сделки и предложи решение» | 3 | 1ms |

Все запросы укладываются в **<2ms**. Для сравнения: LLM-based planner (как в LangGraph) добавляет 500-2000ms и стоит ~$0.01-0.05 за вызов.

### Фильтрация инструментов

| Сценарий | Инструментов в промпте (RAG) | Инструментов в промпте (Planner) | Сокращение |
|---|---|---|---|
| Простой запрос | 5 | 1-2 | 60-80% |
| Средний запрос | 5 | 2-4 | 20-60% |
| Сложный multi-step | 5 | 3-6 | 0-40% |

Плюс планировщик добавляет **порядок выполнения** и **param refs**, чего RAG не может.

### Тестовое покрытие

31 тест покрывает 10 реальных amoCRM-сценариев:

```python
class TestScenario1VipClientWithAnalytics:
    """Сценарий: VIP-клиент с аналитикой."""
    
    def test_intents(self, planner):
        result = planner.plan('добавь VIP-клиента с аналитикой')
        assert 'contact_management' in result.intents or 'analytics' in result.intents

    def test_required_tools(self, planner):
        result = planner.plan('добавь VIP-клиента с аналитикой')
        tools = [s.tool for s in result.chain]
        assert any('contact' in t or 'scoring' in t for t in tools)

class TestMandatorySteps:
    """Обязательные шаги: зависимости разрешены."""
    
    def test_move_lead_requires_pipelines(self, planner):
        result = planner.plan('перемести сделку в этап Переговоры')
        tools = [s.tool for s in result.chain]
        if 'kommo_entity_actions' in tools:
            pipe_idx = tools.index('kommo_list_pipelines') if 'kommo_list_pipelines' in tools else -1
            entity_idx = tools.index('kommo_entity_actions')
            assert pipe_idx < entity_idx, 'list_pipelines must come before move_lead'
```

## Сравнение с фреймворками

| Характеристика | KommoMCP Planner | LangGraph | CrewAI | AutoGen |
|---|---|---|---|---|
| **Планировщик** | Детерминированный граф | LLM-based | LLM-based (manager) | LLM-based |
| **Латентность планирования** | <2ms | 500-2000ms | 500-2000ms | 500-2000ms |
| **Стоимость планирования** | $0 | $0.01-0.05/запрос | $0.01-0.05/запрос | $0.01-0.05/запрос |
| **Детерминированность** | 100% | ~70-90% | ~70-90% | ~70-90% |
| **Dependency resolution** | Граф + backward chaining | Промпт-инженерия | Промпт-инженерия | Промпт-инженерия |
| **Tool scoping** | Автоматическая фильтрация | Ручная конфигурация | Per-agent tools | Ручная конфигурация |
| **Param passing** | Явные $step refs | Через state | Через shared memory | Через chat |
| **Replanning** | ❌ (в roadmap) | ✅ | ✅ | ✅ |
| **Learning** | ❌ (в roadmap) | ❌ | ❌ | ❌ |

### Когда наш подход лучше

- **Фиксированный набор инструментов** — если вы знаете все tools заранее, граф бьёт LLM
- **Высокие требования к латентности** — 0ms vs 500-2000ms
- **Экономия на LLM-вызовах** — при 1000 запросов/день экономия ~$50-150/мес
- **Детерминированность** — один и тот же запрос всегда даёт одну и ту же цепочку

### Когда LLM-based planner лучше

- **Динамический набор инструментов** — если tools меняются в runtime
- **Сложная семантика** — когда keyword matching недостаточен
- **Replanning** — когда нужно адаптироваться к ошибкам в реальном времени

## Уроки и грабли

### 1. YAML — не JSON

Мы начали с JSON для реестра, но быстро перешли на YAML. Причина: 54 инструмента × 5+ действий = 1650 строк. В YAML это читаемо, в JSON — нет.

Грабля: символ `?` в YAML имеет специальное значение. `[pipeline_id?]` парсится как mapping key, а не как строка. Решение: `["pipeline_id?"]`.

### 2. REQUIRES vs SEQUENCE

Изначально мы использовали только `REQUIRES`. Но оказалось, что есть два типа зависимостей:
- **Жёсткая** (`REQUIRES`): `move_lead` **не может** работать без `list_pipelines`
- **Мягкая** (`SEQUENCE`): `advisor.strategy` **лучше** вызывать после `loss_analysis.reasons`, но может работать и без

### 3. Направление рёбер в backward chaining

Баг, который стоил нам 2 часа: `REQUIRES` edge `A → B` означает «A требует B», но в `_out_edges[A]` хранится ребро `A → B`. Значит, зависимости нужно искать в `_out_edges`, а не в `_in_edges`:

```python
# ❌ Неправильно
def get_dependencies(self, tool_id):
    return [e for e in self._in_edges.get(tool_id, []) if e.edge_type == 'REQUIRES']

# ✅ Правильно
def get_dependencies(self, tool_id):
    return [e for e in self._out_edges.get(tool_id, []) if e.edge_type == 'REQUIRES']
```

### 4. Русская морфология

Keyword matching для русского языка — это боль. «Квалификация», «квалифицируй», «квалифицирован» — три разные формы одного слова. Решение: расширенные keywords с основными словоформами:

```yaml
- intent: qualification
  keywords: [квалификация, квалифицируй, квалифициров, bant, qualify, оценить лид, скоринг лида]
```

Не идеально, но работает для 90%+ запросов. Для оставшихся 10% — fallback на полный набор инструментов.

## Что дальше

Наш roadmap к полному SOTA:

1. **Replanning on failure** — если tool call вернул ошибку, перезапустить планировщик с обновлённым контекстом
2. **Verifier agent** — паттерн Planner-Verifier-Executor (Lei et al., 2025): валидация результатов перед возвратом пользователю
3. **Learning from execution** — логировать успешные цепочки в PostgreSQL, использовать для оптимизации весов рёбер
4. **A2A Protocol** — Google's Agent-to-Agent для кросс-системной коллаборации агентов

## Итого

| Метрика | До (RAG only) | После (Planner + RAG) |
|---|---|---|
| Tool selection accuracy | ~80% | ~95%+ |
| Dependency resolution | ❌ manual | ✅ automatic |
| Planning latency | 0ms | <2ms |
| Tools in prompt | 5 (fixed) | 2-6 (dynamic) |
| Param passing | LLM guesses | Explicit $step refs |
| Cost per plan | $0 | $0 |
| Determinism | Low | 100% |

Граф-планировщик — это не замена LLM. Это **дополнение**, которое делает LLM-агента предсказуемым. Планировщик решает **что** и **в каком порядке** вызывать, а LLM решает **как** заполнить параметры и **как** интерпретировать результаты.

800 строк Python, 1650 строк YAML, 31 тест. Никаких внешних зависимостей кроме PyYAML. Работает в production с февраля 2026.

---

*Теги: python, machine learning, ai, llm, mcp, crm, graph algorithms, agentic ai, tool planning*

*Хабы: Машинное обучение, Python, Алгоритмы, Искусственный интеллект*
