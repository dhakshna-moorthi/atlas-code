# Changes — July 2026 overhaul

Companion to [RESEARCH.md](RESEARCH.md), which contains the research and the architecture
decision behind everything below.

## Architecture decision (Phase 2)

**MCP was researched and deliberately NOT adopted.** Atlas's LLM loop runs on the remote
FastAPI server while tools execute on the user's machine; an MCP client must live with the
loop, so adopting MCP would first require moving the agentic loop into the extension host —
a control-flow rewrite with no payoff at Atlas's current scale (one client, one provider,
~13 first-party tools). The HTTP + OpenAI function-calling architecture stays. RESEARCH.md
documents the future shape if/when MCP becomes worth it (local stdio MCP server replacing
the spawn-per-call Python agent, loop moved into the extension, server.py reduced to a key-
holding LLM proxy). No endpoints or request/response shapes changed.

## New tools (agent/agent.py + server.py)

Chosen from a gap analysis against Claude Code, Cline, Aider, and Cursor:

- `create_directory` — mkdir -p semantics; safe if the directory exists.
- `rename_file` — rename/move (shutil.move, cross-drive safe); creates destination parent
  dirs; refuses to overwrite. Replaces the old read+create+delete dance.
- `get_file_info` — size, line count, last-modified; lets the model pick `read_file` vs
  `read_lines` before reading.
- `find_files` — glob search by filename, complementing content-only `search_files`.

Deferred with reasons recorded in RESEARCH.md: `execute_command` / git tools (need a
consent UI first), symbol search (needs tree-sitter/LSP).

## System prompt (server.py)

Rewritten from scratch along the structure shared by published production prompts
(Cline, Claude Code): identity → environment (with explicit cannot-dos and the stale-line-
number caveat) → planning/reasoning (act-vs-ask policy) → tool selection with preference
ordering *and rationales* → step-by-step debugging / new-code / refactoring workflows →
communication contract → error recovery (specific tool-error → response mappings, max-two-
retries rule, honest-failure rule).

## Error handling (all four layers)

- **server.py** — global exception handler plus per-endpoint try/except: every failure
  returns JSON `{status:"error", message}`; a plain-text 500 can no longer escape.
  Malformed tool arguments from the model get one bounded self-correction retry.
  Oversized tool results are truncated (60k chars) with a marker.
  **Latent bug fixed:** when the model emitted multiple tool calls, all were serialized
  into history but only one was answered, which made the next OpenAI call reject the
  transcript — the assistant message is now trimmed to the single executed call.
- **src/panel.ts** — responses are read as text and parsed defensively (Render cold-start
  HTML pages no longer crash the loop); fetch timeout (120s); step cap (30) so the loop
  can't spin forever; tool subprocess gets a 60s timeout, a spawn-failure handler
  ("Python not installed" is now a friendly message instead of a hang), and stderr
  capture; a `finish()` guard guarantees exactly one terminal webview message
  (`agentMessage` or `agentError`) on every code path.
- **agent/agent.py** — specific handling for permission, encoding (UTF-8 fallback with
  replacement chars), directory-vs-file, and missing-argument errors; out-of-range line
  numbers now tell the model to re-read the file; `main()` can no longer crash on bad
  stdin — the process always emits exactly one valid JSON object.
- **media/main.js** — new `agentError` message type rendered as a styled error note; both
  terminal message types funnel through one `finalizeTurn()` that always calls
  `setWaiting(false)`, so the UI cannot get stuck in the waiting state.

## @ file references (media/main.js + src/panel.ts + media/style.css)

Cursor-style mentions: typing `@` in the input opens a dropdown of workspace files
(fetched from the extension host via `vscode.workspace.findFiles`, node_modules/.git/venv
excluded), filterable as you type, with ↑/↓/Enter/Tab/Esc keyboard navigation and mouse
selection. Selecting a file removes the `@query` text and adds a pill using the existing
pill styling. On send, the extension host reads each referenced file (100 KB cap,
truncation marker) and injects it into the message as a labeled fenced block. New CSS was
added only for the dropdown and error note; existing styles are untouched.

## Activity labels (src/panel.ts)

Terminal-flavored per spec: `Running ls -R...`, `Running ls...`, `Reading file...`,
`Reading lines...`, `Running grep "..."...`, `Editing file...`, `Writing file...`,
`Creating file...`, `Removing file...`, `Running mkdir...`, `Running mv...`,
`Running find "..."...`, `Running stat...`, and `Fetching...` for any future web tools.

## Notes

- `agent/tools.py` is **dead code** — nothing imports it (the extension spawns
  `agent/agent.py`, which has its own schemas-free executor; the server owns the schemas).
  Left untouched to keep this change reviewable; recommend deleting it in a follow-up.
- Verified: `tsc` compiles clean, `eslint` clean, both Python files byte-compile, and all
  new/updated agent tools plus their error paths were exercised end-to-end via stdin.
- `media/index.html` did not need changes (the dropdown is created dynamically), so the
  existing UI design is fully preserved.
