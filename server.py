import os
import json
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Atlas Code Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Cap how much of a single tool result enters the model context.
MAX_TOOL_RESULT_CHARS = 60_000

SYSTEM_PROMPT = """You are Atlas, an expert autonomous coding agent embedded in VS Code. You read, write, debug, and refactor code across any language or framework by operating directly on the user's workspace through tools.

## ENVIRONMENT
- You operate on the user's local filesystem through the tools listed below. Every tool call executes on their machine; results come back to you as text.
- The absolute workspace path is provided at the end of this prompt. Always build file paths from it — never guess or invent paths.
- You CANNOT run shell commands, execute code, install packages, run tests, or access the internet. If verification requires running something, make the change and explicitly tell the user what to run.
- You cannot see the user's editor, terminal, or cursor. Your only knowledge of the project comes from tool results and what the user tells you (including any file contents attached to their message under "Referenced file").
- Line numbers shown by read_file/read_lines are 1-indexed. After you edit a file, previously fetched line numbers for that file are stale.

## PLANNING AND REASONING
- Investigate before you mutate. Never write to a file you have not read in this conversation.
- For a new task, orient first: call get_file_tree once to learn the layout, then use search_files / find_files to locate relevant code. Do not re-call get_file_tree in the same conversation unless the structure changed.
- Act without asking when the task is clear and reversible (edits the user asked for, new files, refactors they described). State in one sentence what you are about to do, then do it.
- Ask exactly one focused question first when: the request is ambiguous in a way that changes what you'd build, the change is destructive (deleting files, overwriting significant work), or you'd have to guess project-specific intent.
- For multi-file tasks, list the files you plan to touch before the first edit, then work through them one at a time.
- If the user attached file contents to their message, use them directly — do not re-read those files unless you need parts that were truncated.

## TOOL SELECTION
Preference order, with reasons:
- Locating code: search_files (content match) or find_files (filename match) BEFORE reading files one by one. Search is cheap; reading whole files is not.
- Sizing up a file: get_file_info tells you size and line count so you can choose between read_file and read_lines.
- Reading: read_file for files under ~300 lines; read_lines for a targeted slice of anything bigger. Never read a large file whole when you only need one function.
- Editing: replace_lines for targeted changes — but ALWAYS read_lines the exact region first in the same turn, because line numbers go stale after any prior edit. write_file only for genuine full rewrites of files you have read.
- Creating: create_file for new files (it creates parent folders too); create_directory only when an empty directory itself is the deliverable.
- Moving/renaming: rename_file — never simulate a move with read + create + delete.
- Deleting: delete_file only when the user explicitly asked for that specific deletion.

## DEBUGGING WORKFLOW
1. Reproduce understanding: restate the symptom from the user's report or error text.
2. Locate: search_files for the error message, function name, or identifier involved.
3. Read: read_lines around every hit that could be the source; follow the data flow across files if needed.
4. Diagnose: identify the root cause and say what it is in one or two sentences BEFORE editing. If you cannot find a root cause, say so — do not guess-patch symptoms.
5. Fix: make the minimal edit that addresses the cause.
6. Verify: re-read the edited region to confirm the change landed correctly, and check for other call sites the fix affects (search_files for the changed symbol).
7. Report: explain the bug, the fix, and what the user should run to confirm.

## WRITING NEW CODE WORKFLOW
1. Check whether similar functionality already exists (search_files) — extend rather than duplicate.
2. Read one or two neighboring files of the same kind to absorb conventions: naming, imports, formatting, error handling, test style.
3. Never assume a library is available — confirm it appears in existing imports or the dependency manifest (package.json, requirements.txt, etc.) before using it.
4. Write the code following those conventions. Keep functions small and focused.
5. Summarize what was created and what the user should verify or wire up.

## REFACTORING WORKFLOW
1. Read the entire function/class/module being refactored — not just the lines that change.
2. Find every usage site first (search_files for the symbol) so nothing is left referencing the old shape.
3. Make one logical change at a time; update all call sites for that change before starting the next.
4. Preserve behavior unless the user asked for behavior changes; say explicitly if a behavior change is unavoidable.
5. Re-read edited regions to verify, then summarize what changed and why.

## COMMUNICATION STYLE
- Before acting: one sentence stating the plan. During long tasks: brief notes when you discover something that changes the plan.
- After acting: a short summary — what changed, where, and what to check. Reference files as path:line.
- Be concise and concrete. The user sees their files in the editor; do not paste whole file contents back unless asked.
- Plain language for explanations; precise technical terms for code facts. No filler, no apologies.
- Never claim you did something you did not do. If a step failed or was skipped, say so plainly.

## ERROR RECOVERY
- A tool error is information, not a dead end. Read the message and adapt:
  - "File does not exist" → find_files or list_files to locate the real path; check for typos or wrong directory.
  - "line is past the end" / stale-line symptoms → re-read the file, then retry the edit with fresh numbers.
  - "not valid UTF-8 / binary" → the file cannot be edited as text; tell the user.
  - "permission denied" → report it to the user; do not retry in a loop.
- Retry a failed operation at most twice, and only with a changed approach each time. Never repeat the identical failing call.
- If you cannot complete the task after adapting, stop and tell the user exactly what failed, what you tried, and what they can do — an honest partial result beats a fabricated success."""


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_file_tree",
            "description": """Get the full recursive file and folder structure of the workspace.
USE THIS FIRST before any other tool to understand the project layout.
Use this to identify what kind of project it is (Python, Node, etc.), where source files live, and which files are relevant to the user's request.
Do NOT use this repeatedly — call it once at the start and remember the structure.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The root path to generate the tree from. Use the workspace root unless told otherwise."
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth to recurse. Default 3. Use 2 for large projects to avoid noise."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": """List files and folders in a specific directory.
Use this when you need to inspect a specific subdirectory after get_file_tree has given you the overall structure.
Example: user asks about tests — use this to list the tests/ folder specifically.
Do NOT use this as a substitute for get_file_tree on the root.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to list."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": """Read the full content of a file.
Use this for short to medium files (under ~300 lines).
For large files, prefer read_lines to avoid flooding the context window.
ALWAYS read a file before modifying it — never assume its contents.
Use search_files first to locate which file contains the code you need.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The full path to the file."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_lines",
            "description": """Read a specific range of lines from a file.
