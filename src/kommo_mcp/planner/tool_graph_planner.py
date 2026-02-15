"""
Tool Graph Planner for MCP Agent.

Deterministic planner that builds optimal tool chains from a graph of 
CRM tools, their capabilities, inputs/outputs, and edges.

Architecture:
  User Query → LLM (capability parse) → RAG (top-20 tools)
            → Graph Planner (this module) → Optimal Chain
            → Dynamic Tool Prompt → LLM Executor

Uses in-memory graph (loaded from YAML registry) with optional
Postgres persistence for logging and learning.
"""

import logging
import time
import yaml
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# Data classes
# ============================================================

@dataclass
class ToolAction:
    """Single action within a tool."""
    tool_id: str
    action_id: str
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    effects: List[str] = field(default_factory=list)
    cost: float = 0.2


@dataclass
class ToolNode:
    """A tool in the graph."""
    id: str
    name: str
    category: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    preconditions: List[str] = field(default_factory=list)
    effects: List[str] = field(default_factory=list)
    actions: Dict[str, ToolAction] = field(default_factory=dict)
    cost: float = 0.2


@dataclass
class Edge:
    """Directed edge between tools."""
    from_tool: str
    to_tool: str
    edge_type: str  # REQUIRES, PRODUCES, SEQUENCE, PARALLEL
    weight: float = 0.5
    reason: str = ''


@dataclass
class ChainStep:
    """A single step in the execution chain."""
    tool: str
    action: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    parallel: bool = False
    depends_on: Optional[int] = None  # index of step this depends on
    param_refs: Dict[str, str] = field(default_factory=dict)  # param -> '$prev.field'


@dataclass
class PlannedChain:
    """Result of the planner."""
    chain: List[ChainStep]
    cost: float
    constraints_ok: bool
    intents: List[str] = field(default_factory=list)
    explanation: str = ''
    latency_ms: int = 0


# ============================================================
# Intent Detector
# ============================================================

