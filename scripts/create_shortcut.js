#!/usr/bin/env node
/**
 * PC Doctor - Cross-Platform Desktop Shortcut Creator & Updater
 * Supports Windows (.lnk), Linux (.desktop), and macOS (.command/.app).
 */

'use strict';

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT_DIR = path.resolve(__dirname, '..');
const platform = process.platform;
const homeDir = os.homedir();

const iconIco = path.join(ROOT_DIR, 'src-tauri', 'icons', 'icon.ico');
const iconPng = path.join(ROOT_DIR, 'src-tauri', 'icons', '128x128.png');

if (platform === 'win32') {
    // ── Windows Shortcut (.lnk / .exe) ─────────────────────────────────────────
    const desktopDir = path.join(process.env.USERPROFILE || homeDir, 'Desktop');
    const exePath = path.join(desktopDir, 'PC Doctor.exe');
    const shortcutPath = path.join(desktopDir, 'PC Doctor.lnk');
    const tauriExe = path.join(ROOT_DIR, 'src-tauri', 'target', 'debug', 'app.exe');
    const tauriDll = path.join(ROOT_DIR, 'src-tauri', 'target', 'debug', 'WebView2Loader.dll');
    const dllPath = path.join(desktopDir, 'WebView2Loader.dll');

    if (fs.existsSync(tauriExe)) {
        try {
            fs.copyFileSync(tauriExe, exePath);
            if (fs.existsSync(tauriDll)) {
                fs.copyFileSync(tauriDll, dllPath);
            }
            console.log(`[ok] Updated Windows Executable & WebView2Loader.dll on Desktop`);
        } catch (_) {}
    }

    const startJsPath = path.join(ROOT_DIR, 'scripts', 'start.js');
    const nodeExe = process.execPath;

    let targetPath = nodeExe;
    let targetArgs = `"${startJsPath}"`;

    if (fs.existsSync(tauriExe)) {
        targetPath = tauriExe;
        targetArgs = '';
    }

    const startMenuDir = path.join(process.env.APPDATA || path.join(homeDir, 'AppData', 'Roaming'), 'Microsoft', 'Windows', 'Start Menu', 'Programs');
    const startMenuShortcutPath = path.join(startMenuDir, 'PC Doctor.lnk');

    const psScript = `
$wsh = New-Object -ComObject WScript.Shell

# 1. Desktop Shortcut
$desktopShortcut = $wsh.CreateShortcut('${shortcutPath.replace(/'/g, "''")}')
$desktopShortcut.TargetPath = '${targetPath.replace(/'/g, "''")}'
$desktopShortcut.Arguments = '${targetArgs.replace(/'/g, "''")}'
$desktopShortcut.WorkingDirectory = '${ROOT_DIR.replace(/'/g, "''")}'
$desktopShortcut.IconLocation = '${iconIco.replace(/'/g, "''")}'
$desktopShortcut.Description = 'PC Doctor Desktop Application'
$desktopShortcut.Save()

# 2. Windows Start Menu (Windows Home) Shortcut
$startShortcut = $wsh.CreateShortcut('${startMenuShortcutPath.replace(/'/g, "''")}')
$startShortcut.TargetPath = '${targetPath.replace(/'/g, "''")}'
$startShortcut.Arguments = '${targetArgs.replace(/'/g, "''")}'
$startShortcut.WorkingDirectory = '${ROOT_DIR.replace(/'/g, "''")}'
$startShortcut.IconLocation = '${iconIco.replace(/'/g, "''")}'
$startShortcut.Description = 'PC Doctor Desktop Application'
$startShortcut.Save()
`;

    try {
        const encoded = Buffer.from(psScript, 'utf16le').toString('base64');
        execSync(`powershell -NoProfile -EncodedCommand ${encoded}`, { stdio: 'inherit' });
        console.log(`[ok] Windows Desktop shortcut created at:\n    ${shortcutPath}`);
        console.log(`[ok] Windows Start Menu shortcut created at:\n    ${startMenuShortcutPath}`);
    } catch (err) {
        console.error(`[x] Shortcut creation error: ${err.message}`);
    }

} else if (platform === 'linux') {
    // ── Linux Desktop Shortcut (.desktop) ─────────────────────────────────────
    const desktopDir = path.join(homeDir, 'Desktop');
    const appDir = path.join(homeDir, '.local', 'share', 'applications');

    if (!fs.existsSync(appDir)) {
        fs.mkdirSync(appDir, { recursive: true });
    }

    const desktopContent = `[Desktop Entry]
Name=PC Doctor
Comment=Intelligent System Repair & Health Monitor
Exec=npm --prefix "${ROOT_DIR}" start
Icon=${iconPng}
Terminal=false
Type=Application
Categories=Utility;System;
StartupNotify=true
Path=${ROOT_DIR}
`;

    const desktopFileApp = path.join(appDir, 'pc-doctor.desktop');
    fs.writeFileSync(desktopFileApp, desktopContent, 'utf8');
    fs.chmodSync(desktopFileApp, '755');
    console.log(`[ok] Linux Application Entry created: ${desktopFileApp}`);

    if (fs.existsSync(desktopDir)) {
        const desktopFileUser = path.join(desktopDir, 'pc-doctor.desktop');
        fs.writeFileSync(desktopFileUser, desktopContent, 'utf8');
        fs.chmodSync(desktopFileUser, '755');
        console.log(`[ok] Linux Desktop Shortcut created: ${desktopFileUser}`);
    }

} else if (platform === 'darwin') {
    // ── macOS Launcher (.command) ─────────────────────────────────────────────
    const desktopDir = path.join(homeDir, 'Desktop');
    const commandPath = path.join(desktopDir, 'PC Doctor.command');
    const commandContent = `#!/bin/bash
cd "${ROOT_DIR}"
npm start
`;
    fs.writeFileSync(commandPath, commandContent, 'utf8');
    fs.chmodSync(commandPath, '755');
    console.log(`[ok] macOS Launcher created: ${commandPath}`);
}
