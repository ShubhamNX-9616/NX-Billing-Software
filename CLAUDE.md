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
public `shared_*`, `tailoring_*report*`, `tailoring_receipt*`, and
`unauthorized.html` templates — they don't extend `base.html`, but they do
`<link>` `base.css` directly (no theme-toggle script, so tokens always
resolve light). Substitute by what the value *means*, not by whichever
token is nearest in hex — `#f3f4f6` sits between `--bg` and `--border`, and
only one of those is a line colour.

When a hex/glyph search on a directory returns a capped result set, narrow
the search and re-run it before trusting the count — a truncated match list
has under-reported scope three times now.

<!-- glyph rule -->
## Glyphs: icon sprite vs. emoji vs. plain text

Applies regardless of encoding — a literal `✓`/`✕` character, the HTML
entity (`&#10003;`/`&#215;`), and a JS `✓` escape are the same glyph
and the same problem: they render as a tofu box on the wrong OS/font and
don't theme with `currentColor`. A search for one encoding is not a search
for the glyph — check all three before calling a sweep clean.

The fix depends on which layer is rendering the UI:

- **Server-rendered markup** (Jinja templates): use the `_icons.html`
  sprite, `{{ icon('name', size) }}`.
- **JS that builds markup via `innerHTML`** (can carry an `<svg>`): use the
  same sprite through its DOM form, `<svg class="ico" aria-hidden="true">
  <use href="#i-name"/></svg>` — already the established pattern in
  `tailoring.js`, `history.js`, `inventory.js`, `customers.js`. One sprite,
  no second icon set to keep in sync.
- **JS that sets `.textContent`** on a button/status label (can't carry
  markup at all): no glyph, no icon — plain text only. "Saved", "Payment
  balanced", "Copied" already carry the meaning; a checkmark there was
  decoration on a label that was already changing. Don't add markup-based
  workarounds to route around `.textContent` — if a spot like this
  genuinely needs an icon, that's a sign it should become an `.innerHTML`
  site instead, not an excuse to keep the glyph.

If a template's initial paint and a JS `.textContent` assignment both set
the same element's label, they must agree on which of the above it is —
fixing one without the other means the JS repaints the glyph back on the
next state change (this is exactly what happened to
`new_institution_bill.html`'s save button between rounds 8 and 9).

Exception: emoji inside a WhatsApp share-text string (the JS that builds
`wa.me/?text=...`, e.g. `bill_detail.html`, `institution_bill_detail.html`,
`tailoring_report.html`'s `waText()`) is chat text going into another app,
not a control in this UI — the icon sprite can't reach it anyway. Leave
those alone.

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