Use this for large files when you only need a specific section.
Use search_files to find which lines are relevant, then read_lines to fetch just those.
Prefer this over read_file for files longer than ~300 lines.
Lines are 1-indexed and inclusive.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The full path to the file."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Starting line number (1-indexed)."
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Ending line number (1-indexed, inclusive)."
                    }
                },
                "required": ["path", "start_line", "end_line"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": """Search for a string or pattern across all files in the workspace (matches file CONTENTS).
Use this to locate where a function, class, variable, or error is defined before reading or editing.
Always use this before read_file when you don't know which file contains the relevant code.
Results include file path and line number.
To find files by NAME instead of contents, use find_files.
Optional: filter by file extension (e.g. '.py', '.js') to narrow results.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "The root workspace directory to search in."
                    },
                    "query": {
                        "type": "string",
                        "description": "The string to search for. Case-insensitive."
                    },
                    "file_extension": {
                        "type": "string",
                        "description": "Optional file extension filter e.g. '.py', '.js', '.ts'."
                    }
                },
                "required": ["workspace", "query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": """Find files by NAME using a glob-style pattern (matches filenames, not contents).
Use this when you know (part of) a filename but not where it lives.
Examples: pattern '*.test.ts' finds all test files; 'config*' finds config.yaml, config.json, etc.
Case-insensitive. To search file CONTENTS, use search_files instead.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "The root workspace directory to search in."
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern matched against filenames, e.g. '*.py', 'test_*', 'config*'."
                    }
                },
                "required": ["workspace", "pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_info",
            "description": """Get metadata about a file or directory: size in bytes, line count, and last modified time.
Use this to size up a file BEFORE reading it, so you can choose read_file (small files) vs read_lines (large files).
Also useful to confirm a file exists and check whether it changed recently.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The full path to the file or directory."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": """Replace a specific range of lines in a file without rewriting the entire file.
PREFER THIS over write_file for targeted edits — it is safer and more precise.
Always use read_lines first to confirm the exact lines you are replacing.
WARNING: line numbers become stale after any previous edit to the same file — re-read before each edit.
Use this for: fixing bugs, updating a function, changing a specific block of logic.
Do NOT use this to add content at the end of a file — use write_file for full rewrites or append scenarios.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The full path to the file."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Starting line number to replace (1-indexed)."
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Ending line number to replace (1-indexed, inclusive)."
                    },
                    "new_content": {
                        "type": "string",
                        "description": "The new content to replace the specified lines with."
                    }
                },
                "required": ["path", "start_line", "end_line", "new_content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": """Overwrite the ENTIRE content of an existing file.
WARNING: This replaces everything in the file. Only use when a full rewrite is genuinely needed.
For targeted changes, use replace_lines instead.
ALWAYS read the file first before writing to it.
Do NOT use this to create new files — use create_file instead.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The full path to the file to overwrite."
                    },
                    "content": {
                        "type": "string",
                        "description": "The complete new content for the file."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": """Create a new file with given content. Parent directories are created automatically.
Use this when the user asks to add a new file, module, or script to the project.
Fails safely if the file already exists — will not overwrite.
Follow the project's existing conventions — check similar files first with read_file to match style and imports.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The full path for the new file."
                    },
                    "content": {
                        "type": "string",
                        "description": "The initial content to write to the file."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": """Create a new directory (including any missing parent directories).
Use this only when an empty directory itself is needed — create_file already creates parent folders for new files.
Safe to call if the directory already exists (reports it, changes nothing).""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The full path of the directory to create."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rename_file",
            "description": """Rename or move a file or directory to a new path.
Use this for renames and moves — NEVER simulate a move by reading, creating, and deleting.
Parent directories of the destination are created automatically.
Fails safely if the destination already exists — will not overwrite.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "The current full path of the file or directory."
                    },
                    "destination": {
                        "type": "string",
                        "description": "The new full path."
                    }
                },
                "required": ["source", "destination"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": """Delete a file permanently. This CANNOT be undone.
ONLY use this when the user has explicitly asked to delete a specific file.
Never delete files as a side effect of another task.
If unsure, ask the user to confirm before calling this tool.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The full path to the file to delete."
                    }
                },
                "required": ["path"]
            }
        }
    }
]


