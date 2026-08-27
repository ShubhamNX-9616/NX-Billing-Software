<!-- design tokens -->
## CSS: design tokens

Colours, radii and the type scale come from tokens in `static/css/base.css`
(`:root` for light, the `html[data-theme="dark"]` block for dark). New hex
belongs in `:root`, the dark token block, or a `@media print` block —
nowhere else. No `var()` fallbacks (`var(--x, #ccc)`); every screen loads
`base.css`, so a missing token is not the problem you have.

Three exceptions, all of them "this never sees a theme": `color: #fff` on a
saturated brand fill (`.btn-primary` etc. — white-on-accent isn't a themed
decision, and a token that can only ever hold one value isn't a token), PIL
label rendering in `routes/inventory.py`, and documents built as JS strings
(`static/js/inst-performa.js`). Everything else uses tokens, including the
public `shared_*` and `tailoring_receipt*`/`tailoring_report` templates —
they don't extend `base.html`, but they do `<link>` `base.css` directly
(no theme-toggle script, so tokens always resolve light).

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
