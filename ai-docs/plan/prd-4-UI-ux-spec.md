# UX Specification: KYC Workflow Automation UI

---

## Pre-Pass 0: Context Extraction

**Screens identified:**
1. **Dashboard (Mission Control)** — High-level stats: workflow count, active runs, 7-day success/error rates
2. **Agent Library** — Create and configure reusable agents (GCP Agent Builder style)
3. **Workflow Builder** — Drag-and-drop canvas to construct workflows from agents (n8n style)
4. **Workflow Runs** — List all runs, trigger a new run, preview workflow diagram before triggering
5. **Run Detail (Execution Monitor)** — Visualize execution diagram, drill into per-node input/output/state/timing (Langfuse style)

**Data models:**
- `src/config/agents.yaml`: Defines reusable agent catalog — role, goal, backstory, model, temperature, max_tokens, retry config, execution type (llm/rule), rule_fn, system_prompt (inline or file), input_keys, output_key, retry_count_key, output_schema, matching_threshold
- `src/config/workflows.yaml`: Defines workflow topology — metadata, state schema, nodes (agent instances), edges (unconditional and conditional with routing fn/routes/on_traverse), observability config, runtime config, variables

**Reference UIs:**
- **n8n.io**: workflow builder canvas (drag-and-drop, node palette, property panel, edge drawing), workflow diagram rendering, live execution animation
- **GCP Vertex AI Agent Builder**: agent library (list + detail), step-form with grouped config sections
- **Langfuse**: execution trace timeline, per-span input/output JSON, session state inspection

**Personas:**
- **Workflow Engineer** (primary): technically proficient, builds and maintains YAML-backed agent workflows, needs full access to all YAML attributes through the UI
- **KYC Operator** (secondary): triggers workflow runs and monitors execution, less interested in configuration detail

**Design-time / Runtime split:** Yes
- Design-time: Agent Library + Workflow Builder (creating definitions)
- Runtime: Workflow Runs + Run Detail (triggering and observing executions)
- Dashboard bridges both (aggregated view)

---

## Pass 1: Mental Model

**Primary user intent:** Build, trigger, and monitor multi-agent AI workflows visually — without hand-editing YAML files.

**Likely misconceptions:**
- "Nodes and agents are the same thing" → Reality: **Agents** are reusable library templates; **Nodes** are workflow instances that reference an agent. You configure the agent once and reuse it across many workflows.
- "I can modify a workflow while it's running" → Reality: workflow definitions are immutable during execution; you see a read-only diagram in Run Detail.
- "The canvas diagram IS the execution" → Reality: the canvas shows the definition; execution creates a separate trace with its own state.
- "The feedback loop (critic → retry) is a bug" → Reality: critics route back to their source agent intentionally when validation fails; this is by design and must be visually obvious.
- "I need to write Python routing functions" → Reality: common routing patterns (like critic decision routing) should be selectable from a dropdown of known functions.

**Key distinctions users must learn:**
- **Agent vs Node**: Agent = library template (configured once, reused). Node = workflow instance (a specific placement of an agent in one workflow). UI must use these terms consistently and never conflate them.
- **Definition vs Execution**: Workflow Builder = design-time (static YAML). Run Detail = runtime (live or historical trace). Visual language (colors, icons, labels) must clearly separate these modes.

**UX principle to reinforce:** The UI is a visual editor for YAML. Every field the user touches must correspond to a real YAML attribute. No "magic" settings that don't serialize back to the config files.

---

## Pass 2: Information Architecture

**All user-visible concepts:**
- Agent (role, goal, backstory, model, temperature, max_tokens, retry config, execution type, prompt, input/output keys, output schema)
- Workflow definition (id, name, description, entry_point, max_steps, timeout, state schema, nodes, edges, observability, runtime, variables)
- Node (type, agent reference)
- Edge (from, to, conditional routing: fn, routes, on_traverse)
- Workflow run (id, workflow, status, started, duration, entry inputs)
- Node execution (input, output, timing, error, session state snapshot)
- Dashboard stats (workflow count, active runs, 7-day success/error)

**Grouped structure:**

### Dashboard
- Active run count: Primary
- Workflow count: Primary
- 7-day success/error: Primary
- Recent runs list: Secondary (shortcut to Runs screen)

