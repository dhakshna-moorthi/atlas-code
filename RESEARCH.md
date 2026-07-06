# Atlas Code — Architecture Research & Analysis

Research conducted before the July 2026 overhaul. This document covers the five mandated
research topics, then the Phase 2 architecture decision that drives the implementation.

**Current architecture recap** (from reading every file in this repo):

```
┌──────────────────────────────  user's machine  ─────────────────────────────┐
│  VS Code webview (media/)  ⇄  extension host (src/panel.ts)                 │
│                                    │            ▲                            │
│                                    │ HTTP POST  │ spawns per tool call       │
│                                    ▼            │                            │
│                              agent/agent.py (stdin JSON → stdout JSON)      │
└──────────────────────────────────│──────────────────────────────────────────┘
                                   ▼
                     FastAPI server on Render (server.py)
                     — owns SYSTEM_PROMPT, TOOLS, OpenAI calls
                     — returns either {status:"done"} or {status:"tool_call"}
```

The agentic loop is **driven by the extension** (the `while(true)` in `panel.ts`), but each
iteration's *decision* is made remotely by `server.py` calling OpenAI. Tool execution is
local (spawned Python). Full message state is round-tripped through the client on every
step (`messages` array in the response body). `agent/tools.py` is dead code — it duplicates
both the schemas and the executors but is imported by nothing; `agent/agent.py` is what the
extension actually spawns.

---

## 1. MCP (Model Context Protocol)

### What it is

MCP is an open standard (originated by Anthropic, late 2024; now industry-wide) that
standardizes how AI applications connect to tools and data. It uses **JSON-RPC 2.0** over
two transports: **stdio** (local child process, the default for local servers) and
**Streamable HTTP** (which replaced the legacy SSE transport in the Nov 2025 spec) for
remote servers.

Roles in MCP:

- **Host** — the application that owns the conversation with the LLM (Claude Desktop,
  VS Code Copilot agent mode, Cursor, Claude Code).
- **Client** — a connector object *inside the host*, one per server, holding a stateful
  JSON-RPC session.
- **Server** — a process exposing three primitives:
  - **Tools** — model-invoked functions with JSON Schema input definitions (near-identical
    in shape to OpenAI function-calling schemas);
  - **Resources** — read-only, URI-addressed data the *application* (not the model) fetches
    and injects into context;
  - **Prompts** — user-invokable prompt templates.

### How VS Code extensions integrate with MCP

VS Code implements the full MCP spec, but the integration point is **Copilot / the built-in
agent mode**, not arbitrary webview extensions. An extension can:

1. Ship an MCP server and register it via the `mcpServerDefinitionProviders` contribution
   point — the tools then appear in *Copilot's* agent mode.
2. Contribute Language Model Tools via `vscode.lm.registerTool` — again surfaced to
   Copilot, not to a custom chat UI.
3. Act as its own MCP **host**: embed an MCP client (official `@modelcontextprotocol/sdk`
   for TypeScript), spawn a server over stdio, do `tools/list` and `tools/call` itself, and
   bridge the tool schemas into whatever LLM API it uses.

Only option 3 is relevant to Atlas, because Atlas has its own chat UI and its own model
backend. Options 1–2 would donate Atlas's tools to Copilot rather than improve Atlas.

### MCP tool definitions vs raw OpenAI function calling

| | OpenAI function calling | MCP |
|---|---|---|
| Schema | `{type:"function", function:{name, description, parameters}}` | `{name, description, inputSchema}` — same JSON Schema core |
| Coupling | Request-scoped; tools sent with every API call | Stateful session; tools discovered via `tools/list`, can change at runtime (`listChanged` notifications) |
| Who executes | Your own dispatch code | The server process, behind a protocol boundary |
| Portability | Tied to the provider's API shape | Any MCP host can use the server unchanged |
| Extra machinery | None | SDK dependency, transport lifecycle, session management, consent UX |

The two are complementary, not competing: a common production pattern is to keep
provider function calling as the *model-facing* interface and use MCP servers as the
*execution* layer, translating schemas between the two.

### Does MCP fit Atlas's current setup?

This is the crux, and the answer is driven by **topology**: an MCP client must live in the
same process/machine context as whatever drives the LLM loop *and* must be able to reach the
server. In Atlas:

- The component that talks to the LLM is `server.py` — **remote, on Render**.
- The tools operate on the **user's local filesystem**.