class ToolResult(BaseModel):
    tool_call_id: str
    result: str

class ChatRequest(BaseModel):
    message: Optional[str] = None
    workspace: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = []
    tool_result: Optional[ToolResult] = None
    messages: Optional[List[Dict[str, Any]]] = None


# Any exception that escapes an endpoint still returns structured JSON,
# never a plain-text 500 the extension can't parse.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={"status": "error", "message": f"Server error: {type(exc).__name__}: {str(exc)}"}
    )


def _serialize_message(m):
    return m.model_dump() if hasattr(m, "model_dump") else m


# ── endpoints ──
@app.post("/chat")
def chat(body: ChatRequest):
    try:
        if body.messages and body.tool_result:
            # continuing loop with tool result
            messages = [dict(m) for m in body.messages]
            result_text = body.tool_result.result
            if len(result_text) > MAX_TOOL_RESULT_CHARS:
                result_text = result_text[:MAX_TOOL_RESULT_CHARS] + "\n[... result truncated ...]"
            messages.append({
                "role": "tool",
                "tool_call_id": body.tool_result.tool_call_id,
                "content": result_text
            })
        elif body.message is not None:
            # fresh turn
            messages = [
                {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nWorkspace: {body.workspace}"}
            ]
            for entry in (body.history or [])[:-1]:
                if isinstance(entry, dict) and "role" in entry and "content" in entry:
                    messages.append({"role": entry["role"], "content": entry["content"]})
            messages.append({"role": "user", "content": body.message})
        else:
            return {"status": "error", "message": "Invalid request: expected either a message or a tool result."}

        # One bounded retry: if the model emits unparseable tool arguments, feed the
        # parse error back as the tool result and let it correct itself once.
        for attempt in range(2):
            response = client.chat.completions.create(
                model="gpt-5.4-nano",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto"
            )

            message = response.choices[0].message

            if not message.tool_calls:
                serializable = [_serialize_message(m) for m in messages]
                serializable.append(_serialize_message(message)
                                    if hasattr(message, "model_dump")
                                    else {"role": "assistant", "content": message.content})
                return {
                    "status": "done",
                    "message": message.content or "",
                    "messages": serializable
                }

            tool_call = message.tool_calls[0]

            # The client executes exactly one tool call per round trip, so the
            # serialized assistant message must contain only that call — leaving
            # extra tool_calls in history makes the next API call reject the
            # transcript for unanswered tool_call ids.
            assistant_msg = _serialize_message(message)
            if isinstance(assistant_msg, dict) and assistant_msg.get("tool_calls"):
                assistant_msg["tool_calls"] = assistant_msg["tool_calls"][:1]

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                if attempt == 0:
                    messages.append(assistant_msg)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error: your tool arguments were not valid JSON ({str(e)}). Retry the call with valid JSON arguments."
                    })
                    continue
                return {"status": "error",
                        "message": "The model produced malformed tool arguments twice. Please try rephrasing your request."}

            serializable = [_serialize_message(m) for m in messages]
            serializable.append(assistant_msg)
            return {
                "status": "tool_call",
                "tool_name": tool_call.function.name,
                "tool_args": tool_args,
                "tool_call_id": tool_call.id,
                "messages": serializable
            }

        return {"status": "error", "message": "Unexpected state in the agent loop. Please try again."}

    except Exception as e:
        return {"status": "error", "message": f"Server error: {type(e).__name__}: {str(e)}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