### Agent Library
- Agent list (name, role, model, execution type): Primary
- Agent editor:
  - Identity (role, goal, backstory): Primary
  - Execution config (type, model, temperature, max_tokens): Primary
  - Retry config (max_attempts, backoff, delay): Secondary
  - Prompt (inline/file toggle, prompt content): Primary
  - I/O keys (input_keys, output_key, retry_count_key): Primary
  - Output schema (ref, is_list, example): Secondary
  - Matching threshold: Hidden (shown only when applicable)
- Delete agent action: Secondary

### Workflow Builder
- Canvas (nodes, edges): Primary
- Node palette (agents from library): Primary
- Node property panel (agent ref, type): Primary
- Edge property panel (unconditional/conditional toggle, routing fn, routes table, on_traverse): Primary
- Workflow metadata panel (id, name, description, entry_point, max_steps, timeout): Secondary
- State schema editor: Hidden (advanced, accessible via gear icon)
- Runtime config (checkpointer, URI): Hidden
- Observability config (provider, project, tags): Hidden
- Variables editor: Hidden
- Toolbar (Save, Export YAML, Import YAML, Validate): Primary

### Workflow Runs
- Workflows list (name, description, last run date): Primary — browse and inspect before triggering
- Workflow diagram view (read-only n8n-style canvas, full size): Primary — visible BEFORE deciding to trigger
- `Trigger Run` CTA on the diagram view: Primary
- Runs list (run ID, workflow name, status, started, duration): Primary
- Status filter bar: Primary
- Trigger Run modal (entry input JSON editor, opens from diagram view): Primary

### Run Detail
- Execution diagram (read-only canvas with live state for in-progress): Primary
- Node detail panel (input, output, timing, state, error tabs): Primary
- Timeline (horizontal span view): Secondary
- Run metadata header (workflow name, run ID, status, duration): Primary

**Navigation architecture:**
- Top-level nav: persistent left sidebar with 5 items: Dashboard, Agents, Workflows, Runs, (Settings)
- Secondary nav within Workflow Builder: tabbed panels (Canvas / Metadata / State Schema / Runtime / Variables)
- Secondary nav within Run Detail: node click → tabbed panel (Input / Output / Timing / State / Error)
- Entry point / home: Dashboard
- Navigation principle: persistent left sidebar (always visible); detail views open in the same page via sliding panels, not new routes

**Data Model → UI Mapping (agents.yaml):**

| Schema field | UI label | Form type | Notes |
|---|---|---|---|
| `role` | Role | Single-line text | Required |
| `goal` | Goal | Single-line text | Supports `{var}` interpolation hint |
| `backstory` | Backstory | Textarea (multiline) | Required |
| `execution` | Execution type | Toggle/dropdown: `llm` / `rule` | Controls visibility of prompt and rule_fn sections |
| `rule_fn` | Rule function | Single-line text (dotted path) | Shown only when `execution: rule` |
| `model` | Model | Dropdown + free text (LiteLLM format) | Shows inherited default from `defaults.model` |
| `temperature` | Temperature | Slider 0.0–1.0 | Shows inherited default; shows "inherited" badge when not overridden |
| `max_tokens` | Max tokens | Number input | Shows inherited default |
| `retry.max_attempts` | Max retry attempts | Number input | Shows inherited default |
| `retry.backoff` | Backoff strategy | Dropdown: `linear` / `exponential` / `fixed` | Shows inherited default |
| `retry.delay_seconds` | Retry delay (seconds) | Number input | Shows inherited default |
| `input_keys` | Input state keys | Tag input (multi-value) | Autocomplete from workflow state schema |
| `output_key` | Output state key | Single-line text | |
| `retry_count_key` | Retry count state key | Single-line text | |
| `matching_threshold` | Matching threshold | Slider 0.0–1.0 | Shown only when relevant (rule-based agents with fuzzy matching) |
| `system_prompt.inline` | Prompt (inline) | Code textarea | Shown when inline mode selected |
| `system_prompt.file` | Prompt file path | File path text input | Shown when file mode selected |
| `output_schema.ref` | Output schema class | Single-line text (Pydantic class path) | |
| `output_schema.is_list` | Output is list | Toggle | |
| `output_schema.example` | Schema example | JSON editor | Alternative to ref |

**Data Model → UI Mapping (workflows.yaml):**

