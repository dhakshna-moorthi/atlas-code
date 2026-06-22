# Privacy Policy — Atlas Code

_Last updated: June 2026_

## What data leaves your machine

When you send a message in Atlas Code, the following information is transmitted to the Atlas backend server:

- The text of your message
- Your current workspace path (the root folder you have open in VS Code)
- The conversation history for the current session

This data is sent solely to determine which file operations to perform in response to your request.

## What stays on your machine

All file operations — reading, writing, creating, and deleting files — execute locally on your machine via a Python process. File contents are only read when the agent determines it needs to inspect a specific file; they are not uploaded in bulk.

## How requests are processed

The Atlas backend uses the OpenAI API to process your messages and decide what actions to take. Your message and workspace context are passed to OpenAI's models server-side. OpenAI's own privacy policy governs how they handle that data.

## Data retention

No user data, messages, file contents, or workspace information is stored permanently on the Atlas backend. Each request is processed in memory and discarded when the response is returned.

## Third-party sharing

Your data is not sold, rented, or shared with any third parties other than OpenAI for the sole purpose of processing your requests.

## Python requirement

Atlas Code requires Python 3.8 or higher to be installed on your machine. Python is used only to execute local file operations; no additional data is sent through the Python process.

## Contact

If you have questions about this policy, open an issue at https://github.com/dhakshna-moorthi/atlas-code.
