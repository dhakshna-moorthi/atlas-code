import sys
import json
import os
import shutil
import fnmatch
from datetime import datetime

# Directories never worth walking into — build output, deps, VCS internals.
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'venv', '.venv', 'out', '.next', 'dist'}


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
        elif tool_name == "create_directory":
            return _create_directory(tool_args["path"])
        elif tool_name == "rename_file":
            return _rename_file(tool_args["source"], tool_args["destination"])
        elif tool_name == "get_file_info":
            return _get_file_info(tool_args["path"])
        elif tool_name == "find_files":
            return _find_files(tool_args["workspace"], tool_args["pattern"])
        else:
            return f"Unknown tool: {tool_name}"
    except KeyError as e:
        return f"Tool error ({tool_name}): missing required argument {str(e)}"
    except PermissionError as e:
        return f"Tool error ({tool_name}): permission denied for {getattr(e, 'filename', None) or e}"
    except IsADirectoryError as e:
        return f"Tool error ({tool_name}): expected a file but got a directory: {getattr(e, 'filename', None) or e}"
    except NotADirectoryError as e:
        return f"Tool error ({tool_name}): expected a directory but got a file: {getattr(e, 'filename', None) or e}"
    except UnicodeDecodeError:
        return f"Tool error ({tool_name}): file is not valid UTF-8 text (possibly binary). Only text files can be read."
    except OSError as e:
        return f"Tool error ({tool_name}): {e.strerror or str(e)} ({getattr(e, 'filename', None) or 'path error'})"
    except Exception as e:
        return f"Tool error ({tool_name}): {str(e)}"


def _read_text(path):
    """Read a text file, falling back to replacement chars for odd encodings."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.readlines()
    except UnicodeDecodeError:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.readlines()


def _list_files(path):
    if not os.path.exists(path):
        return f"Path does not exist: {path}"
    if not os.path.isdir(path):
        return f"Not a directory: {path}"
    entries = os.listdir(path)
    folders = sorted([f"[dir]  {e}" for e in entries if os.path.isdir(os.path.join(path, e))])
    files = sorted([f"[file] {e}" for e in entries if os.path.isfile(os.path.join(path, e))])
    return "\n".join(folders + files) if (folders or files) else "(empty directory)"


def _read_file(path):
    if not os.path.exists(path):
        return f"File does not exist: {path}"
    if os.path.isdir(path):
        return f"Not a file (it is a directory): {path}"
    lines = _read_text(path)
    return "".join([f"{i+1}: {line}" for i, line in enumerate(lines)]) or "(empty file)"


def _write_file(path, content):
    if not os.path.exists(path):
        return f"File does not exist: {path}. Use create_file to create a new file."
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Successfully wrote to {path}"


def _create_file(path, content):
    if os.path.exists(path):
        return f"File already exists: {path}. Use write_file to overwrite."
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Successfully created {path}"


def _delete_file(path):
    if not os.path.exists(path):
        return f"File does not exist: {path}"
    if os.path.isdir(path):
        return f"Refusing to delete: {path} is a directory, not a file."
    os.remove(path)
    return f"Successfully deleted {path}"


def _read_lines(path, start_line, end_line):
    if not os.path.exists(path):
        return f"File does not exist: {path}"
    lines = _read_text(path)
    start = max(0, start_line - 1)
    end = min(len(lines), end_line)
    if start >= len(lines):
        return f"start_line {start_line} is past the end of the file ({len(lines)} lines)."
    return "".join([f"{start + i + 1}: {line}" for i, line in enumerate(lines[start:end])])


def _replace_lines(path, start_line, end_line, new_content):
    if not os.path.exists(path):
        return f"File does not exist: {path}"
    lines = _read_text(path)
    if start_line > len(lines):
        return f"start_line {start_line} is past the end of the file ({len(lines)} lines). Re-read the file to get current line numbers."
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
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
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
                continue  # unreadable/binary files are expected — skip silently
    return "\n".join(results[:50]) if results else f"No matches found for '{query}'"


def _get_file_tree(path, max_depth=3):
    if not os.path.exists(path):
        return f"Path does not exist: {path}"
    lines = []
    _walk_tree(path, lines, 0, max_depth)
    return "\n".join(lines) if lines else "(empty)"


def _walk_tree(path, lines, depth, max_depth):
    if depth > max_depth:
        return
    indent = "  " * depth
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return
    for entry in entries:
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            if entry in SKIP_DIRS or entry.startswith('.'):
                continue
            lines.append(f"{indent}📁 {entry}/")
            _walk_tree(full, lines, depth + 1, max_depth)
        else:
            lines.append(f"{indent}📄 {entry}")


def _create_directory(path):
    if os.path.isfile(path):
        return f"Cannot create directory: a file already exists at {path}"
    if os.path.isdir(path):
        return f"Directory already exists: {path}"
    os.makedirs(path, exist_ok=True)
    return f"Successfully created directory {path}"


def _rename_file(source, destination):
    if not os.path.exists(source):
        return f"Source does not exist: {source}"
    if os.path.exists(destination):
        return f"Destination already exists: {destination}. Refusing to overwrite."
    parent = os.path.dirname(destination)
    if parent:
        os.makedirs(parent, exist_ok=True)
    shutil.move(source, destination)  # handles cross-drive moves, unlike os.rename
    return f"Successfully moved {source} -> {destination}"


def _get_file_info(path):
    if not os.path.exists(path):
        return f"Path does not exist: {path}"
    st = os.stat(path)
    modified = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    if os.path.isdir(path):
        try:
            count = len(os.listdir(path))
        except PermissionError:
            count = "unknown (permission denied)"
        return f"Type: directory\nPath: {path}\nEntries: {count}\nLast modified: {modified}"
    line_count = "unknown (binary or unreadable)"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            line_count = sum(1 for _ in f)
    except (UnicodeDecodeError, OSError):
        pass
    return (f"Type: file\nPath: {path}\nSize: {st.st_size} bytes\n"
            f"Lines: {line_count}\nLast modified: {modified}")


def _find_files(workspace, pattern):
    if not os.path.exists(workspace):
        return f"Workspace does not exist: {workspace}"
    matches = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for filename in files:
            if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                matches.append(os.path.join(root, filename))
                if len(matches) >= 50:
                    return "\n".join(matches) + "\n(results capped at 50)"
    return "\n".join(matches) if matches else f"No files matching '{pattern}'"


def main():
    # This process must always emit exactly one valid JSON object on stdout —
    # the extension parses it blindly, so every failure path funnels into "result".
    try:
        raw = sys.stdin.read()
        input_data = json.loads(raw)
        tool_name = input_data.get("tool_name")
        tool_args = input_data.get("tool_args", {})
        if not tool_name:
            result = "Error: no tool_name provided to agent."
        elif not isinstance(tool_args, dict):
            result = "Error: tool_args must be an object."
        else:
            result = execute_tool(tool_name, tool_args)
    except json.JSONDecodeError as e:
        result = f"Error: agent received invalid JSON input: {str(e)}"
    except Exception as e:
        result = f"Error: agent failed unexpectedly: {str(e)}"

    try:
        print(json.dumps({"result": result}))
    except Exception:
        # json.dumps can only fail on non-serializable input; result is always str,
        # but guard anyway so stdout is never empty.
        print(json.dumps({"result": "Error: agent could not serialize the tool result."}))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
