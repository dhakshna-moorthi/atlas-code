import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

const SERVER_URL = "https://nexus-code-server.onrender.com";

export class NexusViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'nexus.chatView';
    private _token: string | null = null;

    constructor(private readonly _extensionUri: vscode.Uri) {}

    resolveWebviewView(webviewView: vscode.WebviewView) {
        const mediaUri = vscode.Uri.joinPath(this._extensionUri, 'media');

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [mediaUri]
        };

        webviewView.webview.html = this.getHtml(webviewView.webview);

        let history: { role: string; content: string }[] = [];

        webviewView.webview.onDidReceiveMessage(async message => {

            // ── login ──
            if (message.type === 'validateKey') {
                try {
                    const response = await fetch(`${SERVER_URL}/login`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            username: 'admin',
                            password: message.key
                        })
                    });
                    const data = await response.json() as { status: string; token?: string };
                    if (data.status === 'success' && data.token) {
                        this._token = data.token;
                        webviewView.webview.postMessage({ type: 'keyResult', valid: true });
                    } else {
                        webviewView.webview.postMessage({ type: 'keyResult', valid: false });
                    }
                } catch {
                    webviewView.webview.postMessage({ type: 'keyResult', valid: false });
                }
                return;
            }

            // ── chat ──
            if (message.type === 'userMessage') {
                if (!this._token) {
                    webviewView.webview.postMessage({ type: 'agentMessage', text: 'Not authenticated.' });
                    return;
                }

                const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
                history.push({ role: 'user', content: message.text });

                const agentPath = path.join(this._extensionUri.fsPath, 'agent', 'agent.py');
                const isWindows = process.platform === 'win32';
                const pythonPath = path.join(
                    this._extensionUri.fsPath,
                    'venv',
                    isWindows ? 'Scripts' : 'bin',
                    isWindows ? 'python.exe' : 'python'
                );

                try {
                    // agentic loop
                    let requestBody: Record<string, unknown> = {
                        message: message.text,
                        workspace: workspacePath,
                        history: history
                    };
                    let messages: unknown[] | null = null;

                    while (true) {
                        const response = await fetch(`${SERVER_URL}/chat`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'authorization': `Bearer ${this._token}`
                            },
                            body: JSON.stringify(requestBody)
                        });

                        const data = await response.json() as {
                            status: string;
                            message?: string;
                            tool_name?: string;
                            tool_args?: Record<string, unknown>;
                            tool_call_id?: string;
                            messages?: unknown[];
                        };

                        if (data.status === 'done') {
                            const finalMessage = data.message || '';
                            history.push({ role: 'assistant', content: finalMessage });
                            webviewView.webview.postMessage({
                                type: 'agentMessage',
                                text: finalMessage
                            });
                            break;
                        }

                        if (data.status === 'tool_call') {
                            const toolName = data.tool_name!;
                            const toolArgs = data.tool_args!;
                            const toolCallId = data.tool_call_id!;
                            messages = data.messages!;

                            // emit activity to UI
                            webviewView.webview.postMessage({
                                type: 'activityUpdate',
                                text: activityText(toolName, toolArgs)
                            });

                            // execute tool locally via Python
                            const toolResult = await runLocalTool(pythonPath, agentPath, toolName, toolArgs);

                            // feed result back to server
                            requestBody = {
                                messages: messages,
                                tool_result: {
                                    tool_call_id: toolCallId,
                                    result: toolResult
                                }
                            };
                        }
                    }
                } catch (err) {
                    webviewView.webview.postMessage({
                        type: 'agentMessage',
                        text: `Error: ${err instanceof Error ? err.message : String(err)}`
                    });
                }
            }

            if (message.type === 'clearChat') {
                history = [];
            }
        });
    }

    private getHtml(webview: vscode.Webview): string {
        const mediaUri = vscode.Uri.joinPath(this._extensionUri, 'media');
        const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaUri, 'style.css'));
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaUri, 'main.js'));

        const htmlPath = vscode.Uri.joinPath(mediaUri, 'index.html').fsPath;
        const html = fs.readFileSync(htmlPath, 'utf8');

        return html
            .replace('{{STYLE_URI}}', styleUri.toString())
            .replace('{{SCRIPT_URI}}', scriptUri.toString())
            .replace(/\{\{CSP_SOURCE\}\}/g, webview.cspSource);
    }
}


// ── run a single tool locally via Python ──
function runLocalTool(
    pythonPath: string,
    agentPath: string,
    toolName: string,
    toolArgs: Record<string, unknown>
): Promise<string> {
    return new Promise((resolve) => {
        const payload = JSON.stringify({ tool_name: toolName, tool_args: toolArgs });
        const proc = cp.spawn(pythonPath, [agentPath]);
        proc.stdin.write(payload);
        proc.stdin.end();

        let output = '';
        proc.stdout.on('data', (data) => { output += data.toString(); });
        proc.stderr.on('data', (data) => { console.error('Tool error:', data.toString()); });

        proc.on('close', () => {
            try {
                const parsed = JSON.parse(output.trim());
                resolve(parsed.result || '');
            } catch {
                resolve(`Error executing tool: ${output}`);
            }
        });
    });
}


// ── human readable activity labels ──
function activityText(toolName: string, toolArgs: Record<string, unknown>): string {
    const basename = (p: string) => p.split(/[\\/]/).pop() || p;
    switch (toolName) {
        case 'get_file_tree': return 'Exploring project structure...';
        case 'list_files': return `Listing ${basename(String(toolArgs.path || ''))}...`;
        case 'read_file': return `Reading ${basename(String(toolArgs.path || ''))}...`;
        case 'read_lines': return `Reading ${basename(String(toolArgs.path || ''))}...`;
        case 'search_files': return `Searching for '${toolArgs.query}'...`;
        case 'replace_lines': return `Updating ${basename(String(toolArgs.path || ''))}...`;
        case 'write_file': return `Writing ${basename(String(toolArgs.path || ''))}...`;
        case 'create_file': return `Creating ${basename(String(toolArgs.path || ''))}...`;
        case 'delete_file': return `Deleting ${basename(String(toolArgs.path || ''))}...`;
        default: return `Running ${toolName}...`;
    }
}