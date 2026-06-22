import * as vscode from 'vscode';
import { AtlasViewProvider } from './panel';

export function activate(context: vscode.ExtensionContext) {
    const provider = new AtlasViewProvider(context.extensionUri);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(AtlasViewProvider.viewType, provider)
    );
}

export function deactivate() {}