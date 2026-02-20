"""
Visualize the KommoMCP Tool Graph from tool_registry.yaml.
Generates a high-quality PNG with category clusters, readable labels, and edge legend.
"""

import yaml
import networkx as nx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from pathlib import Path
from collections import defaultdict
import math
import random

random.seed(42)

# ── Load registry ──
registry_path = Path(__file__).parent.parent / 'src' / 'kommo_mcp' / 'planner' / 'tool_registry.yaml'
with open(registry_path, 'r', encoding='utf-8') as f:
    data = yaml.safe_load(f)

# ── Category config ──
CATEGORY_META = {
    'pipeline':       {'color': '#4A90D9', 'label': 'Pipeline'},
    'analytics':      {'color': '#E8913A', 'label': 'Analytics'},
    'deals':          {'color': '#D94A4A', 'label': 'Deals'},
    'tasks':          {'color': '#9B59B6', 'label': 'Tasks'},
    'contacts':       {'color': '#27AE60', 'label': 'Contacts'},
    'communications': {'color': '#1ABC9C', 'label': 'Comms'},
    'search':         {'color': '#F1C40F', 'label': 'Search'},
    'forecasting':    {'color': '#E74C3C', 'label': 'Forecast'},
    'advisor':        {'color': '#8E44AD', 'label': 'AI Advisor'},
    'entity':         {'color': '#C0392B', 'label': 'Entity Ops'},
    'setup':          {'color': '#2C3E50', 'label': 'Setup'},
    'templates':      {'color': '#16A085', 'label': 'Templates'},
    'automation':     {'color': '#D35400', 'label': 'Automation'},
    'team':           {'color': '#2980B9', 'label': 'Team'},
    'utility':        {'color': '#7F8C8D', 'label': 'Utility'},
}

EDGE_STYLES = {
    'REQUIRES': {'color': '#E74C3C', 'style': 'solid',  'width': 2.8, 'label': 'REQUIRES (dependency)'},
    'SEQUENCE': {'color': '#3498DB', 'style': 'dashed', 'width': 2.0, 'label': 'SEQUENCE (ordering)'},
    'PARALLEL': {'color': '#2ECC71', 'style': 'dotted', 'width': 2.0, 'label': 'PARALLEL (concurrent)'},
}

# ── Pretty label ──
def short_label(tid):
    s = tid.replace('kommo_', '')
    # Capitalize and shorten
    parts = s.split('_')
    if len(parts) <= 2:
        return '\n'.join(p.capitalize() for p in parts)
    # Abbreviate long names
    return '\n'.join(p.capitalize() for p in parts[:3])

# ── Build graph ──
G = nx.DiGraph()

tool_categories = {}
tool_action_counts = {}
for tool in data.get('tools', []):
    tid = tool['id']
    cat = tool.get('category', 'unknown')
    actions = tool.get('actions', [])
    n_actions = len(actions) if isinstance(actions, list) else 0
    tool_categories[tid] = cat
    tool_action_counts[tid] = n_actions
    G.add_node(tid, category=cat, n_actions=n_actions)

for edge in data.get('edges', []):
    from_tool = edge['from'].split('.')[0]
    to_tool = edge['to'].split('.')[0]
    etype = edge['type']
    G.add_edge(from_tool, to_tool, edge_type=etype, reason=edge.get('reason', ''))

# ── Category groups ──
categories = defaultdict(list)
for tid, cat in tool_categories.items():
    categories[cat].append(tid)

# ── Manual radial layout: categories on a big circle, tools on small circles ──
cat_order = [
    'pipeline', 'analytics', 'forecasting', 'deals',
    'contacts', 'communications', 'search', 'entity',
    'setup', 'automation', 'advisor', 'tasks',
    'templates', 'team', 'utility',
]
# Filter to only present categories
cat_order = [c for c in cat_order if c in categories]

n_cats = len(cat_order)
big_radius = 18
pos = {}

for i, cat in enumerate(cat_order):
    angle = 2 * math.pi * i / n_cats - math.pi / 2  # start from top
    cx = big_radius * math.cos(angle)
    cy = big_radius * math.sin(angle)
    tools = categories[cat]
    n = len(tools)
    # Spread tools in a small cluster around category center
    small_r = 1.2 + 0.5 * n  # bigger cluster for more tools
    small_r = min(small_r, 7.0)
    for j, tid in enumerate(tools):
        a = 2 * math.pi * j / max(n, 1)
        jitter = random.uniform(-0.15, 0.15)
        px = cx + small_r * math.cos(a) + jitter
        py = cy + small_r * math.sin(a) + jitter
        pos[tid] = (px, py)

# ── Draw ──
fig, ax = plt.subplots(1, 1, figsize=(56, 48))
fig.patch.set_facecolor('#0D1117')
ax.set_facecolor('#0D1117')

