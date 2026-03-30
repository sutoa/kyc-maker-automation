# Stitch Prompt Package: KYC Workflow Automation UI

Generated from UX spec. Use one prompt per Stitch generation run.
Apply your saved style to all screens. Generate screens in order — Dashboard first to validate style with data-heavy content.

---

## Shared Context (include in every prompt)

> This is a professional internal tool for KYC workflow engineers and operators. The app has a persistent left sidebar navigation with 5 items: Dashboard, Agents, Workflows, Runs, Settings. The active nav item is highlighted. The sidebar is always visible across all screens.

---

## Screen 1: Dashboard (Mission Control)

### State to render: Populated (nominal operating state)

**Prompt:**

Design the Dashboard screen for a KYC workflow automation tool. Persistent left sidebar navigation (Dashboard selected/active, plus Agents, Workflows, Runs, Settings). Full-width main content area.

**Top section — 4 stat cards in a horizontal row:**
- "Workflows Defined" — large bold number (e.g. 3), subtitle "total defined", clickable card
- "Active Runs" — large bold number (e.g. 2) with a small animated green dot indicator, subtitle "running now", clickable card
- "Succeeded (7d)" — large bold number (e.g. 47) with a small upward sparkline chart to the right, green-tinted number, subtitle "last 7 days"
- "Errors (7d)" — large bold number (e.g. 3), red-tinted number, subtitle "last 7 days"

**Lower section — two columns:**
- Left column (60% width): "Recent Runs" table with columns: Workflow name, Status badge (color-coded: green=Success, blue=In Progress, red=Error, grey=Pending), Started (relative time like "2m ago"), Duration. Show 6–8 rows of sample data including a mix of statuses. "View all →" link below the table.
- Right column (40% width): "7-Day Activity" minimal bar chart. 7 bars (Mon–Sun), each bar stacked with two segments: success (green) and error (red). Keep it minimal — no grid lines, just day labels below bars.

**Key constraint:** The stat cards must look clickable/interactive (hover state implied). Status badges must be immediately readable at a glance.

---

## Screen 2: Agent Library — List View

### State to render: Populated (several agents configured)

**Prompt:**

Design the Agent Library screen for a KYC workflow automation tool. Persistent left sidebar (Agents selected). Two-panel layout.

**Left panel (fixed ~320px width):**
- Panel header: "Agents" title + "New Agent" button (top-right of panel, primary)
- Search input at the top of the list
- List of agent cards. Each card shows:
  - Agent name (bold, e.g. "extractor", "critic_1", "reconciler")
  - Role text (1-line truncated, e.g. "KYC Document Extraction Specialist")
  - Two small badges: model badge (e.g. "gpt-4o-mini") and execution type badge (either "LLM" in blue or "Rule" in orange)
- One card is selected/highlighted (e.g. "extractor")
- Show 5–6 agent cards in the list

**Right panel (remainder of screen — agent editor for selected agent):**
Scrollable form with grouped sections, each with a section header and collapse toggle:

- **Identity** section (expanded):
  - Role field (single-line text input, filled: "KYC Document Extraction Specialist")
  - Goal field (single-line text input, filled: "Extract all person records from KYC documents")
  - Backstory field (multiline textarea, 4 rows, filled with example text)

- **Execution** section (expanded):
  - Toggle tabs: "LLM" (active) / "Rule"
  - Model field: dropdown showing "openai/gpt-4o-mini" with a small grey "inherited" badge next to it
  - Temperature: slider at 0.0 position, showing value "0" — small grey "inherited" badge
  - Max tokens: number input showing "16384" — small grey "inherited" badge

- **Retry** section (collapsed, shows "All inherited from defaults" badge inline):
  - Just show the section header with collapse arrow and the inherited badge

- **Prompt** section (expanded, LLM mode):
  - Toggle: "Inline" / "File" (File selected)
  - File path text input showing: "../prompts/extractor.md"

- **I/O Keys** section (expanded):
  - Input keys: chip/tag inputs showing "documents" and "extraction_feedback" as chips
  - Output key: text input showing "extracted_persons"
  - Retry count key: text input showing "extraction_retry_count"

**Footer (sticky at bottom of right panel):** "Save" button (primary), "Cancel" button, "Delete" button (destructive, right-aligned)