| Schema field | UI label | Form type | Notes |
|---|---|---|---|
| `workflow.id` | Workflow ID | Single-line text (auto-slugified from name) | |
| `workflow.name` | Name | Single-line text | Required |
| `workflow.description` | Description | Textarea | |
| `workflow.entry_point` | Entry point | Dropdown (from node list) | Default `__start__` |
| `workflow.max_steps` | Max steps | Number input | |
| `workflow.timeout_seconds` | Timeout (seconds) | Number input | |
| `state.*` | State schema | Table editor (key, type, default) | Advanced panel |
| `nodes.*.type` | Node type | Dropdown: `agent` / `parallel` / `merger` / `human` / `subgraph` / `end` | |
| `nodes.*.agent` | Agent | Dropdown (from agent library) | Link icon opens agent editor |
| `edges.from / to` | Source / Target | Canvas connection handle | |
| `edge.condition.fn` | Routing function | Dropdown of known fns + free text | Shows common patterns (e.g. `route_on_critic_decision`) |
| `edge.condition.routes.*` | Route table | Key-value rows (route string → node dropdown) | |
| `edge.on_traverse.when_route` | Trigger on route | Single-line text | |
| `edge.on_traverse.increment_key` | Increment state key | Single-line text (autocomplete from state schema) | |
| `observability.provider` | Observability provider | Dropdown: `langsmith` / `langfuse` / `none` | |
| `observability.project` | Project name | Single-line text | |
| `observability.tags` | Tags | Tag input | |
| `runtime.checkpointer` | Checkpointer | Dropdown: `sqlite` / `postgres` / `memory` / `redis` | |
| `runtime.checkpointer_uri` | Checkpointer URI | Single-line text | |
| `vars.*` | Variables | Key-value table | Value supports `${ENV_VAR}` syntax hint |

---

## Pass 3: Affordances

**Reference UI pattern analysis:**

| Reference | Pattern to borrow | Used in screen | Adaptation needed |
|---|---|---|---|
| n8n.io | Drag from left palette to canvas to instantiate node | Workflow Builder | Palette shows agent library items (not node type palette) |
| n8n.io | Port handles appear on node hover; drag from port to draw edge | Workflow Builder | Conditional edge routing panel opens on edge click |
| n8n.io | Right-side properties panel slides in on node/edge selection | Workflow Builder, Run Detail | Panel content maps to YAML fields, not generic node settings |
| n8n.io | Loopback edges rendered as curved arrows with label | Workflow Builder, Run Detail | Show retry count badge on loopback edges during execution |
| n8n.io | Active node pulsing animation during live execution | Run Detail | Blue pulse for active node; green checkmark for completed; red X for error |
| GCP Agent Builder | Left list + right detail layout for entity management | Agent Library | Left panel = agent cards; right panel = agent editor form |
| GCP Agent Builder | Grouped form sections with collapsible advanced config | Agent editor | Section headers: Identity / Execution / Retry / Prompt / I/O / Schema |
| GCP Agent Builder | Inherited defaults shown as placeholder with "default" badge | Agent editor | Show `defaults.model`, `defaults.temperature` etc. as greyed-out placeholders |
| Langfuse | Horizontal timeline with collapsible spans showing timing | Run Detail | Timeline at bottom; each span = one node execution |
| Langfuse | Per-span input/output JSON side by side | Run Detail node panel | Tabs: Input / Output / Timing / State / Error |
| Langfuse | Session state snapshot accessible per span | Run Detail node panel | "State" tab shows full WorkflowState at that node |

**Affordances table:**

| Action | Visual/Interaction Signal |
|---|---|
| Drag agent from palette to canvas | Palette items show grab cursor + elevation shadow on hover |
| Draw edge between nodes | Port dots appear on node hover; cursor changes to crosshair when over port |
| Open node config | Click node → blue selection ring + right panel slides open |
| Open edge config | Click edge → edge highlights + right panel slides open with edge settings |
| Toggle conditional edge | Checkbox/toggle "Conditional" in edge panel; routing table appears when enabled |
| Delete node or edge | Selected node/edge shows Delete key or trash icon in panel |
| Agent is inherited vs overridden | Fields show "inherited" badge (grey) when using defaults; override removes badge |
| Trigger a run | Prominent "Run" button in toolbar and Runs screen; disabled if no workflow selected |
| Drill into run detail | Run list rows are fully clickable (hover highlight + cursor pointer) |
| Active node during execution | Pulsing animated border (blue); adjacent edges animate flow direction |
| Completed node | Static green checkmark icon overlay |
| Failed node | Static red X icon overlay |
| Click node in execution diagram | Node gets selection ring + detail panel opens |
| Save workflow | "Save" button in toolbar; unsaved changes indicator (dot on "Save" button label) |

