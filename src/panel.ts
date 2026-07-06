import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

const SERVER_URL = "https://atlas-code-server.onrender.com";

// Safety rails for the agentic loop.
const MAX_AGENT_STEPS = 30;
const FETCH_TIMEOUT_MS = 120_000;
const TOOL_TIMEOUT_MS = 60_000;
const MAX_REFERENCED_FILE_BYTES = 100_000;
const FILE_LIST_LIMIT = 400;

const FILE_LIST_EXCLUDE = '{**/node_modules/**,**/.git/**,**/venv/**,**/.venv/**,**/__pycache__/**,**/out/**,**/dist/**,**/.next/**}';

export class AtlasViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'atlas.chatView';

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

            // ── @ mention support: webview asks for the workspace file list ──
            if (message.type === 'requestFiles') {
                try {
                    const uris = await vscode.workspace.findFiles('**/*', FILE_LIST_EXCLUDE, FILE_LIST_LIMIT);
                    const files = uris.map(u => vscode.workspace.asRelativePath(u, false)).sort();
                    webviewView.webview.postMessage({ type: 'fileList', files });
                } catch {
                    webviewView.webview.postMessage({ type: 'fileList', files: [] });
                }
                return;
            }

            // ── chat ──
            if (message.type === 'userMessage') {
                const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
                const referencedFiles: string[] = Array.isArray(message.files) ? message.files : [];

                // Inject @-referenced file contents as labeled context blocks.
                // The host does the reading (the webview has no fs access).
                const fullMessage = await buildMessageWithFileContext(message.text, referencedFiles, workspacePath);
                history.push({ role: 'user', content: fullMessage });

                const agentPath = path.join(this._extensionUri.fsPath, 'agent', 'agent.py');
                const pythonPath = 'python';

                // Whatever happens below, the webview must receive exactly one
                // terminal message so the input never stays locked.
                let finished = false;
                const finish = (type: 'agentMessage' | 'agentError', text: string) => {
                    if (finished) { return; }
                    finished = true;
                    webviewView.webview.postMessage({ type, text });
                };

                try {
                    let requestBody: Record<string, unknown> = {
                        message: fullMessage,
                        workspace: workspacePath,
                        history: history
                    };

                    for (let step = 0; step < MAX_AGENT_STEPS; step++) {
                        const data = await postToServer(requestBody);

                        if (data.status === 'done') {
                            const finalMessage = data.message || '';
                            history.push({ role: 'assistant', content: finalMessage });
                            finish('agentMessage', finalMessage);
                            return;
                        }

                        if (data.status === 'tool_call' && data.tool_name && data.tool_call_id && data.messages) {
                            webviewView.webview.postMessage({
                                type: 'activityUpdate',
                                text: activityText(data.tool_name, data.tool_args || {})
                            });

                            const toolResult = await runLocalTool(pythonPath, agentPath, data.tool_name, data.tool_args || {});

                            requestBody = {
                                messages: data.messages,
                                tool_result: {
                                    tool_call_id: data.tool_call_id,
                                    result: toolResult
                                }
                            };
                            continue;
                        }

                        // status === 'error' or a shape we don't recognize
                        throw new Error(data.message || 'The server returned an unexpected response.');
                    }

                    throw new Error(`The task exceeded ${MAX_AGENT_STEPS} steps and was stopped. Try breaking it into smaller requests.`);
                } catch (err) {
                    finish('agentError', friendlyError(err));
                }
                return;
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


interface ServerResponse {
    status: string;
    message?: string;
    tool_name?: string;
    tool_args?: Record<string, unknown>;
    tool_call_id?: string;
    messages?: unknown[];
}

// ── one round trip to the server, with timeout and non-JSON protection ──
async function postToServer(requestBody: Record<string, unknown>): Promise<ServerResponse> {
    let response: Response;
    try {
        response = await fetch(`${SERVER_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
            signal: AbortSignal.timeout(FETCH_TIMEOUT_MS)
        });
    } catch (err) {
        if (err instanceof Error && err.name === 'TimeoutError') {
            throw new Error('The server took too long to respond. It may be waking up — please try again in a moment.');
        }
        throw new Error('Could not reach the Atlas server. Check your internet connection and try again.');
    }

    // Read as text first: proxies and cold starts can return HTML/plain-text
    // error pages that would make response.json() throw uninformatively.
    const text = await response.text();
    let data: ServerResponse;
    try {
        data = JSON.parse(text) as ServerResponse;
    } catch {
        throw new Error(`The server returned an invalid response (HTTP ${response.status}). Please try again shortly.`);
    }
    return data;
}


// ── @ mention context injection ──
async function buildMessageWithFileContext(text: string, files: string[], workspacePath: string): Promise<string> {
    if (!files.length || !workspacePath) { return text; }

    const blocks: string[] = [];
    for (const relPath of files) {
        const absPath = path.resolve(workspacePath, relPath);
        // Only inject files that actually live inside the workspace.
        if (!absPath.startsWith(path.resolve(workspacePath))) { continue; }
        try {
            const stat = await fs.promises.stat(absPath);
            if (!stat.isFile()) { continue; }
            let content: string;
            if (stat.size > MAX_REFERENCED_FILE_BYTES) {
                const fd = await fs.promises.open(absPath, 'r');
                try {
                    const buf = Buffer.alloc(MAX_REFERENCED_FILE_BYTES);
                    const { bytesRead } = await fd.read(buf, 0, MAX_REFERENCED_FILE_BYTES, 0);
                    content = buf.toString('utf8', 0, bytesRead) + '\n[... file truncated ...]';
                } finally {
                    await fd.close();
                }
            } else {
                content = await fs.promises.readFile(absPath, 'utf8');
            }
            blocks.push(`Referenced file: ${relPath}\n\`\`\`\n${content}\n\`\`\``);
        } catch {
            blocks.push(`Referenced file: ${relPath} (could not be read)`);
        }
    }

    return blocks.length ? `${text}\n\n${blocks.join('\n\n')}` : text;
}