class IntentDetector:
    """Detects user intents from query using keyword matching."""

    def __init__(self, capability_map: List[Dict]):
        self._map = capability_map
        # Build inverted index: keyword → (intent, capabilities)
        self._keyword_index: Dict[str, List[Tuple[str, List[str]]]] = defaultdict(list)
        for entry in self._map:
            intent = entry['intent']
            caps = entry.get('capabilities', [])
            for kw in entry.get('keywords', []):
                self._keyword_index[kw.lower()].append((intent, caps))

    def detect(self, query: str) -> List[Dict[str, Any]]:
        """Detect intents from user query.
        
        Returns list of {intent, capabilities, score} sorted by score desc.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())
        intent_scores: Dict[str, float] = defaultdict(float)
        intent_caps: Dict[str, Set[str]] = defaultdict(set)

        for entry in self._map:
            intent = entry['intent']
            caps = entry.get('capabilities', [])
            score = 0.0

            for kw in entry.get('keywords', []):
                kw_lower = kw.lower()
                # Exact substring match
                if kw_lower in query_lower:
                    score += 3.0
                # Word-level match
                elif kw_lower in query_words:
                    score += 2.0
                # Partial match
                elif any(kw_lower in w or w in kw_lower for w in query_words if len(w) > 2):
                    score += 1.0

            if score > 0:
                intent_scores[intent] += score
                intent_caps[intent].update(caps)

        results = []
        for intent, score in sorted(intent_scores.items(), key=lambda x: -x[1]):
            results.append({
                'intent': intent,
                'capabilities': list(intent_caps[intent]),
                'score': score,
            })

        return results


# ============================================================
# Tool Graph
# ============================================================

class ToolGraph:
    """In-memory directed graph of tools and their relationships."""

    def __init__(self):
        self.nodes: Dict[str, ToolNode] = {}
        self.edges: List[Edge] = []
        # Adjacency lists
        self._out_edges: Dict[str, List[Edge]] = defaultdict(list)
        self._in_edges: Dict[str, List[Edge]] = defaultdict(list)
        # Capability index: capability → [tool_id]
        self._cap_index: Dict[str, List[str]] = defaultdict(list)
        # Output index: output_name → [(tool_id, action_id)]
        self._output_index: Dict[str, List[Tuple[str, Optional[str]]]] = defaultdict(list)

    def add_node(self, node: ToolNode):
        """Add a tool node to the graph."""
        self.nodes[node.id] = node
        for cap in node.capabilities:
            self._cap_index[cap].append(node.id)
        # Index tool-level outputs
        for out in node.outputs:
            self._output_index[out].append((node.id, None))
        # Index action-level outputs
        for action in node.actions.values():
            for out in action.outputs:
                self._output_index[out].append((node.id, action.action_id))

    def add_edge(self, edge: Edge):
        """Add a directed edge."""
        self.edges.append(edge)
        from_base = edge.from_tool.split('.')[0]
        to_base = edge.to_tool.split('.')[0]
        self._out_edges[from_base].append(edge)
        self._in_edges[to_base].append(edge)

    def get_tools_by_capability(self, capability: str) -> List[ToolNode]:
        """Find tools that have a given capability."""
        tool_ids = self._cap_index.get(capability, [])
        return [self.nodes[tid] for tid in tool_ids if tid in self.nodes]

    def get_tools_by_output(self, output_name: str) -> List[Tuple[ToolNode, Optional[str]]]:
        """Find tools that produce a given output. Returns (tool, action_id)."""
        results = []
        for tool_id, action_id in self._output_index.get(output_name, []):
            if tool_id in self.nodes:
                results.append((self.nodes[tool_id], action_id))
        return results

    def get_dependencies(self, tool_id: str) -> List[Edge]:
        """Get REQUIRES edges from this tool (what it depends on)."""
        return [e for e in self._out_edges.get(tool_id, []) if e.edge_type == 'REQUIRES']

    def get_sequences(self, tool_id: str) -> List[Edge]:
        """Get SEQUENCE edges from this tool."""
        return [e for e in self._out_edges.get(tool_id, []) if e.edge_type == 'SEQUENCE']

    def get_parallel(self, tool_id: str) -> List[Edge]:
        """Get PARALLEL edges from this tool."""
        return [e for e in self._out_edges.get(tool_id, []) if e.edge_type == 'PARALLEL']

    def topological_sort(self, tool_ids: Set[str]) -> List[str]:
        """Topological sort of a subset of tools based on REQUIRES/SEQUENCE edges."""
        # Build sub-graph
        in_degree: Dict[str, int] = {tid: 0 for tid in tool_ids}
        adj: Dict[str, List[str]] = defaultdict(list)

        for edge in self.edges:
            from_base = edge.from_tool.split('.')[0]
            to_base = edge.to_tool.split('.')[0]
            if from_base in tool_ids and to_base in tool_ids:
                if edge.edge_type in ('REQUIRES', 'SEQUENCE'):
                    # from depends on to (for REQUIRES) or from → to (for SEQUENCE)
                    if edge.edge_type == 'REQUIRES':
                        adj[to_base].append(from_base)
                        in_degree[from_base] = in_degree.get(from_base, 0) + 1
                    else:  # SEQUENCE
                        adj[from_base].append(to_base)
                        in_degree[to_base] = in_degree.get(to_base, 0) + 1

        # Kahn's algorithm
        queue = deque([tid for tid in tool_ids if in_degree.get(tid, 0) == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If not all nodes are in result, there's a cycle — just append remaining
        remaining = tool_ids - set(result)
        result.extend(sorted(remaining))

        return result


# ============================================================
# Registry Loader
# ============================================================

def load_registry(registry_path: Optional[str] = None) -> Tuple[ToolGraph, IntentDetector]:
    """Load tool registry from YAML and build graph + intent detector."""
    if registry_path is None:
        registry_path = str(Path(__file__).parent / 'tool_registry.yaml')

    with open(registry_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    graph = ToolGraph()

    # Load tools
    for tool_data in data.get('tools', []):
        actions = {}
        tool_outputs = []
        tool_inputs = []

        # Parse tool-level inputs/outputs
        for inp in tool_data.get('inputs', []):
            clean = inp.rstrip('?')
            tool_inputs.append(clean)
        for out in tool_data.get('outputs', []):
            tool_outputs.append(out)

        # Parse actions
        for action_data in tool_data.get('actions', []):
            if isinstance(action_data, dict) and 'id' in action_data:
                action_inputs = [i.rstrip('?') for i in action_data.get('inputs', [])]
                action_outputs = action_data.get('outputs', [])
                action_effects = action_data.get('effects', [])
                action = ToolAction(
                    tool_id=tool_data['id'],
                    action_id=action_data['id'],
                    inputs=action_inputs,
                    outputs=action_outputs,
                    effects=action_effects,
                    cost=action_data.get('cost', tool_data.get('cost', 0.2)),
                )
                actions[action_data['id']] = action
                tool_outputs.extend(action_outputs)

        node = ToolNode(
            id=tool_data['id'],
            name=tool_data.get('name', tool_data['id']),
            category=tool_data.get('category', ''),
            description=tool_data.get('description', ''),
            capabilities=tool_data.get('capabilities', []),
            inputs=tool_inputs,
            outputs=list(set(tool_outputs)),
            preconditions=tool_data.get('preconditions', []),
            effects=tool_data.get('effects', []),
            actions=actions,
            cost=tool_data.get('cost', 0.2),
        )
        graph.add_node(node)

    # Load edges
    for edge_data in data.get('edges', []):
        edge = Edge(
            from_tool=edge_data['from'],
            to_tool=edge_data['to'],
            edge_type=edge_data['type'],
            weight=edge_data.get('weight', 0.5),
            reason=edge_data.get('reason', ''),
        )
        graph.add_edge(edge)

    # Load capability map
    cap_map = data.get('capability_map', [])
    detector = IntentDetector(cap_map)

    logger.info(
        f'Loaded registry: {len(graph.nodes)} tools, '
        f'{len(graph.edges)} edges, {len(cap_map)} intent mappings'
    )

    return graph, detector


# ============================================================
# Chain Planner (core logic)
# ============================================================

class ChainPlanner:
    """Deterministic planner that builds optimal tool chains.
    
    Algorithm:
    1. Detect intents from user query
    2. Map intents → required capabilities
    3. Find tools that satisfy capabilities
    4. Resolve dependencies (backward chaining)
    5. Topological sort for execution order
    6. Identify parallelizable steps
    7. Optimize: remove redundant steps, minimize cost
    """

    def __init__(self, graph: ToolGraph, detector: IntentDetector):
        self.graph = graph
        self.detector = detector

    def plan(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        max_chain_length: int = 8,
    ) -> PlannedChain:
        """Build optimal chain for user query.
        
        Args:
            query: User's natural language request
            context: Current state (available params, active pipeline, etc.)
            max_chain_length: Maximum steps in chain
            
        Returns:
            PlannedChain with ordered steps
        """
        start_time = time.time()
        context = context or {}

        # Step 1: Detect intents
        intents = self.detector.detect(query)
        if not intents:
            return PlannedChain(
                chain=[], cost=0, constraints_ok=True,
                intents=[], explanation='No matching intents detected',
                latency_ms=int((time.time() - start_time) * 1000),
            )

        logger.debug(f'Detected intents: {[(i["intent"], i["score"]) for i in intents[:5]]}')

        # Step 2: Collect required capabilities (from top intents)
        required_caps: List[str] = []
        selected_intents: List[str] = []
        for intent_info in intents[:3]:  # Top 3 intents
            if intent_info['score'] >= 1.0:
                required_caps.extend(intent_info['capabilities'])
                selected_intents.append(intent_info['intent'])

        required_caps = list(dict.fromkeys(required_caps))  # dedupe preserving order

        # Step 3: Find tools that satisfy capabilities
        candidate_tools: Dict[str, ToolNode] = {}
        tool_actions_map: Dict[str, Optional[str]] = {}  # tool_id → best action

        for cap in required_caps:
            tools = self.graph.get_tools_by_capability(cap)
            for tool in tools:
                if tool.id not in candidate_tools:
                    candidate_tools[tool.id] = tool
                    # Find best action for this capability
                    best_action = self._find_best_action(tool, cap, query)
                    if best_action:
                        tool_actions_map[tool.id] = best_action

        if not candidate_tools:
            return PlannedChain(
                chain=[], cost=0, constraints_ok=True,
                intents=selected_intents,
                explanation='No tools found for detected capabilities',
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Step 4: Resolve dependencies (backward chaining)
        resolved_tools = self._resolve_dependencies(
            candidate_tools, context, max_depth=3
        )

        # Step 5: Topological sort
        all_tool_ids = set(resolved_tools.keys())
        sorted_ids = self.graph.topological_sort(all_tool_ids)

        # Step 6: Build chain with parallel detection
        chain = self._build_chain(
            sorted_ids, resolved_tools, tool_actions_map, context
        )

        # Step 7: Optimize
        chain = self._optimize_chain(chain, max_chain_length)

        # Calculate total cost
        total_cost = sum(
            self.graph.nodes[step.tool].cost
            for step in chain
            if step.tool in self.graph.nodes
        )

        latency_ms = int((time.time() - start_time) * 1000)

        return PlannedChain(
            chain=chain,
            cost=round(total_cost, 2),
            constraints_ok=len(chain) <= max_chain_length,
            intents=selected_intents,
            explanation=self._explain_chain(chain, selected_intents),
            latency_ms=latency_ms,
        )

    def _find_best_action(
        self, tool: ToolNode, capability: str, query: str
    ) -> Optional[str]:
        """Find the best action for a tool given a capability and query."""
        if not tool.actions:
            return None

        query_lower = query.lower()
        best_action = None
        best_score = -1

        for action_id, action in tool.actions.items():
            score = 0
            # Action ID in query
            if action_id in query_lower:
                score += 5
            # Action ID words overlap with query
            action_words = set(action_id.replace('_', ' ').split())
            query_words = set(query_lower.split())
            overlap = len(action_words & query_words)
            score += overlap * 2
            # Capability match via outputs
            cap_words = set(capability.replace('_', ' ').split())
            action_out_words = set()
            for out in action.outputs:
                action_out_words.update(out.replace('_', ' ').split())
            cap_overlap = len(cap_words & action_out_words)
            score += cap_overlap

            if score > best_score:
                best_score = score
                best_action = action_id

        return best_action

    def _resolve_dependencies(
        self,
        candidate_tools: Dict[str, ToolNode],
        context: Dict[str, Any],
        max_depth: int = 3,
    ) -> Dict[str, ToolNode]:
        """Backward chaining: resolve tool dependencies.
        
        For each candidate tool, check if its required inputs are available
        in context. If not, find tools that produce those inputs and add them.
        """
        resolved = dict(candidate_tools)
        available_outputs = set(context.keys())

        for _ in range(max_depth):
            new_tools: Dict[str, ToolNode] = {}

            for tool_id, tool in resolved.items():
                # Check REQUIRES edges
                for edge in self.graph.get_dependencies(tool_id):
                    dep_tool_id = edge.to_tool.split('.')[0]
                    if dep_tool_id not in resolved and dep_tool_id in self.graph.nodes:
                        new_tools[dep_tool_id] = self.graph.nodes[dep_tool_id]

                # Check if inputs are satisfied
                needed_inputs = set(tool.inputs) - available_outputs
                for inp in needed_inputs:
                    providers = self.graph.get_tools_by_output(inp)
                    for provider_tool, provider_action in providers:
                        if provider_tool.id not in resolved:
                            new_tools[provider_tool.id] = provider_tool
                            break

            if not new_tools:
                break

            resolved.update(new_tools)
            # Update available outputs
            for tool in new_tools.values():
                available_outputs.update(tool.outputs)

        return resolved

    def _build_chain(
        self,
        sorted_ids: List[str],
        tools: Dict[str, ToolNode],
        actions_map: Dict[str, Optional[str]],
        context: Dict[str, Any],
    ) -> List[ChainStep]:
        """Build execution chain with parallel step detection."""
        chain: List[ChainStep] = []
        produced_outputs: Set[str] = set(context.keys())
        step_index: Dict[str, int] = {}  # tool_id → step index

        for tool_id in sorted_ids:
            if tool_id not in tools:
                continue

            tool = tools[tool_id]
            action_id = actions_map.get(tool_id)

            # Determine if this can run in parallel with previous step
            parallel = False
            depends_on = None
            if chain:
                parallel_edges = self.graph.get_parallel(tool_id)
                parallel_peers = {e.to_tool.split('.')[0] for e in parallel_edges}
                parallel_peers.update(
                    e.from_tool.split('.')[0]
                    for e in self.graph.edges
                    if e.edge_type == 'PARALLEL'
                    and e.to_tool.split('.')[0] == tool_id
                )

                # Check if previous step is a parallel peer
                prev_tool = chain[-1].tool
                if prev_tool in parallel_peers:
                    parallel = True

                # Find dependency step
                for edge in self.graph._in_edges.get(tool_id, []):
                    dep_id = edge.from_tool.split('.')[0]
                    if edge.edge_type in ('REQUIRES', 'SEQUENCE') and dep_id in step_index:
                        depends_on = step_index[dep_id]
                        break

            # Build param refs (e.g., pipeline_id from previous step)
            param_refs: Dict[str, str] = {}
            if action_id and action_id in tool.actions:
                action = tool.actions[action_id]
                for inp in action.inputs:
                    if inp not in context and inp in produced_outputs:
                        # Find which step produces this
                        for prev_id, prev_idx in step_index.items():
                            prev_tool = tools.get(prev_id)
                            if prev_tool and inp in prev_tool.outputs:
                                param_refs[inp] = f'$step{prev_idx}.{inp}'
                                break

            step = ChainStep(
                tool=tool_id,
                action=action_id,
                params={k: v for k, v in context.items() if k in tool.inputs},
                parallel=parallel,
                depends_on=depends_on,
                param_refs=param_refs,
            )

            step_index[tool_id] = len(chain)
            chain.append(step)
            produced_outputs.update(tool.outputs)

        return chain

    def _optimize_chain(
        self, chain: List[ChainStep], max_length: int
    ) -> List[ChainStep]:
        """Optimize chain: remove redundant steps, enforce max length."""
        if len(chain) <= max_length:
            return chain

        # Score each step by importance
        scored = []
        for i, step in enumerate(chain):
            score = 1.0
            # Steps with dependencies from others are more important
            refs_to_me = sum(1 for s in chain if s.depends_on == i)
            score += refs_to_me * 2
            # Steps with param_refs are dependent — keep them
            if step.param_refs:
                score += 1
            # Non-parallel steps are usually more critical
            if not step.parallel:
                score += 0.5
            scored.append((score, i, step))

        # Keep top max_length by score
        scored.sort(key=lambda x: -x[0])
        kept_indices = sorted([idx for _, idx, _ in scored[:max_length]])
        return [chain[i] for i in kept_indices]

    def _explain_chain(
        self, chain: List[ChainStep], intents: List[str]
    ) -> str:
        """Generate human-readable explanation of the chain."""
        if not chain:
            return 'Empty chain — no tools needed.'

        parts = [f'Intents: {", ".join(intents)}']
        for i, step in enumerate(chain):
            action_str = f'.{step.action}' if step.action else ''
            parallel_str = ' [PARALLEL]' if step.parallel else ''
            dep_str = f' (after step {step.depends_on})' if step.depends_on is not None else ''
            ref_str = ''
            if step.param_refs:
                refs = ', '.join(f'{k}={v}' for k, v in step.param_refs.items())
                ref_str = f' [{refs}]'
            parts.append(f'  {i}: {step.tool}{action_str}{parallel_str}{dep_str}{ref_str}')

        return '\n'.join(parts)


# ============================================================
# Dynamic Prompt Builder
# ============================================================

class DynamicPromptBuilder:
    """Builds a focused LLM prompt from a planned chain."""

    def __init__(self, graph: ToolGraph):
        self.graph = graph

    def build(self, chain: PlannedChain, query: str) -> str:
        """Build dynamic prompt for LLM executor.
        
        Instead of sending all 54 tools, send only the tools in the chain
        with explicit ordering instructions.
        """
        if not chain.chain:
            return ''

        lines = [
            '🎯 ПЛАН ВЫПОЛНЕНИЯ:',
            f'Запрос: {query}',
            f'Шагов: {len(chain.chain)}, Стоимость: {chain.cost}',
            '',
            '📋 ПОРЯДОК ВЫЗОВОВ:',
        ]

        for i, step in enumerate(chain.chain):
            tool = self.graph.nodes.get(step.tool)
            if not tool:
                continue

            action_str = f' action="{step.action}"' if step.action else ''
            parallel_str = ' ⚡ ПАРАЛЛЕЛЬНО' if step.parallel else ''

            lines.append(f'\n{i + 1}. `{step.tool}`{action_str}{parallel_str}')
            lines.append(f'   {tool.description}')

            # Show required params
            if step.params:
                params_str = ', '.join(f'{k}={v}' for k, v in step.params.items())
                lines.append(f'   Параметры: {params_str}')

            if step.param_refs:
                refs_str = ', '.join(f'{k} ← {v}' for k, v in step.param_refs.items())
                lines.append(f'   Из предыдущего шага: {refs_str}')

            if step.depends_on is not None:
                dep_tool = chain.chain[step.depends_on].tool
                lines.append(f'   ⚠️ Ждать результат шага {step.depends_on + 1} ({dep_tool})')

        lines.extend([
            '',
            '⚠️ ПРАВИЛА:',
            '1. Вызывай инструменты СТРОГО в указанном порядке',
            '2. Передавай результаты предыдущих шагов в следующие (см. "$step")',
            '3. Параллельные шаги можно вызывать одновременно',
            '4. Если шаг не нужен по контексту — пропусти его',
        ])

        return '\n'.join(lines)

    def build_tool_filter(self, chain: PlannedChain) -> List[str]:
        """Return list of tool names that should be available to LLM."""
        return list(dict.fromkeys(step.tool for step in chain.chain))


# ============================================================
# Planner Facade
# ============================================================

class ToolGraphPlanner:
    """Main facade for the tool graph planner.
    
    Usage:
        planner = ToolGraphPlanner()
        result = planner.plan('добавь VIP-клиента с аналитикой')
        prompt = planner.build_prompt(result, query)
    """

    def __init__(self, registry_path: Optional[str] = None):
        self.graph, self.detector = load_registry(registry_path)
        self._planner = ChainPlanner(self.graph, self.detector)
        self._prompt_builder = DynamicPromptBuilder(self.graph)
        logger.info(
            f'ToolGraphPlanner initialized: '
            f'{len(self.graph.nodes)} tools, {len(self.graph.edges)} edges'
        )

    def plan(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        max_chain_length: int = 8,
    ) -> PlannedChain:
        """Plan optimal tool chain for query."""
        return self._planner.plan(query, context, max_chain_length)

    def build_prompt(self, chain: PlannedChain, query: str) -> str:
        """Build dynamic LLM prompt from planned chain."""
        return self._prompt_builder.build(chain, query)

    def get_tool_filter(self, chain: PlannedChain) -> List[str]:
        """Get list of tool names to include in LLM tool list."""
        return self._prompt_builder.build_tool_filter(chain)

    def detect_intents(self, query: str) -> List[Dict[str, Any]]:
        """Detect intents from query (for debugging)."""
        return self.detector.detect(query)

    def to_yaml(self, chain: PlannedChain) -> str:
        """Serialize chain to YAML format."""
        import io
        data = {
            'chain': [],
            'cost': chain.cost,
            'constraints_ok': chain.constraints_ok,
            'intents': chain.intents,
            'latency_ms': chain.latency_ms,
        }
        for step in chain.chain:
            step_data: Dict[str, Any] = {'tool': step.tool}
            if step.action:
                step_data['action'] = step.action
            if step.params:
                step_data['params'] = step.params
            if step.parallel:
                step_data['parallel'] = True
            if step.param_refs:
                step_data['param_refs'] = step.param_refs
            data['chain'].append(step_data)

        buf = io.StringIO()
        yaml.dump(data, buf, default_flow_style=False, allow_unicode=True)
        return buf.getvalue()

    def stats(self) -> Dict[str, Any]:
        """Return planner statistics."""
        total_actions = sum(len(n.actions) for n in self.graph.nodes.values())
        total_caps = sum(len(n.capabilities) for n in self.graph.nodes.values())
        return {
            'tools': len(self.graph.nodes),
            'actions': total_actions,
            'edges': len(self.graph.edges),
            'capabilities': total_caps,
        }