**Affordance rules:**
- If a palette item has a grab handle icon, dragging it creates a canvas node
- If a canvas node is grey/no-icon, it is unconnected and the workflow is invalid
- If an edge has a label (route name), it is conditional
- If a node in the execution diagram has a pulsing border, it is currently executing
- If a form field shows a grey placeholder with "inherited" label, the value comes from global defaults and can be overridden by typing

---

## Pass 4: Cognitive Load

**Friction points:**

| Moment | Type | Simplification |
|---|---|---|
| Creating first workflow with no agents yet | Missing prerequisite | Show "No agents found" callout in node palette with "Create your first agent →" CTA |
| Wiring a conditional edge (routing fn, routes, on_traverse) | Choice complexity | Pre-populate route table with common routing pattern (`route_on_critic_decision` → pass/fail_retry/fail_max/default) when fn is selected from dropdown |
| Defining state schema | Complexity | Auto-populate state keys by scanning all agents' `input_keys` and `output_keys`; allow manual additions |
| Entering entry input JSON when triggering a run | Uncertainty | Generate example JSON template from state schema `documents` and other entry keys; show it pre-filled in the trigger modal |
| Understanding agent vs node distinction | Conceptual | First-time tooltip: "Agents are reusable templates in your library. A node is an instance of an agent placed in this workflow." |
| Effective retry configuration | Uncertainty | Node tooltip shows "Effective config: model=gpt-4o-mini (inherited), retries=4 (inherited)" — merging agent config with defaults |
| Tracking which run is which | Choice | Auto-name runs as `{workflow-name}-{YYYY-MM-DD-HH:mm}` |
| Loopback edge direction confusing users | Uncertainty | Label loopback edges as "retry on FAIL_RETRY" with arrow clearly showing direction |
| runtime / observability config complexity | Choice complexity | Hide behind "Advanced" collapsible section in workflow metadata panel; show sensible defaults pre-filled |

**Defaults introduced:**
- `model`: pre-filled from `defaults.model` (`openai/gpt-4o-mini`)
- `temperature`: `0` (shown as inherited)
- `max_tokens`: `16384` (shown as inherited)
- `retry.max_attempts`: `4` (shown as inherited)
- `retry.backoff`: `exponential` (shown as inherited)
- `runtime.checkpointer`: `sqlite`
- `observability.provider`: `none`
- Conditional edge routes: pre-populated with `pass`, `fail_retry`, `fail_max`, `default` keys when `route_on_critic_decision` fn is selected

**Prerequisites surfaced:**
- Agent library empty → surface before Workflow Builder is usable (inline nudge in palette)
- No state schema defined → warn before saving if node input_keys reference undefined state keys
- Entry point not set → highlight missing entry_point before allowing run trigger

---

## Pass 5: State Design

### Screen: Dashboard

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| Loading | Skeleton stat cards (grey animated blocks) | Data is being fetched | Wait |
| Populated | Stat cards with numbers, recent runs list | System health at a glance | Click stat card to navigate to relevant screen |
| No data yet | Stat cards showing 0, empty run list with "No runs yet" | System is set up but unused | Click "Create workflow" CTA |
| Live update | Active run count ticks up/down (polled every 10s) | Runs are changing in real time | Navigate to Runs for detail |

### Screen: Agent Library — List

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| Empty | "No agents yet" with "Create Agent" button | Library is empty | Click to create first agent |
| Loading | Skeleton agent cards | List is loading | Wait |
| Populated | Cards showing agent name, role excerpt, model badge, execution type badge | Available agents at a glance | Click to edit, drag to workflow canvas |
| Agent in use | Card shows "Used in N workflows" badge | Deleting will have impact | Open to view, edit carefully |

