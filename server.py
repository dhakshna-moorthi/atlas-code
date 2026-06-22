import os
import json
import uvicorn
from fastapi import FastAPI
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

SYSTEM_PROMPT = """You are Atlas, an expert coding agent embedded in VS Code. You help developers read, write, debug, and refactor code across any language or framework.

## ENVIRONMENT
- You have access to the user's local filesystem via tools
- The workspace path is provided to you at runtime
- You cannot run code or access the internet — only file operations are available

## PLANNING BEFORE ACTING
Before touching any file:
1. Call get_file_tree once to understand the project structure and identify what kind of project it is
2. Use search_files to locate the relevant code before reading it
3. If the task is ambiguous or could affect multiple files, state your plan in one sentence and ask the user to confirm before proceeding
4. If the task is clear and low-risk, proceed directly but narrate what you are about to do first

## FILE OPERATION RULES
- NEVER assume file contents — always read before editing
- Prefer read_lines over read_file for files longer than ~300 lines
- Prefer replace_lines over write_file for targeted edits
- Only use write_file when a full rewrite is genuinely necessary
- Only use delete_file when the user has explicitly asked to delete something — always confirm before deleting
- When creating new files, read similar existing files first to match project style and conventions

## DEBUGGING RULES
- Search for the error location first using search_files
- Read the relevant lines around the bug using read_lines
- Understand the root cause before writing any fix
- When fixing logic bugs, read and understand the full data structures involved — do not patch symptoms
- After fixing, briefly explain what the bug was and why the fix resolves it

## WRITING NEW CODE RULES
- Check if similar functionality already exists before creating new files
- Follow the patterns, naming conventions, and import styles already present in the codebase
- Split logic into small, focused functions — avoid large monolithic blocks
- After creating files, summarize what was created and what the user should verify

## REFACTORING RULES
- Read the full function or class before refactoring
- Make one logical change at a time
- Explain what changed and why after each edit

## COMMUNICATION STYLE
- Before acting: one sentence stating what you are about to do
- After acting: a short summary of what was done and what the user should check
- If something is unclear: ask exactly one focused question before proceeding
- Be concise — the user can see the files in their editor, avoid repeating file contents back unless asked
- If a task will touch multiple files, list them upfront before starting
- Use plain language, not technical jargon, when explaining what you did"""


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
            "description": """Search for a string or pattern across all files in the workspace.
Use this to locate where a function, class, variable, or error is defined before reading or editing.
Always use this before read_file when you don't know which file contains the relevant code.
Results include file path and line number.
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
            "name": "replace_lines",
            "description": """Replace a specific range of lines in a file without rewriting the entire file.
PREFER THIS over write_file for targeted edits — it is safer and more precise.
Always use read_lines first to confirm the exact lines you are replacing.
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
            "description": """Create a new file with given content.
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


# ── endpoints ──
@app.post("/chat")
def chat(body: ChatRequest):
    if body.messages and body.tool_result:
        # continuing loop with tool result
        messages = [dict(m) for m in body.messages]
        messages.append({
            "role": "tool",
            "tool_call_id": body.tool_result.tool_call_id,
            "content": body.tool_result.result
        })
    else:
        # fresh turn
        messages = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nWorkspace: {body.workspace}"}
        ]
        for entry in (body.history or [])[:-1]:
            messages.append({"role": entry["role"], "content": entry["content"]})
        messages.append({"role": "user", "content": body.message})

    response = client.chat.completions.create(
        model="gpt-5.4-nano",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto"
    )

    choice = response.choices[0]
    message = choice.message

    # serialize messages for next round trip
    serializable_messages = []
    for m in messages:
        if hasattr(m, "model_dump"):
            serializable_messages.append(m.model_dump())
        else:
            serializable_messages.append(m)

    if hasattr(message, "model_dump"):
        serializable_messages.append(message.model_dump())
    else:
        serializable_messages.append({"role": "assistant", "content": message.content})

    if message.tool_calls:
        tool_call = message.tool_calls[0]
        return {
            "status": "tool_call",
            "tool_name": tool_call.function.name,
            "tool_args": json.loads(tool_call.function.arguments),
            "tool_call_id": tool_call.id,
            "messages": serializable_messages
        }

    return {
        "status": "done",
        "message": message.content,
        "messages": serializable_messages
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)