**Key constraints:**
- The "inherited" badge is critical — it must be visually distinct (grey/muted) from fields with user-set values (which show no badge)
- The section collapse/expand pattern must be clear — show collapsed sections as just a header bar with a chevron
- The left panel card selection must be clearly highlighted

---

## Screen 2b: Agent Library — Empty State

### State to render: Empty (no agents yet)

**Prompt:**

Design the Agent Library empty state screen. Same two-panel layout as the populated state, but:
- Left panel shows: no cards, just the "Agents" header + "New Agent" button, and an empty state message in the center of the panel: "No agents yet" with a subtle icon (e.g. robot or puzzle piece) and a "Create your first agent →" CTA button
- Right panel: empty, shows placeholder text "Select an agent to edit, or create a new one"

---

## Screen 3: Workflow Builder — Populated Canvas

### State to render: Valid workflow with nodes and edges placed

**Prompt:**

Design the Workflow Builder screen for a KYC workflow automation tool. Persistent left sidebar (Workflows selected). Full-height canvas layout.

**Canvas toolbar (top bar spanning full width above canvas):**
- Left side: workflow name "KYC Document Processing" (editable inline, looks like a text input in edit mode), status chip showing "Saved" (green/subtle)
- Right side (button group): "Validate" button, "Import YAML" button, "Export YAML" button, Settings gear icon button, "Save" primary button, "Trigger Run ▶" secondary button

**Left inner panel (~240px, node palette):**
- Header: "Agents" + small search input
- List of draggable agent cards (smaller than the Agent Library cards): name + grab handle icon on left. Show: extractor, critic_1, reconciler, critic_2, classifier, critic_3, formatter
- At the bottom of the palette, two special built-in nodes with a separator: "__start__" and "end" (styled differently — outlined/ghost style)

**Canvas (main area, infinite scroll):**
Show the KYC workflow with these nodes arranged in a logical top-to-bottom flow:

Nodes (each is a card with): agent name (bold), role subtitle (small, truncated), "LLM" or "Rule" badge
- `__start__` (entry node, special styling — e.g. rounded pill or hexagon)
- `extractor` (LLM)
- `critic_1` (LLM)
- `reconciler` (LLM)
- `critic_2` (Rule)
- `classifier` (LLM)
- `critic_3` (Rule)
- `formatter` (LLM)
- `end` (terminal node, special styling)

Edges:
- Solid straight arrows: __start__ → extractor → critic_1, reconciler → critic_2, classifier → critic_3, formatter → end
- Conditional edges (dashed lines) from critic_1, critic_2, critic_3 with route labels:
  - critic_1 → reconciler (label: "pass"), critic_1 → extractor (label: "fail_retry", this is a LOOPBACK — curved arc going back up), critic_1 → end (label: "fail_max")
  - Same pattern for critic_2 → classifier/reconciler/end and critic_3 → formatter/classifier/end
- The loopback edges (fail_retry) are curved arcs that bend around the left side of the nodes — NOT straight lines that would overlap

**Right properties panel (320px, slides in — show it open for the critic_1 node selected):**
- Node selected header: "critic_1"
- Node ID field: "critic_1"
- Node type dropdown: "agent"
- Agent dropdown: "critic_1" with "Open agent ↗" link

**Key constraints:**
- Loopback/cycle edges are REQUIRED — curved arcs going backward in the flow, not overlapping with forward edges
- Conditional edges must be visually distinct from unconditional (dashed vs solid)
- Route labels ("pass", "fail_retry", "fail_max") must be readable inline on the edges
- The canvas must look zoomable/pannable — show zoom controls (+ / - / fit) in a corner

---

## Screen 3b: Workflow Builder — Empty Canvas

### State to render: Empty (no nodes placed yet)

**Prompt:**

Design the Workflow Builder empty canvas state. Same layout as the populated state, but:
- Canvas area is empty with a subtle centered hint: ghost/dashed rectangle with text "Drag an agent from the palette to start building your workflow"
- The node palette on the left is visible with agents listed
- Toolbar shows "Unsaved" status chip (orange/amber tint)
- No properties panel (nothing selected)

---

## Screen 4: Workflow Runs — Workflows Tab (Browse + Diagram)

