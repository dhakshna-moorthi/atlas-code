# Atlas Code

A coding agent for VS Code powered by GPT-5.4-Nano. Read, write, debug, and refactor your code using natural language.

## Features

- **File operations** — read, write, create, and delete files in your workspace
- **Code generation** — generate new files and functions from a description
- **Debugging** — find and fix bugs across your codebase
- **Refactoring** — improve existing code with targeted edits
- **Project exploration** — understand your codebase structure instantly

## How it works

1. You type a message in the Atlas Code panel
2. The message is sent to a backend server, which uses AI to decide which file operations to perform
3. File operations (read, write, create, delete) execute locally on your machine
4. Results are returned and the agent replies in the chat

## Requirements

- Python 3.8 or higher must be installed on your machine
- An active internet connection to reach the Atlas server

## Usage

1. Install the extension from VS Code — Atlas Code Agent
2. Open the Atlas Code panel from the activity bar
3. Open a folder in VS Code
4. Start asking Atlas to help with your code

## Privacy & Data

- **What's sent to the server:** your message and workspace path, used only to process your request
- **File operations run locally:** reading, writing, creating, and deleting files all happen on your machine
- **AI processing:** the backend uses the OpenAI API to understand your request and plan actions
- **No permanent storage:** your messages and file data are not stored after your request is handled
- **No third-party sharing:** your data is not sold or shared with anyone other than OpenAI for request processing

See [PRIVACY_POLICY.md](PRIVACY_POLICY.md) for full details.