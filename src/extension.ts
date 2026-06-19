import * as vscode from 'vscode';
import { NexusViewProvider } from './panel';

export function activate(context: vscode.ExtensionContext) {
    const provider = new NexusViewProvider(context.extensionUri);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(NexusViewProvider.viewType, provider)
    );
}

export function deactivate() {}