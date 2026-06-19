import sys
import json
import os


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
    return "".join([f"{i+1}: {line}" for i, line in enumerate(lines)])


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
    return "".join([f"{start + i + 1}: {line}" for i, line in enumerate(lines[start:end])])


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


def main():
    input_data = json.loads(sys.stdin.read())
    tool_name = input_data.get("tool_name")
    tool_args = input_data.get("tool_args", {})
    result = execute_tool(tool_name, tool_args)
    print(json.dumps({ "result": result }))
    sys.stdout.flush()


if __name__ == "__main__":
    main()