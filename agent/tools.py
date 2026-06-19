import os

# ── tool definitions (OpenAI schema) ──
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


# ── tool execution ──
def execute_tool(tool_name, tool_args):
    try:
        if tool_name == "list_files":
            return _list_files(tool_args["path"])
        elif tool_name == "read_file":
            return _read_file(tool_args["path"])
        elif tool_name == "write_file":
            return _write_file(tool_args["path"], tool_args["content"])
        elif tool_name == "create_file":
            return _create_file(tool_args["path"], tool_args["content"])
        elif tool_name == "delete_file":
            return _delete_file(tool_args["path"])
        elif tool_name == "read_lines":
            return _read_lines(tool_args["path"], tool_args["start_line"], tool_args["end_line"])
        elif tool_name == "replace_lines":
            return _replace_lines(tool_args["path"], tool_args["start_line"], tool_args["end_line"], tool_args["new_content"])
        elif tool_name == "search_files":
            return _search_files(tool_args["workspace"], tool_args["query"], tool_args.get("file_extension"))
        elif tool_name == "get_file_tree":
            return _get_file_tree(tool_args["path"], tool_args.get("max_depth", 3))
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        return f"Tool error ({tool_name}): {str(e)}"


# ── implementations ──
def _list_files(path):
    if not os.path.exists(path):
        return f"Path does not exist: {path}"
    entries = os.listdir(path)
    folders = sorted([f"[dir]  {e}" for e in entries if os.path.isdir(os.path.join(path, e))])
    files = sorted([f"[file] {e}" for e in entries if os.path.isfile(os.path.join(path, e))])
    return "\n".join(folders + files)


def _read_file(path):
    if not os.path.exists(path):
        return f"File does not exist: {path}"
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    numbered = [f"{i+1}: {line}" for i, line in enumerate(lines)]
    return "".join(numbered)


def _write_file(path, content):
    if not os.path.exists(path):
        return f"File does not exist: {path}. Use create_file to create a new file."
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Successfully wrote to {path}"


def _create_file(path, content):
    if os.path.exists(path):
        return f"File already exists: {path}. Use write_file to overwrite."
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Successfully created {path}"


def _delete_file(path):
    if not os.path.exists(path):
        return f"File does not exist: {path}"
    os.remove(path)
    return f"Successfully deleted {path}"


def _read_lines(path, start_line, end_line):
    if not os.path.exists(path):
        return f"File does not exist: {path}"
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    start = max(0, start_line - 1)
    end = min(len(lines), end_line)
    selected = lines[start:end]
    return "".join([f"{start + i + 1}: {line}" for i, line in enumerate(selected)])


def _replace_lines(path, start_line, end_line, new_content):
    if not os.path.exists(path):
        return f"File does not exist: {path}"
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    start = max(0, start_line - 1)
    end = min(len(lines), end_line)
    new_lines = new_content.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'
    lines[start:end] = new_lines
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    return f"Successfully replaced lines {start_line}-{end_line} in {path}"


def _search_files(workspace, query, file_extension=None):
    if not os.path.exists(workspace):
        return f"Workspace does not exist: {workspace}"
    results = []
    skip_dirs = {'.git', 'node_modules', '__pycache__', 'venv', '.venv', 'out', '.next', 'dist'}
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
        for filename in files:
            if file_extension and not filename.endswith(file_extension):
                continue
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f, 1):
                        if query.lower() in line.lower():
                            results.append(f"{filepath}:{i}: {line.rstrip()}")
            except Exception:
                continue
    return "\n".join(results[:50]) if results else f"No matches found for '{query}'"


def _get_file_tree(path, max_depth=3):
    if not os.path.exists(path):
        return f"Path does not exist: {path}"
    lines = []
    _walk_tree(path, lines, 0, max_depth)
    return "\n".join(lines)


def _walk_tree(path, lines, depth, max_depth):
    if depth > max_depth:
        return
    indent = "  " * depth
    skip_dirs = {'.git', 'node_modules', '__pycache__', 'venv', '.venv', 'out', '.next', 'dist'}
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return
    for entry in entries:
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            if entry in skip_dirs or entry.startswith('.'):
                continue
            lines.append(f"{indent}📁 {entry}/")
            _walk_tree(full, lines, depth + 1, max_depth)
        else:
            lines.append(f"{indent}📄 {entry}")