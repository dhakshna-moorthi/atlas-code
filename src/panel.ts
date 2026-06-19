import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

export class NexusViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'nexus.chatView';

    constructor(private readonly _extensionUri: vscode.Uri) {}

    resolveWebviewView(webviewView: vscode.WebviewView) {
        const mediaUri = vscode.Uri.joinPath(this._extensionUri, 'media');

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [mediaUri]
        };

        webviewView.webview.html = this.getHtml(webviewView.webview);

        let history: { role: string; content: string }[] = [];

        webviewView.webview.onDidReceiveMessage(message => {
            if (message.type === 'validateKey') {
                const envPath = path.join(this._extensionUri.fsPath, '.env');
                let password = '';
                try {
                    const envContent = fs.readFileSync(envPath, 'utf8');
                    const match = envContent.match(/^PASSWORD=(.+)$/m);
                    if (match) { password = match[1].trim(); }
                } catch {}
                webviewView.webview.postMessage({
                    type: 'keyResult',
                    valid: message.key === password
                });
                return;
            }

            if (message.type === 'userMessage') {
                const agentPath = path.join(this._extensionUri.fsPath, 'agent', 'agent.py');
                const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';

                history.push({ role: 'user', content: message.text });

                const payload = JSON.stringify({
                    message: message.text,
                    model: message.model,
                    workspace: workspacePath,
                    history: history
                });

                const pythonPath = path.join(this._extensionUri.fsPath, 'venv', 'Scripts', 'python.exe');
                const proc = cp.spawn(pythonPath, [agentPath]);
                proc.stdin.write(payload);
                proc.stdin.end();

                let lineBuffer = '';
                let finalResult: { status: string; message: string } | null = null;

                proc.stdout.on('data', (data) => {
                    lineBuffer += data.toString();
                    const lines = lineBuffer.split('\n');
                    lineBuffer = lines.pop() ?? '';
                    for (const line of lines) {
                        const trimmed = line.trim();
                        if (!trimmed) { continue; }
                        try {
                            const parsed = JSON.parse(trimmed);
                            if (parsed.type === 'activity') {
                                webviewView.webview.postMessage({ type: 'activityUpdate', text: parsed.text });
                            } else if (parsed.type === 'response') {
                                finalResult = parsed;
                            }
                        } catch { /* ignore malformed lines */ }
                    }
                });

                proc.stderr.on('data', (data) => {
                    console.error('Python error:', data.toString());
                });

                proc.on('close', () => {
                    if (lineBuffer.trim()) {
                        try {
                            const parsed = JSON.parse(lineBuffer.trim());
                            if (parsed.type === 'response') { finalResult = parsed; }
                        } catch { /* ignore */ }
                    }
                    if (finalResult && finalResult.message) {
                        history.push({ role: 'assistant', content: finalResult.message });
                        webviewView.webview.postMessage({ type: 'agentMessage', text: finalResult.message });
                    } else {
                        webviewView.webview.postMessage({ type: 'agentMessage', text: 'Error: no response from agent.' });
                    }
                });
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