// ── run a single tool locally via Python ──
// Always resolves (never rejects): failures become error strings that are fed
// back to the model as the tool result so it can adapt.
function runLocalTool(
    pythonPath: string,
    agentPath: string,
    toolName: string,
    toolArgs: Record<string, unknown>
): Promise<string> {
    return new Promise((resolve) => {
        let settled = false;
        const settle = (result: string) => {
            if (settled) { return; }
            settled = true;
            clearTimeout(timer);
            resolve(result);
        };

        let proc: cp.ChildProcess;
        try {
            proc = cp.spawn(pythonPath, [agentPath]);
        } catch (err) {
            resolve(`Error: could not start the local tool process: ${err instanceof Error ? err.message : String(err)}`);
            return;
        }

        const timer = setTimeout(() => {
            proc.kill();
            settle(`Error: tool '${toolName}' timed out after ${TOOL_TIMEOUT_MS / 1000}s and was stopped.`);
        }, TOOL_TIMEOUT_MS);

        // Fires when the executable itself can't be launched (e.g. python not on PATH).
        proc.on('error', (err) => {
            settle(`Error: could not run Python to execute tools (${err.message}). Make sure Python 3 is installed and on your PATH.`);
        });

        let output = '';
        let errOutput = '';
        proc.stdout?.on('data', (data) => { output += data.toString(); });
        proc.stderr?.on('data', (data) => { errOutput += data.toString(); });

        proc.on('close', () => {
            try {
                const parsed = JSON.parse(output.trim());
                settle(typeof parsed.result === 'string' ? parsed.result : JSON.stringify(parsed.result ?? ''));
            } catch {
                const detail = errOutput.trim() || output.trim() || 'no output';
                settle(`Error executing tool '${toolName}': ${detail.slice(0, 2000)}`);
            }
        });

        try {
            proc.stdin?.write(JSON.stringify({ tool_name: toolName, tool_args: toolArgs }));
            proc.stdin?.end();
        } catch (err) {
            settle(`Error: could not send input to the tool process: ${err instanceof Error ? err.message : String(err)}`);
        }
    });
}


// ── user-facing error text ──
function friendlyError(err: unknown): string {
    const raw = err instanceof Error ? err.message : String(err);
    return raw || 'Something went wrong while processing your request. Please try again.';
}


// ── activity labels (terminal-flavored) ──
function activityText(toolName: string, toolArgs: Record<string, unknown>): string {
    const basename = (p: unknown) => String(p || '').split(/[\\/]/).pop() || '';
    switch (toolName) {
        case 'get_file_tree': return 'Running ls -R...';
        case 'list_files': return 'Running ls...';
        case 'read_file': return `Reading ${basename(toolArgs.path) || 'file'}...`;
        case 'read_lines': return `Reading lines ${toolArgs.start_line ?? ''}-${toolArgs.end_line ?? ''} of ${basename(toolArgs.path) || 'file'}...`;
        case 'search_files': return `Running grep "${toolArgs.query ?? ''}"...`;
        case 'find_files': return `Running find "${toolArgs.pattern ?? ''}"...`;
        case 'get_file_info': return `Running stat ${basename(toolArgs.path) || ''}...`;
        case 'replace_lines': return `Editing ${basename(toolArgs.path) || 'file'}...`;
        case 'write_file': return `Writing ${basename(toolArgs.path) || 'file'}...`;
        case 'create_file': return `Creating ${basename(toolArgs.path) || 'file'}...`;
        case 'delete_file': return `Removing ${basename(toolArgs.path) || 'file'}...`;
        case 'create_directory': return `Running mkdir ${basename(toolArgs.path) || ''}...`;
        case 'rename_file': return `Running mv ${basename(toolArgs.source) || ''}...`;
        default:
            if (/web|fetch|http|url|search_internet/i.test(toolName)) { return 'Fetching...'; }
            return `Running ${toolName}...`;
    }
}
