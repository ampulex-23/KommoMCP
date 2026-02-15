-- Tool Graph Schema for MCP Agent Planner
-- Stores tool definitions, capabilities, and graph edges for deterministic chain planning

BEGIN;

-- ============================================================
-- Core tables
-- ============================================================

CREATE TABLE IF NOT EXISTS tools (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL,
    description TEXT NOT NULL,
    cost        REAL NOT NULL DEFAULT 0.2,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tool_actions (
    id          SERIAL PRIMARY KEY,
    tool_id     TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    action_id   TEXT NOT NULL,
    description TEXT,
    cost        REAL,
    UNIQUE(tool_id, action_id)
);

-- Inputs/outputs per action (or per tool if action_id is NULL)
CREATE TABLE IF NOT EXISTS tool_inputs (
    id          SERIAL PRIMARY KEY,
    tool_id     TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    action_id   TEXT,  -- NULL = tool-level input
    param_name  TEXT NOT NULL,
    param_type  TEXT NOT NULL DEFAULT 'string',
    required    BOOLEAN NOT NULL DEFAULT false,
    description TEXT
);

CREATE TABLE IF NOT EXISTS tool_outputs (
    id          SERIAL PRIMARY KEY,
    tool_id     TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    action_id   TEXT,  -- NULL = tool-level output
    param_name  TEXT NOT NULL,
    param_type  TEXT NOT NULL DEFAULT 'string',
    description TEXT
);

-- Preconditions: what must be true before tool can run
CREATE TABLE IF NOT EXISTS tool_preconditions (
    id          SERIAL PRIMARY KEY,
    tool_id     TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    action_id   TEXT,
    condition   TEXT NOT NULL,  -- e.g. 'pipeline_id_known', 'lead_exists'
    description TEXT
);

-- Effects: what changes after tool runs
CREATE TABLE IF NOT EXISTS tool_effects (
    id          SERIAL PRIMARY KEY,
    tool_id     TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    action_id   TEXT,
    effect      TEXT NOT NULL,  -- e.g. 'lead_created', 'note_added'
    description TEXT
);

-- Capabilities: what a tool can do (for intent matching)
CREATE TABLE IF NOT EXISTS tool_capabilities (
    id          SERIAL PRIMARY KEY,
    tool_id     TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    capability  TEXT NOT NULL,
    UNIQUE(tool_id, capability)
);

CREATE INDEX IF NOT EXISTS idx_capabilities_cap ON tool_capabilities(capability);

-- ============================================================
-- Graph edges between tools
-- ============================================================

CREATE TABLE IF NOT EXISTS tool_edges (
    id          SERIAL PRIMARY KEY,
    from_tool   TEXT NOT NULL,  -- tool_id or tool_id.action_id
    to_tool     TEXT NOT NULL,  -- tool_id or tool_id.action_id
    edge_type   TEXT NOT NULL CHECK (edge_type IN ('REQUIRES', 'PRODUCES', 'SEQUENCE', 'PARALLEL')),
    weight      REAL NOT NULL DEFAULT 0.5,
    reason      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(from_tool, to_tool, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON tool_edges(from_tool);
CREATE INDEX IF NOT EXISTS idx_edges_to ON tool_edges(to_tool);
CREATE INDEX IF NOT EXISTS idx_edges_type ON tool_edges(edge_type);

-- ============================================================
-- Capability map: user intents → capabilities
-- ============================================================

CREATE TABLE IF NOT EXISTS intent_map (
    id          SERIAL PRIMARY KEY,
    intent      TEXT NOT NULL UNIQUE,
    keywords    TEXT[] NOT NULL DEFAULT '{}',
    capabilities TEXT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_intent_keywords ON intent_map USING GIN(keywords);

-- ============================================================
-- Chain execution log (for learning and metrics)
-- ============================================================

CREATE TABLE IF NOT EXISTS chain_executions (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    query           TEXT NOT NULL,
    detected_intents TEXT[] NOT NULL DEFAULT '{}',
    chain           JSONB NOT NULL,  -- [{tool, action, params, parallel}]
    total_cost      REAL,
    latency_ms      INTEGER,
    success         BOOLEAN,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chain_user ON chain_executions(user_id);
CREATE INDEX IF NOT EXISTS idx_chain_created ON chain_executions(created_at);

-- ============================================================
-- Views for graph traversal
-- ============================================================

-- View: tool dependency graph (what tool A needs from tool B)
CREATE OR REPLACE VIEW v_tool_dependencies AS
SELECT
    e.from_tool,
    e.to_tool,
    e.edge_type,
    e.weight,
    e.reason,
    t1.category AS from_category,
    t2.category AS to_category
FROM tool_edges e
LEFT JOIN tools t1 ON split_part(e.from_tool, '.', 1) = t1.id
LEFT JOIN tools t2 ON split_part(e.to_tool, '.', 1) = t2.id;

-- View: tool with all capabilities
CREATE OR REPLACE VIEW v_tool_capabilities AS
SELECT
    t.id,
    t.name,
    t.category,
    t.description,
    t.cost,
    array_agg(DISTINCT tc.capability) AS capabilities
FROM tools t
LEFT JOIN tool_capabilities tc ON t.id = tc.tool_id
GROUP BY t.id, t.name, t.category, t.description, t.cost;

-- View: full tool action detail
CREATE OR REPLACE VIEW v_tool_actions AS
SELECT
    ta.tool_id,
    ta.action_id,
    t.name AS tool_name,
    t.category,
    array_agg(DISTINCT ti.param_name) FILTER (WHERE ti.param_name IS NOT NULL) AS inputs,
    array_agg(DISTINCT tou.param_name) FILTER (WHERE tou.param_name IS NOT NULL) AS outputs,
    array_agg(DISTINCT te.effect) FILTER (WHERE te.effect IS NOT NULL) AS effects
FROM tool_actions ta
JOIN tools t ON ta.tool_id = t.id
LEFT JOIN tool_inputs ti ON ta.tool_id = ti.tool_id AND ta.action_id = ti.action_id
LEFT JOIN tool_outputs tou ON ta.tool_id = tou.tool_id AND ta.action_id = tou.action_id
LEFT JOIN tool_effects te ON ta.tool_id = te.tool_id AND ta.action_id = te.action_id
GROUP BY ta.tool_id, ta.action_id, t.name, t.category;

-- ============================================================
-- Graph traversal functions
-- ============================================================

-- Find all paths from a set of capabilities to a goal
CREATE OR REPLACE FUNCTION find_tool_chain(
    p_capabilities TEXT[],
    p_max_depth INTEGER DEFAULT 5
)
RETURNS TABLE(
    path_tools TEXT[],
    path_cost REAL,
    path_length INTEGER
) AS $$
WITH RECURSIVE chain AS (
    -- Start: tools that match requested capabilities
    SELECT
        ARRAY[tc.tool_id] AS path,
        t.cost AS total_cost,
        1 AS depth,
        tc.tool_id AS current_tool
    FROM tool_capabilities tc
    JOIN tools t ON tc.tool_id = t.id
    WHERE tc.capability = ANY(p_capabilities)

    UNION ALL

    -- Extend: follow SEQUENCE and REQUIRES edges
    SELECT
        c.path || e.to_tool,
        c.total_cost + COALESCE(t2.cost, 0.2),
        c.depth + 1,
        split_part(e.to_tool, '.', 1)
    FROM chain c
    JOIN tool_edges e ON split_part(e.from_tool, '.', 1) = c.current_tool
    JOIN tools t2 ON split_part(e.to_tool, '.', 1) = t2.id
    WHERE c.depth < p_max_depth
      AND e.edge_type IN ('SEQUENCE', 'REQUIRES')
      AND NOT (split_part(e.to_tool, '.', 1) = ANY(c.path))
)
SELECT DISTINCT
    path AS path_tools,
    total_cost AS path_cost,
    depth AS path_length
FROM chain
ORDER BY total_cost, depth;
$$ LANGUAGE SQL STABLE;

-- Find tools that can satisfy a set of output requirements
CREATE OR REPLACE FUNCTION find_tools_by_output(
    p_outputs TEXT[]
)
RETURNS TABLE(
    tool_id TEXT,
    tool_name TEXT,
    action_id TEXT,
    matched_outputs TEXT[]
) AS $$
SELECT
    tou.tool_id,
    t.name AS tool_name,
    tou.action_id,
    array_agg(tou.param_name) AS matched_outputs
FROM tool_outputs tou
JOIN tools t ON tou.tool_id = t.id
WHERE tou.param_name = ANY(p_outputs)
GROUP BY tou.tool_id, t.name, tou.action_id;
$$ LANGUAGE SQL STABLE;

COMMIT;