# Draw category background circles (clusters)
for i, cat in enumerate(cat_order):
    angle = 2 * math.pi * i / n_cats - math.pi / 2
    cx = big_radius * math.cos(angle)
    cy = big_radius * math.sin(angle)
    n = len(categories[cat])
    r = 1.8 + 0.6 * n
    r = min(r, 8.0)
    color = CATEGORY_META.get(cat, {}).get('color', '#555')
    circle = plt.Circle((cx, cy), r, color=color, alpha=0.08, zorder=0)
    ax.add_patch(circle)
    # Category label above cluster
    label = CATEGORY_META.get(cat, {}).get('label', cat)
    ax.text(
        cx, cy + r + 0.9, f'{label} ({n})',
        ha='center', va='bottom',
        fontsize=20, fontweight='bold',
        color=color,
        path_effects=[pe.withStroke(linewidth=3, foreground='#0D1117')],
        zorder=10,
    )

# Draw edges by type
for etype, style in EDGE_STYLES.items():
    edges = [(u, v) for u, v, d in G.edges(data=True) if d.get('edge_type') == etype]
    if edges:
        nx.draw_networkx_edges(
            G, pos, edgelist=edges, ax=ax,
            edge_color=style['color'],
            style=style['style'],
            width=style['width'],
            alpha=0.55,
            arrows=True,
            arrowsize=22,
            arrowstyle='-|>',
            connectionstyle='arc3,rad=0.12',
            min_source_margin=25,
            min_target_margin=25,
        )

# Draw nodes
for cat, tools in categories.items():
    color = CATEGORY_META.get(cat, {}).get('color', '#95A5A6')
    nodelist = [t for t in tools if t in G.nodes]
    # Size proportional to number of actions
    sizes = [2800 + tool_action_counts.get(t, 0) * 200 for t in nodelist]
    nx.draw_networkx_nodes(
        G, pos, nodelist=nodelist, ax=ax,
        node_color=color,
        node_size=sizes,
        alpha=0.92,
        edgecolors='#1a1a2e',
        linewidths=2.5,
    )

# Labels on nodes
for tid in G.nodes:
    x, y = pos[tid]
    label = short_label(tid)
    n_act = tool_action_counts.get(tid, 0)
    if n_act > 0:
        label += f'\n({n_act})'
    ax.text(
        x, y, label,
        ha='center', va='center',
        fontsize=10,
        fontweight='bold',
        color='white',
        path_effects=[pe.withStroke(linewidth=2, foreground='#111')],
        zorder=5,
    )

# ── Legend ──
# Categories
cat_patches = []
for cat in cat_order:
    meta = CATEGORY_META.get(cat, {})
    color = meta.get('color', '#555')
    label = meta.get('label', cat)
    count = len(categories[cat])
    cat_patches.append(mpatches.Patch(color=color, label=f'{label} ({count} tools)'))

legend1 = ax.legend(
    handles=cat_patches,
    loc='upper left',
    title='CATEGORIES',
    fontsize=11,
    framealpha=0.85,
    fancybox=True,
    edgecolor='#333',
    facecolor='#161B22',
    labelcolor='white',
    title_fontproperties={'weight': 'bold', 'size': 13},
)
plt.setp(legend1.get_title(), color='white')
ax.add_artist(legend1)

# Edge types
edge_patches = [
    plt.Line2D([0], [0], color=s['color'], linewidth=s['width'],
               linestyle=s['style'], label=s['label'])
    for etype, s in EDGE_STYLES.items()
]
legend2 = ax.legend(
    handles=edge_patches,
    loc='upper right',
    title='EDGE TYPES',
    fontsize=11,
    framealpha=0.85,
    fancybox=True,
    edgecolor='#333',
    facecolor='#161B22',
    labelcolor='white',
    title_fontproperties={'weight': 'bold', 'size': 13},
)
plt.setp(legend2.get_title(), color='white')

# Title
total_actions = sum(tool_action_counts.values())
ax.set_title(
    'KommoMCP — Tool Graph\n'
    f'{len(G.nodes)} tools  ·  {total_actions} actions  ·  '
    f'{len(G.edges)} edges  ·  {len(categories)} categories',
    fontsize=22,
    fontweight='bold',
    color='white',
    pad=25,
)

# Stats box
stats_text = (
    f'Planner latency: <2ms\n'
    f'LLM sees: 2-6 tools (not {len(G.nodes)})\n'
    f'Backward chaining + topo sort\n'
    f'Zero-cost (no LLM calls)'
)
ax.text(
    0.5, 0.01, stats_text,
    transform=ax.transAxes,
    ha='center', va='bottom',
    fontsize=12,
    color='#8B949E',
    fontstyle='italic',
    bbox=dict(boxstyle='round,pad=0.5', facecolor='#161B22', edgecolor='#333', alpha=0.9),
)

ax.axis('off')
plt.tight_layout()

# Save
output_path = Path(__file__).parent.parent / 'docs' / 'tool_graph.png'
plt.savefig(output_path, dpi=180, bbox_inches='tight', facecolor='#0D1117')
print(f'Graph saved to {output_path}')
print(f'Nodes: {len(G.nodes)}, Edges: {len(G.edges)}, Actions: {total_actions}')
print(f'Categories: {dict((k, len(v)) for k, v in sorted(categories.items()))}')
plt.close()