### Screen: Agent Editor

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| New (blank) | Form with defaults pre-filled as placeholders, empty required fields | Creating from scratch | Fill in fields, save |
| Editing existing | Form pre-filled with current values, inherited fields show "inherited" badge | Modifying an existing agent | Edit any field, save or cancel |
| Validation error | Inline red error messages under invalid fields | What specifically needs fixing | Fix errors, then save |
| Saving | Save button shows spinner | System is persisting | Wait |
| Saved | Toast notification "Agent saved", return to list | Success | Continue or navigate away |
| Delete confirmation | Modal: "This agent is used in 2 workflows. Delete anyway?" | Impact of deletion | Confirm or cancel |

### Screen: Workflow Builder — Canvas

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| Empty canvas | Blank canvas + hint text "Drag agents from the palette to start" | Need to add nodes | Drag from palette |
| Nodes placed, no edges | Nodes on canvas with no connections, validation warning in toolbar | Workflow is incomplete | Draw edges |
| Invalid edge | Red dashed edge with error icon | Connection is not valid | Fix routing or delete |
| Valid workflow | Green "Valid" indicator in toolbar | Workflow is ready | Save or trigger |
| Unsaved changes | "Save" button shows orange dot indicator | There are unsaved changes | Save or discard |
| Saving | Toolbar save button shows spinner | System is writing YAML | Wait |
| Saved | Toast "Workflow saved" | Persisted | Continue editing or navigate |

### Screen: Workflow Runs — Workflows tab (browse to trigger)

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| Empty | "No workflows defined yet" + "Build a Workflow →" link | Nothing to trigger | Navigate to Workflow Builder |
| Loading | Skeleton workflow cards | List is loading | Wait |
| Populated | Workflow cards (name, description, last triggered date) | Available workflows at a glance | Click to view diagram |
| Workflow selected | Full-size read-only diagram + "Trigger Run ▶" button | Inspecting workflow topology before committing | Study diagram, then trigger |

### Screen: Workflow Runs — Runs tab (history)

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| Empty | "No runs yet — trigger one from the Workflows tab" | Nothing has been executed | Switch to Workflows tab |
| Loading | Skeleton table rows | List is loading | Wait |
| Populated | Rows with status badges (Pending/In Progress/Success/Error) | All runs at a glance | Click to drill in, filter |
| In-progress run | Row with animated spinner badge, elapsed time ticking | A run is active right now | Click to see live execution |
| Error run | Row with red badge | That run failed | Click for error details |

### Screen: Run Trigger Modal

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| Initial | Workflow selected, entry input JSON pre-filled from schema template | What inputs are expected | Edit inputs, submit |
| Validation error | Inline JSON validation error | Input format is wrong | Fix JSON |
| Submitting | "Trigger" button shows spinner | Run is being submitted | Wait |
| Submitted | Modal closes, run appears in list with "Pending" status | Run has been queued | View run in list |

### Screen: Run Detail — Execution Diagram

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| In-progress | Diagram with active node pulsing (blue), completed nodes grey+checkmark, WebSocket live update | Which node is currently executing | Watch, click any completed node |
| Complete | Static diagram, all nodes grey+checkmark (or error node red+X) | Full execution path | Click any node for detail |
| Error | Diagram with one red node, downstream nodes unfilled | Where it failed | Click error node to see error |
| Stale/disconnected | "Last updated X seconds ago" banner, manual refresh button | Live updates may have stopped | Refresh manually |

### Screen: Run Detail — Node Panel

| State | User Sees | User Understands | User Can Do |
|---|---|---|---|
| No node selected | Empty panel with hint "Click a node to inspect" | Panel is waiting for selection | Click a node |
| Node selected (success) | Tabs: Input / Output / Timing / State / Error; Error tab greyed out | Can inspect all execution details | Switch tabs, copy JSON |
| Node selected (error) | Error tab highlighted red, shows error message | Where and why it failed | Read error, check State tab for context |
| Node selected (in-progress) | Input populated, Output tab shows spinner | Node is still executing | Wait for output to appear |

---

## Pass 6: Flow Integrity

**Flow risks:**