### State to render: Workflow selected, diagram preview visible

**Prompt:**

Design the Workflow Runs screen, "Workflows" tab, for a KYC workflow automation tool. Persistent left sidebar (Runs selected). Two-tab layout at top: "Workflows" (active) and "Runs".

**Left sub-panel (~280px fixed):**
- Header: "Workflows"
- List of workflow cards. Each card shows:
  - Workflow name (bold, e.g. "KYC Document Processing")
  - Description (1-line truncated, e.g. "Multi-agent KYC extraction and classification")
  - "Last run: 2 hours ago" or "Never triggered" (muted text)
- One card is selected/highlighted ("KYC Document Processing")
- Show 2–3 workflow cards

**Right panel (remainder — read-only workflow diagram):**
- Header bar above the diagram: workflow name "KYC Document Processing", description, "7 nodes", "Last modified: today" — all in small muted text
- Prominent **"Trigger Run ▶"** button in the top-right corner of this panel (always visible, primary)
- Canvas area showing the same workflow diagram as Screen 3 (same nodes and edges), but:
  - Read-only — no palette, no selection rings, no properties panel
  - All nodes rendered in a neutral/static style (no edit affordances)
  - Loopback edges still visible with route labels
  - Canvas has fit-to-screen zoom (not scrollable in this view)
- The diagram fills the available space

**Key constraint:** The "Trigger Run ▶" button must be prominent and always in view — it's the primary CTA of this screen. The diagram is for inspection only; nothing in it is clickable.

---

## Screen 4b: Trigger Run Modal

### State to render: Modal open, pre-filled with template

**Prompt:**

Design the Trigger Run modal overlay for the KYC workflow automation tool. Show the modal on top of the blurred/dimmed Workflow Runs screen.

**Modal:**
- Header: "Trigger Run" title + workflow name subtitle "KYC Document Processing"
- Close (×) button top-right
- Body:
  - Section label: "Entry Inputs"
  - Helper text: "Provide the initial documents and workflow_id at minimum"
  - A JSON code editor (monospace font, syntax-highlighted, dark background) pre-filled with a template like:
    ```json
    {
      "workflow_id": "run-001",
      "documents": [
        {
          "filename": "kyc_document.pdf",
          "content": ""
        }
      ]
    }
    ```
  - The JSON editor has line numbers on the left
- Footer: "Trigger ▶" button (primary, full-width or right-aligned), "Cancel" text button

---

## Screen 4c: Workflow Runs — Runs Tab (History)

### State to render: Populated with mixed statuses

**Prompt:**

Design the Workflow Runs screen, "Runs" tab. Persistent left sidebar (Runs selected). Two-tab layout: "Workflows" and "Runs" (active).

**Top filter bar:**
- "Run History" label (left)
- Filter dropdowns (right): Status (showing "All"), Workflow (showing "All"), Date range (showing "Last 7 days")

**Runs table:**
Columns: Run ID (monospace, truncated e.g. "run-2024-03-..."), Workflow, Status, Started, Duration

Show 8 rows with mixed statuses:
- 1 row: In Progress — animated spinner badge (blue), duration showing ticking elapsed time "1m 23s"
- 3 rows: Success — green badge, durations like "2m 14s", "3m 05s", "1m 48s"
- 1 row: Error — red badge, duration "0m 47s"
- 2 rows: Success
- 1 row: Pending — grey badge, "just now"

The in-progress row is subtly highlighted (very light background tint).
The top row (newest) has a small "New" badge/pill next to the Run ID.
Each row has a subtle hover state and looks clickable (cursor: pointer implied).

**Key constraint:** Status badges must be immediately scannable — this is a monitoring screen. The in-progress row should draw the eye.

---

## Screen 5: Run Detail — In-Progress Execution

### State to render: Run in progress, node selected

**Prompt:**

Design the Run Detail screen for a KYC workflow automation tool. Persistent left sidebar (Runs selected, but muted since this is a sub-page).

**Top header bar (full width):**
- Left: "← Back to Runs" link, then "KYC Document Processing" workflow name, then run ID "run-2024-03-29-14:32" (monospace, muted)
- Center/right: "In Progress" status badge with spinner, "Started: 2 min ago", "Duration: 2m 14s" (ticking)

**Main area — split layout:**

