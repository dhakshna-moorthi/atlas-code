import sys
import json
import os
from dotenv import load_dotenv
from openai import OpenAI
from tools import TOOLS, execute_tool

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are Nexus, an expert coding agent embedded in VS Code. You help developers read, write, debug, and refactor code across any language or framework.

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


def emit(event: dict):
    sys.stdout.write(json.dumps(event) + '\n')
    sys.stdout.flush()


def activity_text(tool_name: str, tool_args: dict) -> str:
    basename = lambda p: os.path.basename(p.rstrip('/\\')) or p
    if tool_name == 'get_file_tree':
        return "Exploring project structure..."
    if tool_name == 'list_files':
        return f"Listing {basename(tool_args.get('path', ''))}..."
    if tool_name == 'read_file':
        return f"Reading {basename(tool_args.get('path', ''))}..."
    if tool_name == 'read_lines':
        return f"Reading {basename(tool_args.get('path', ''))}..."
    if tool_name == 'search_files':
        q = tool_args.get('query', '')
        return f"Searching for '{q}'..." if q else "Searching files..."
    if tool_name == 'replace_lines':
        return f"Updating {basename(tool_args.get('path', ''))}..."
    if tool_name == 'write_file':
        return f"Writing {basename(tool_args.get('path', ''))}..."
    if tool_name == 'create_file':
        return f"Creating {basename(tool_args.get('path', ''))}..."
    if tool_name == 'delete_file':
        return f"Deleting {basename(tool_args.get('path', ''))}..."
    return f"Running {tool_name}..."


def run_agent(user_message, model, workspace, history):
    messages = [
        { "role": "system", "content": f"{SYSTEM_PROMPT}\n\nWorkspace is at: {workspace}" },
    ]

    for entry in history[:-1]:
        messages.append({ "role": entry["role"], "content": entry["content"] })

    messages.append({ "role": "user", "content": user_message })

    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )

        choice = response.choices[0]
        message = choice.message

        if not message.tool_calls:
            return message.content

        messages.append(message)

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            emit({"type": "activity", "text": activity_text(tool_name, tool_args)})
            tool_result = execute_tool(tool_name, tool_args)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result
            })

    return "Max iterations reached. The agent could not complete the task."


def main():
    input_data = json.loads(sys.stdin.read())

    user_message = input_data.get("message")
    model = input_data.get("model", "gpt-5.4-nano")
    workspace = input_data.get("workspace")
    history = input_data.get("history", [])

    emit({
        "type": "response",
        "status": "success",
        "message": run_agent(user_message, model, workspace, history)
    })

if __name__ == "__main__":
    main()