| Risk | Where | Mitigation |
|---|---|---|
| User opens Workflow Builder before creating any agents | Workflow Builder | Node palette shows "No agents yet — Create an agent first" with direct link |
| User builds a workflow with nodes referencing deleted agents | Workflow Builder | Validate on open; show broken-reference warning on affected nodes |
| User loses canvas work by navigating away without saving | Workflow Builder | Unsaved changes indicator; browser/navigation "Unsaved changes — leave?" confirmation |
| Entry input format is wrong and run fails immediately | Run trigger modal | Validate entry JSON against state schema before enabling "Trigger" button |
| User can't find the run they just triggered | Runs screen | Newly triggered run jumps to top of list with "New" badge for 30 seconds |
| In-progress run detail falls behind if WebSocket disconnects | Run Detail | Show staleness banner with elapsed-since-update time; manual refresh button |
| Critic retry loops are confusing in diagram | Workflow Builder + Run Detail | Label loopback edges explicitly ("retry: fail_retry"); show retry count badge on node during execution |
| User edits an agent used by multiple workflows | Agent editor | Show "Used in N workflows" warning; changes affect all usages |
| User doesn't know which state keys are available for input_keys | Agent editor | Autocomplete state keys from workflow state schema (or known common keys) |
| Advanced YAML config (runtime/observability/vars) is invisible | Workflow Builder | "Advanced settings" gear icon clearly visible but non-intrusive; badge shows "configured" when non-default values are set |

**Navigation integrity:**
- Happy path (Workflow Engineer): Agents → Create agents → Workflows → Build workflow → Runs → Trigger run → Run Detail → Inspect
- Happy path (KYC Operator): Dashboard → Runs → Trigger run → Run Detail → Inspect
- Can users always navigate back: Yes — persistent left sidebar is always visible; detail panels have explicit close (×) buttons; no dead-end full-page routes
- Cross-screen dependencies:
  - Workflow Builder requires agents to exist → surfaced via palette empty state
  - Run trigger requires a workflow to exist → surfaced via workflow selector empty state
  - Run Detail is only reachable from the Runs screen (not a primary nav item)

**Visibility decisions:**
- Must be visible at all times: Run status (for in-progress runs), unsaved changes indicator, validation errors
- Must be visible in context: Node execution state when in Run Detail diagram, retry count on loopback edges
- Can be implied (progressive disclosure): State schema, runtime config, observability config, variables, advanced agent fields (retry backoff, matching threshold)
- Can be omitted from main flow: YAML export/import (toolbar action, not primary nav), observability tags

**UX constraints:**
- Every UI action must serialize back to valid YAML — no phantom settings
- The canvas must support loopback/cycle edges (critic → source node retry) — standard DAG-only canvas libraries will not work
- Run Detail diagram must support two modes: static (historical) and live (WebSocket-driven); the toggle between modes must be seamless
- Inherited agent defaults must always be visually distinguished from explicit overrides — never show a blank field where a default applies
- Node panel in Run Detail must show the WorkflowState snapshot at that specific node execution point, not the final state
- All config (agents, workflows) must be importable and exportable as YAML files to maintain compatibility with the backend config loader

---

## Visual Specifications

### Screen 1: Dashboard (Mission Control)

**Layout:** Full-width content area with top stat bar and lower split panel.

**Stat bar (top, 4 cards in a row):**
- Card 1: "Workflows Defined" — large number, link to Workflows screen
- Card 2: "Active Runs" — large number with green dot if > 0, animated; link to Runs filtered to In Progress
- Card 3: "Succeeded (7d)" — number + small uptrend sparkline; green text
- Card 4: "Errors (7d)" — number; red text if > 0, grey if 0

**Lower section (two columns):**
- Left (60%): "Recent Runs" table — columns: Workflow name, Status badge, Started (relative time), Duration. Capped at 10 rows. "View all →" link.
- Right (40%): "7-Day Activity" bar chart — one bar per day, stacked success/error. Minimal, no axes labels beyond day abbreviations.

**Refresh:** Stat cards and recent runs auto-refresh every 10 seconds (silent, no loading flash).

---

### Screen 2: Agent Library

**Layout:** Two-panel — left panel (agent list, 320px fixed), right panel (agent editor, remainder).

**Left panel:**
- Header: "Agents" + "New Agent" button (top-right of panel)
- Agent cards (list): Name (bold), role (1-line excerpt, truncated), model badge (provider/model-name pill), execution type badge (LLM | Rule)
- Active/selected card highlighted
- Search input at top of list

**Right panel — Agent Editor:**
Grouped sections with section headers and collapse affordance:

- **Identity** (always open)
  - Role (single-line text)
  - Goal (single-line text)
  - Backstory (textarea, 5 rows)

- **Execution** (always open)
  - Execution type: toggle tabs `LLM` / `Rule`
    - LLM mode: Model (dropdown + freetext), Temperature (slider 0–1 with value readout), Max tokens (number)
    - Rule mode: Rule function (dotted path text input)
  - Fields inherited from defaults show "Using default: X" grey placeholder; user can click to override

- **Retry** (collapsed by default, "Retry config" section header)
  - Max attempts, Backoff (dropdown), Delay seconds
  - Shows "All inherited from defaults" badge when not overridden

- **Prompt** (shown only when Execution = LLM)
  - Mode toggle: `Inline` / `File`
  - Inline: code textarea with monospace font, syntax hint
  - File: text input for relative file path

- **I/O Keys** (always open)
  - Input keys: tag/chip input (comma-separated, autocomplete from state schema)
  - Output key: single-line text
  - Retry count key: single-line text
  - Matching threshold: slider 0–1 (shown only when execution=rule and agent context requires it — e.g. reconciler pattern)

- **Output Schema** (collapsed by default)
  - Mode toggle: `Pydantic ref` / `Example JSON`
  - Pydantic ref: dotted class path + is_list toggle
  - Example JSON: JSON code editor

**Footer actions:** `Save` (primary), `Cancel`, `Delete` (destructive, right-aligned, shown only for existing agents)

---

### Screen 3: Workflow Builder

**Layout:** Left sidebar (nav), full-height canvas area, left inner panel (node palette, 240px), right inner panel (properties, 320px, slides in on selection).

**Canvas toolbar (top bar above canvas):**
- Left: Workflow name (editable inline), workflow status chip (Unsaved / Saved / Invalid)
- Right: `Validate`, `Import YAML`, `Export YAML`, `Settings ⚙` (opens metadata/advanced panel), `Save` (primary button with orange dot when unsaved), `Trigger Run ▶` (secondary button)

**Node palette (left inner panel):**
- Header: "Agents" + search input
- Agent cards: name, role excerpt, grab icon. Drag to canvas to create node.
- Empty state: "No agents yet — [Create an agent]" (link to Agent Library)
- Special built-in nodes at bottom: `__start__` (entry sentinel), `end`

**Canvas:**
- Infinite canvas with zoom/pan (scroll to zoom, drag canvas to pan)
- Node cards: Agent name (bold), role (small, truncated), execution type badge (LLM/Rule), node ID (small, grey)
- Port handles: appear as small circles on node edges when node is hovered
- Edges: solid lines for unconditional; dashed lines for conditional; loopback edges rendered as curved arcs
- Conditional edge labels: route names shown inline on the edge (e.g. "fail_retry", "pass")
- Selected node: blue ring
- Invalid node (broken agent reference): red ring + warning icon

**Properties panel (right, slides in):**

*Node selected:*
- Node ID (editable)
- Node type (dropdown: agent / parallel / merger / human / subgraph / end)
- Agent (dropdown from library, with "Open agent ↗" link)

*Edge selected:*
- Edge type toggle: `Direct` / `Conditional`
- Conditional section (shown when Conditional):
  - Routing function (dropdown of known fns + "Custom…" option for free text)
  - Routes table: rows of (route string) → (node dropdown) — add/remove rows
  - on_traverse section (collapsible):
    - When route (text input)
    - Increment key (text input, autocomplete state keys)

**Metadata/Advanced panel (opened via Settings icon):**
Slides over canvas as a side drawer:
- Tabs: `General` | `State Schema` | `Runtime` | `Observability` | `Variables`
- General: name, description, ID, entry_point, max_steps, timeout_seconds
- State Schema: table editor (key, type, default) + "Auto-populate from agents" button
- Runtime: checkpointer dropdown, checkpointer URI
- Observability: provider dropdown, project, tags, trace toggles
- Variables: key-value table with `${ENV_VAR}` hint

---

### Screen 4: Workflow Runs

**Layout:** Left sidebar (nav), main area with two tabs: `Workflows` and `Runs`.

---

**Tab: Workflows** (default landing tab — browse and trigger)

This tab lets the user inspect a workflow's diagram before committing to a run.