A remote FastAPI process cannot connect to a stdio MCP server on the user's laptop. To
adopt MCP "properly" you must first **move the agentic loop into the extension host**, at
which point the extension becomes the MCP host, the local Python agent becomes a local
stdio MCP server, and `server.py` shrinks to a thin authenticated LLM proxy (it exists to
keep the OpenAI key off user machines, which is a legitimate reason for it to survive).
That is a real architectural inversion, not a drop-in change. Full analysis in Phase 2
below.

Sources: [VS Code MCP developer guide](https://code.visualstudio.com/api/extension-guides/ai/mcp),
[VS Code MCP server management](https://code.visualstudio.com/docs/agent-customization/mcp-servers),
[Ken Muse — Adding an MCP server to a VS Code extension](https://www.kenmuse.com/blog/adding-mcp-server-to-vs-code-extension/),
[Ken Muse — Beyond MCP: AI extension APIs](https://www.kenmuse.com/blog/beyond-mcp-vs-code-ai-extension-apis/),
[MCP vs function calling (Descope)](https://www.descope.com/blog/post/mcp-vs-function-calling),
[MCP vs function calling — how they work together (Portkey)](https://portkey.ai/blog/mcp-vs-function-calling/),
[Prefect — when to use which](https://www.prefect.io/resources/mcp-vs-function-calling).

---

## 2. Tool sets of production coding agents

Survey of what Claude Code, Cline, Aider, and Cursor actually ship:

### Claude Code
`Read` (line-numbered, offset/limit for big files), `Write`, `Edit` (exact string
replacement — *not* line numbers), `Glob` (find files by name pattern), `Grep` (ripgrep
content search with regex, globs, context lines), `Bash` (persistent shell; git, tests,
builds), `Agent` (sub-agents for fan-out search), plus web fetch/search and task tools.
Notable: **no dedicated mkdir/mv/rm tools — shell covers them**; edits are
string-anchored rather than line-anchored, which is far more robust against stale line
numbers.

### Cline
`read_file`, `write_to_file` (create-or-overwrite, mkdir -p implied), `replace_in_file`
(SEARCH/REPLACE diff blocks), `execute_command` (with user approval gating),
`search_files` (regex + file pattern), `list_files` (recursive option),
`list_code_definition_names` (symbol-level overview via tree-sitter),
`ask_followup_question`, `attempt_completion`, `browser_action`, plus MCP passthrough
(`use_mcp_tool`). Notable: a dedicated tool for **asking the user questions** and one for
**declaring completion** — the schema itself encodes conversation control.

### Aider
No free-form tool loop at all — it builds a **repo map** (tree-sitter symbol graph ranked
by PageRank) to pick context, then applies model output as SEARCH/REPLACE or unified-diff
edit blocks. Deeply **git-native**: auto-commits every change, `/undo` reverts, dirty-state
checks before edits. The lesson: version-control awareness and symbol-level maps matter as
much as raw file tools.

### Cursor
Agent mode tools: codebase semantic search (embeddings), grep, file read/write/edit,
terminal command execution (with approval), lints-after-edit feedback, and `@`-mention
context injection (see §4).

### Gap analysis vs Atlas's current 9 tools

Atlas has: `get_file_tree`, `list_files`, `read_file`, `read_lines`, `search_files`
(substring only), `replace_lines`, `write_file`, `create_file`, `delete_file`.

Missing, in rough order of value:

| Tool | Who has it | Verdict for Atlas |
|---|---|---|
| `create_directory` | Cline (implicit), shell elsewhere | **Add** — currently the agent can only create dirs as a side effect of `create_file` |
| `rename_file` / move | shell elsewhere, all IDE agents via mv | **Add** — refactors constantly need renames; today the agent must read+create+delete (3 calls, loses history) |
| `get_file_info` | stat via shell | **Add** — lets the agent size up a file before choosing `read_file` vs `read_lines` |
| `find_files` (glob by name) | Claude Code `Glob`, Cline `list_files` recursive | **Add** — `search_files` only matches *content*; "where is config.yaml?" currently requires walking the tree output |
| `execute_command` (shell) | all four | **Defer** — highest value (tests, installs, git) but requires a user-approval UI and sandboxing story; running remote-LLM-chosen shell commands with zero consent gating is not acceptable. Needs its own design pass. |
| git tools (diff/commit/log) | Aider (core), others via shell | **Defer** — same consent story as shell; subset of `execute_command` |
| symbol search / code map | Cline, Aider, Cursor | **Defer** — needs tree-sitter or LSP; large dependency for a later milestone |
| string-anchored edit (search/replace) | Claude Code, Cline, Aider | **Worth noting**: `replace_lines` is fragile because line numbers go stale after any prior edit in the same turn. Mitigated in the system prompt (re-read before editing); a diff-based edit tool is the right long-term fix. |

Sources: [Claude Code tools reference](https://code.claude.com/docs/en/tools-reference),
[Claude Code built-in tools explained](https://israynotarray.com/en/ai/2026/04/29/claude-code-built-in-tools-explained/),
[Cline tools guide](https://docs.cline.bot/exploring-clines-tools/cline-tools-guide),
[Cline system prompt (annotated)](https://harrywang.github.io/cline).

---

## 3. System prompt patterns for coding agents

Findings from published prompts (Cline's is Apache-2.0 and fully public; Claude Code's has
been extracted and mirrored) and prompt-engineering literature:

**Structure that the best prompts share:**

1. **Identity + capability statement** — one tight paragraph, not marketing copy.
2. **Environment block** — OS, workspace root, what the agent *cannot* do (Cline lists cwd,
   OS, shell explicitly; grounding in real paths measurably reduces hallucinated paths).
3. **Tool-use protocol** — *when to prefer which tool*, stated as rules with reasons
   ("prefer X over Y because Z"). Cline devotes the largest share of its prompt to
   per-tool guidance and explicitly contrasts `write_to_file` vs `replace_in_file`.
4. **Plan vs act separation** — Cline ships literal PLAN/ACT modes; Claude Code has plan
   mode. Where modes aren't a product feature, the prompt encodes the same idea as a rule:
   *investigate before mutating; state intent in one sentence before the first write*.
5. **Ask vs proceed policy** — the modern consensus is "bias to act on clear, reversible
   tasks; ask one focused question when the task is ambiguous or destructive." Cline's
   `ask_followup_question` tool description embeds this policy.
6. **Workflows as numbered procedures** — debugging, feature work, and refactoring get
   step-by-step recipes (locate → read → understand root cause → minimal fix → verify).
   Numbered steps outperform prose paragraphs for procedure adherence.
7. **Convention respect** — "mimic existing code style, use existing libraries, check
   neighbors before creating files" (near-verbatim in Claude Code's prompt: *never assume
   a library is available; look at imports first*).
8. **Communication contract** — before/during/after phrasing rules; Claude Code pushes
   hard toward brevity ("answer in 1–3 sentences, no pre/postamble").
9. **Error recovery** — treat a failed tool call as information: read the error, adjust
   the approach, retry differently at most once or twice, then surface the failure
   honestly rather than looping. Research on agentic frameworks (SHIELDA, AdaCoder)
   confirms explicit error-feedback loops beat silent retries.

**Anti-patterns to avoid:** vague exhortations ("be careful"), rules without rationales
(models generalize better when told *why*), burying tool-choice rules inside tool
descriptions only (state global preference ordering in the prompt body too), and
prompts that never say what to do when things fail.

Sources: [Cline system prompt, annotated](https://harrywang.github.io/cline),
[Cline blog — System Prompt Fundamentals](https://cline.bot/blog/system-prompt),
[Cline blog — System Prompt Advanced](https://cline.ghost.io/system-prompt-advanced/),
[Claude Code tools & prompt extraction](https://gist.github.com/wong2/e0f34aac66caf890a332f7b6f9e2ba8f),
[SHIELDA — structured exception handling in LLM agentic workflows](https://arxiv.org/pdf/2508.07935),
[AdaCoder — adaptive planning for code generation](https://arxiv.org/pdf/2504.04220).

---

## 4. The `@` file-reference pattern

**UX (as implemented by Cursor, Copilot Chat, Cline):**

1. User types `@` in the chat input → a filterable popup lists referenceable items
   (files first; Cursor also offers @Folders, @Code, @Docs, @Git, @Web).
2. Continued typing after `@` fuzzy-filters the list; ↑/↓ navigate, Enter/Tab/click
   selects, Esc dismisses.
3. The selection becomes a visual chip/pill; the raw `@partial` text is removed from the
   input.
4. On send, the *application* (not the model) resolves each mention: reads the file and
   injects its content into the prompt, typically fenced and labeled with the relative
   path. The model never "opens" the file — the content simply arrives as context. This is
   exactly MCP's "resource" concept: application-controlled context injection.

**Implementation notes for a VS Code webview** (webviews cannot touch the filesystem or
`vscode.workspace` directly — everything crosses `postMessage`):

- Webview detects an active mention by scanning the text before the caret for
  `@<partial-token>`; on trigger it sends `requestFiles` to the extension host.
- Extension host answers with `vscode.workspace.findFiles('**/*', excludeGlob, limit)`
  mapped through `asRelativePath`, posted back as `fileList`.
- Webview renders the dropdown (absolutely positioned above the input), filters locally as
  the user keeps typing, and on selection stores the relative path and renders a pill —
  Atlas already has pill markup/CSS and an `attachedFiles` array + `files` field on the
  `userMessage` payload, so the wiring points already exist.
- On `userMessage`, the extension host (which has fs access) reads each referenced file —
  with a size cap and binary check — and prepends labeled fenced blocks to the message text
  sent to the server. Injecting host-side rather than webview-side keeps file I/O off the
  webview and works under the strict CSP.

Sources: [Cursor docs — @ mentions](https://cursor.com/docs/context/mentions),
[Cursor docs — @Files](https://docs.cursor.com/context/@-symbols/@-files),
[Cursor — context management guide](https://datalakehousehub.com/blog/2026-03-context-management-cursor/).

---

## 5. Error handling in agentic tool-calling loops

**Common failure modes, mapped to where Atlas is currently exposed:**

| Failure mode | Atlas today |
|---|---|
| Non-JSON HTTP response (Render cold start, proxy 502 HTML, plain-text 500) | `response.json()` throws; generic `Error:` blob in chat; on some paths webview waits forever |
| Malformed tool-call arguments from the model | `json.loads(tool_call.function.arguments)` in `server.py` is unguarded → 500 |
| Model emits **multiple** tool calls | Only the first is executed, but *all* are serialized into history → next OpenAI call rejects the transcript (unanswered tool_call ids) — a real latent bug found during code reading |
| Tool subprocess fails to spawn (no `python` on PATH) | `cp.spawn` error event is unhandled → loop hangs, UI stuck on "Working" |
| Tool subprocess hangs | No timeout → infinite wait |
| Infinite tool loop (model keeps calling tools) | `while(true)` with no step cap |
| Huge tool result | Round-trips uncapped through client and into the model context |
| File encoding/permission errors in tools | Bare `except Exception` catch-all exists, but binary files produce `UnicodeDecodeError` noise and stdin JSON parse in `agent.py:main()` is unguarded (crash → empty stdout → "Error executing tool:") |
| UI stuck in waiting state | `setWaiting(false)` only runs on the `agentMessage` path |

**Best practices from the literature and production agents:**

1. **Errors as tool results, not exceptions.** When a tool fails, return the error message
   *to the model* as the tool result so it can reason and adapt — don't break the loop.
   Atlas's `agent.py` already does this at the tool layer; extend the idea to spawn
   failures and timeouts in `panel.ts`.
2. **Two-layer recovery.** Infrastructure retries (network blips, 429s, malformed JSON
   from the model → one bounded retry) belong to the orchestration layer, silently.
   Application-level failures (file not found) belong to the model's reasoning.
3. **Always-valid JSON at every boundary.** Servers must never let a 500 escape as
   plain text: global exception handler returning `{status:"error", message}`. Clients must
   `text()` first, then attempt `JSON.parse`, and translate failures into friendly messages.
4. **Terminal-state guarantee for the UI.** Every code path in the message handler must end
   by posting *something* that clears the waiting state — structure as try/catch with a
   `finally`-style guarantee, plus the webview treating any terminal message type as
   "unlock input."
5. **Bounded loops and timeouts.** Cap agent steps (production agents use ~25–50);
   per-request fetch timeouts; per-tool subprocess timeouts with kill.
6. **Truncate oversized tool results** before appending to model context, with an explicit
   `[truncated]` marker so the model knows.
7. **Don't retry non-retryable errors** (4xx other than 429); one retry with backoff for
   transient classes only.

Sources: [n8n — LLM tool calling error handling](https://blog.n8n.io/llm-tool-calling-error-handling/),
[SHIELDA (arXiv 2508.07935)](https://arxiv.org/pdf/2508.07935),
[Handling LLM output parsing errors](https://apxml.com/courses/prompt-engineering-llm-application-development/chapter-7-output-parsing-validation-reliability/handling-parsing-errors),
[Agent error handling & recovery](https://apxml.com/courses/langchain-production-llm/chapter-2-sophisticated-agents-tools/agent-error-handling),
[LLM API error handling and retry patterns](https://www.grizzlypeaksoftware.com/library/llm-api-error-handling-and-retry-patterns-bpk0jmvq).

---

# Phase 2 — Architecture Decision

## Should Atlas be rewritten on MCP now? **No.**

**Recommendation: keep the HTTP + OpenAI function-calling architecture for this release.
Do not adopt MCP yet.** Reasoning:

1. **Topology mismatch (the decisive reason).** MCP's client must live with the LLM loop.
   Atlas's LLM loop decisions happen in `server.py` on Render; the tools live on the
   user's machine. A remote server cannot attach to a local stdio MCP server, and exposing
   the user's filesystem as a *remote* (Streamable HTTP) MCP server reachable from Render
   would mean punching the user's machine onto the public internet — a non-starter.
   MCP adoption therefore *requires* first moving the agentic loop into the extension
   host. That's a rewrite of the control flow, not an incremental improvement.

2. **No consumer for the portability win.** MCP pays off when tools are shared across
   hosts (Claude Desktop + Cursor + CI) or when consuming third-party servers. Atlas has
   exactly one client (its own webview), one model provider, and ten first-party tools.
   Every MCP benefit is speculative here; every MCP cost (SDK dependency in the extension,
   session lifecycle, spec churn — e.g., the 2026 stateless-session work) is immediate.

3. **Schema translation would still be needed.** The backend speaks OpenAI function
   calling. With MCP in the middle we'd maintain the same JSON Schemas *plus* a
   translation layer. Tool count is small enough that this is pure overhead.

4. **The industry hybrid pattern endorses this.** The documented guidance is: keep
   provider function calling for app-internal tools; graduate tools to MCP when they need
   to be shared. Atlas is squarely in the "app-internal" phase.

## Where MCP *would* go, when the time comes

The right future shape (documented so the next milestone has a target):

1. Move the agentic loop from `server.py` into `src/panel.ts` (the extension host becomes
   the MCP **host**).
2. Replace `agent/agent.py`'s spawn-per-call protocol with a long-lived **local stdio MCP
   server** (Python `mcp` SDK or TypeScript SDK). This is the natural insertion point —
   it already is a tool server in all but protocol. Wins: persistent process (no ~200ms
   Python startup per tool call), standard consent hooks, and the ability to plug
   third-party MCP servers (GitHub, Postgres, docs) into Atlas with zero new code.
3. Shrink `server.py` to a stateless authenticated LLM proxy (it must survive in some form
   — it exists to keep the OpenAI API key off user machines).
4. Optionally register the same server via VS Code's `mcpServerDefinitionProviders` so
   users of Copilot agent mode can reuse Atlas's tools.

**What MCP would NOT replace:** the FastAPI server as key-holder, and the webview UI.

## Tools to add in this release

From the §2 gap analysis — implemented now: **`create_directory`**, **`rename_file`**
(doubles as move), **`get_file_info`**, **`find_files`** (name/glob search, complementing
content search). Deliberately deferred with reasons recorded: `execute_command` and git
tools (need a consent UI before it is safe to let a remotely-prompted model run shell
commands), symbol search / code map (needs tree-sitter or LSP integration),
string-anchored edits (right long-term replacement for `replace_lines`; prompt-level
mitigation for now).

## Other decisions locked by this research

- **System prompt** rewritten along the §3 section structure (identity → environment →
  planning → tool selection with preference ordering and rationales → per-workflow
  procedures → communication contract → error recovery).
- **Error handling** implemented per §5: global JSON exception handler and bounded
  model-retry on malformed tool args (server); text-then-parse, step cap, fetch and
  subprocess timeouts, terminal-message guarantee (extension); specific
  encoding/permission/path handling and crash-proof stdin main (local agent); waiting
  state cleared on every terminal message type (webview). The multiple-tool-call
  serialization bug found in §5 is fixed by trimming the assistant message to the single
  executed call.
- **`@` mentions** implemented per §4: webview dropdown + pills, host-side file listing
  via `findFiles`, host-side content injection with size caps.
- `agent/tools.py` is confirmed dead code; left untouched but flagged in CHANGES.md.