*Left side (60% width) — Execution diagram:*
- Read-only canvas showing the same workflow (same nodes as Screen 3)
- Node execution states overlaid:
  - `__start__`: completed (grey + green checkmark)
  - `extractor`: completed (grey + green checkmark)
  - `critic_1`: completed (grey + green checkmark)
  - `reconciler`: **currently executing** — blue fill, pulsing animated border ring (show as glowing/highlighted)
  - `critic_2`, `classifier`, `critic_3`, `formatter`, `end`: not yet reached (grey, no icon, muted/faded)
- Loopback edges still visible but inactive (static, no animation)
- Small zoom controls in corner
- Staleness banner NOT shown (connection is live)

*Right side (40% width) — Node detail panel:*
- Show the panel for `reconciler` (the active node)
- Panel header: "reconciler" (node name, bold), "Person Record Reconciliation Specialist" (agent name, muted), "In Progress" badge (blue)
- Tabs: Input | Output | Timing | State | Error
- **Input tab** (active): formatted JSON showing reconciler's input state keys:
  ```json
  {
    "extracted_persons": [...],
    "reconciliation_feedback": null
  }
  ```
  Keys are labeled/highlighted
- Output tab: shows a spinner + "Waiting for output…" placeholder

**Bottom timeline (expanded, ~180px):**
Horizontal strip showing execution spans:
- `__start__`: short grey span (completed)
- `extractor`: medium green span (completed, ~30s)
- `critic_1`: short green span (completed, ~10s)
- `reconciler`: blue span that is still growing (in progress, truncated at right edge with an animated pulse)
- Remaining nodes: no spans yet (empty space)
- Each span has node name label below it
- A thin vertical "now" line at the current time position

**Key constraints:**
- The active node (`reconciler`) must visually dominate — it's the most important piece of information
- The timeline must clearly show progression through the workflow
- The split between diagram and detail panel should feel like Langfuse's trace view

---

## Screen 5b: Run Detail — Error State

### State to render: Run completed with error at critic_1

**Prompt:**

Design the Run Detail screen showing a completed-with-error run. Same layout as Screen 5 but:

**Header:** "Error" status badge (red, no spinner). Duration: "0m 47s".

**Execution diagram node states:**
- `__start__`: completed (grey + green checkmark)
- `extractor`: completed (grey + green checkmark)
- `critic_1`: **error** — red fill + red X icon, slightly larger/more prominent
- All other nodes: not reached (grey, faded)
- The loopback edge from critic_1 back to extractor shows a badge: "retry × 4" (indicating max retries were exhausted)

**Right detail panel — critic_1 selected, Error tab active:**
- Panel header: "critic_1", "Extraction Quality Auditor", "Error" badge (red)
- Tabs: Input | Output | Timing | State | Error (Error tab is active, highlighted red)
- Error tab content:
  - Large red error message: "Max retries exceeded: extraction failed validation after 4 attempts"
  - Critic feedback section (collapsible, expanded): shows the last critic feedback text
  - Stack trace (collapsible, collapsed): "Show stack trace ▼"

**Timeline:** Shows extractor span (with a lighter repeated span for retry × 3 alongside it), critic_1 spans (3 short spans for retry evaluations), then stops. Red tint on the critic_1 spans.

---

## Shared Component Notes (apply to all screens)

These components appear across multiple screens — keep them visually consistent:

**Status badges:**
- Success: green background, "Success" or "✓"
- In Progress: blue background, spinner icon, "In Progress"
- Error: red background, "Error" or "✗"
- Pending: grey/muted, "Pending"
- New: amber/yellow pill, "New"

**Left sidebar navigation:**
- 5 items: Dashboard, Agents, Workflows, Runs, Settings
- Active item: highlighted (accent color background or left border indicator)
- Icons + labels for each item
- App name/logo at top of sidebar
- Sidebar is fixed, never collapses in this design

**Inherited badge (Agent Editor only):**
- Small grey pill with text "inherited" next to a form field
- Signals the value comes from global defaults and hasn't been overridden
- When a user overrides a field, the badge disappears

**Node cards (canvas):**
- Consistent card style across Workflow Builder, Workflow Runs diagram preview, and Run Detail diagram
- The only difference is execution state overlays in Run Detail