*Left sub-panel (workflow list, 280px fixed):*
- Workflow cards: name (bold), description (1-line truncated), "Last run: X ago" or "Never triggered"
- Active selection highlighted
- Empty state: "No workflows defined yet — [Build a Workflow →]" link to Workflow Builder

*Right sub-panel (workflow diagram view, remainder):*
- Full-size **read-only canvas** (n8n-style) rendering the selected workflow's topology
- Identical visual language to the Workflow Builder canvas: node cards, labeled edges, loopback arcs, conditional route labels
- Canvas is **not interactive** (no drag, no click-to-configure) — this is view-only
- Header above canvas: workflow name, description, node count, last modified date
- Prominent **`Trigger Run ▶`** button in the top-right of this panel (always in view)
- Empty state (no workflow selected): "Select a workflow on the left to preview its diagram"

*Flow: user selects workflow → diagram appears → user studies it → clicks "Trigger Run ▶" → Trigger Run Modal opens*

**Trigger Run Modal** (opens from the `Trigger Run ▶` button on the diagram view):
- Header: "Trigger: {Workflow Name}"
- Entry inputs section: JSON editor pre-populated with state schema template
  - Validation: JSON schema check against state definition before enabling "Trigger" button
  - Helper text: "Provide the initial documents and workflow_id at minimum"
- Note: no workflow selector here — the workflow is already chosen from the list
- Actions: `Trigger ▶` (primary), `Cancel`

---

**Tab: Runs** (execution history)

*Top action bar:*
- Left: "Run History" label
- Filter bar: Status (All / Pending / In Progress / Success / Error), Workflow (dropdown), Date range (last 24h / 7d / 30d / custom)

*Runs table:*
Columns: Run ID (truncated, monospace), Workflow (name), Status (badge), Started (relative time + absolute on hover), Duration, Entry snapshot (collapsed JSON, hover to expand)

Each row is clickable → opens Run Detail.

In-progress rows: status badge has spinner animation; duration column shows elapsed time, ticking.

Newly triggered run: jumps to top of list with "New" badge for 30 seconds after triggering.

---

### Screen 5: Run Detail (Execution Monitor)

**Layout:** Top header bar, main split: left diagram (60%), right detail panel (40%), bottom timeline (collapsible, ~180px).

**Top header bar:**
- Workflow name + Run ID
- Status badge (with spinner if in-progress)
- Started time, Duration (ticking if in-progress)
- `← Back to Runs` link

**Left: Execution Diagram**
Read-only canvas rendering the workflow definition, overlaid with execution state:

Node states:
- Not yet reached: grey fill, no overlay icon
- In progress (current node): blue fill, pulsing animated border ring
- Completed successfully: grey fill + green checkmark icon (top-right)
- Error: red fill + red X icon
- Retry loop active: loopback edge shows animated dashes (CSS animation), retry count badge on edge label (e.g. "retry × 2")

Live mode (in-progress run): WebSocket drives updates. If disconnected, show banner: "Live updates paused — last seen {N}s ago [Refresh]"

Click any node → opens right detail panel for that node.

**Right: Node Detail Panel**
Shows after clicking a node. Header: node name + agent name + execution status badge.

Tabs:
- **Input**: formatted JSON of the state keys this agent read (from `input_keys` config). Keys highlighted with their names.
- **Output**: formatted JSON of the agent's `output_key` value. "Pending…" spinner if node in progress.
- **Timing**: Start time, End time, Duration. Retry attempt number (e.g. "Attempt 2 of 4").
- **State**: full WorkflowState snapshot at the moment this node completed. Scrollable JSON tree. Highlight changed keys (diff from previous node state).
- **Error**: shown only if node failed. Error message (large, red). Stack trace (collapsible). Critic feedback if applicable.

Empty state (no node selected): "Click any node in the diagram to inspect its execution details."

**Bottom: Timeline**
Collapsible horizontal bar (toggle arrow in bottom-right corner).
Shows all node executions as horizontal spans in chronological order.
Each span: node name label, color-coded by status (grey/green/red/blue for in-progress).
Spans show actual wall-clock timing proportional to duration.
Hover over span → tooltip with start/end/duration.
Click span → selects that node and opens detail panel (same as clicking canvas node).
Retry attempts shown as repeated spans on the same row with lighter fill.
