#!/usr/bin/env node
/**
 * PC Doctor - Cross-platform start script.
 * Starts the Python backend and Vite frontend dev server in parallel.
 * Works on Windows, Linux, and macOS.
 * Run with: npm start
 */

'use strict';

const { spawn } = require('child_process');
const path = require('path');
const fs   = require('fs');

const isWin      = process.platform === 'win32';
const ROOT_DIR   = path.resolve(__dirname, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
const VENV_PYTHON = isWin
    ? path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe')
    : path.join(BACKEND_DIR, '.venv', 'bin', 'python3');

const GREEN  = '\x1b[32m';
const YELLOW = '\x1b[33m';
const RED    = '\x1b[31m';
const RESET  = '\x1b[0m';
const CYAN   = '\x1b[36m';

function info(msg)  { console.log(`${GREEN}[ok]${RESET} ${msg}`); }
function warn(msg)  { console.log(`${YELLOW}[!]${RESET}  ${msg}`); }
function err(msg)   { console.error(`${RED}[x]${RESET}  ${msg}`); process.exit(1); }

// ── Pre-flight checks ───────────────────────────────────────────────────────
if (!fs.existsSync(VENV_PYTHON)) {
    err(`Python backend environment not found. Run setup first:\n    ${isWin ? 'npm.cmd run setup' : 'npm run setup'}`);
}
if (!fs.existsSync(path.join(ROOT_DIR, 'node_modules'))) {
    err(`Node dependencies missing. Run setup first:\n    ${isWin ? 'npm.cmd run setup' : 'npm run setup'}`);
}

console.log('');
// Cross-platform pre-flight port cleanup (Windows, Linux, macOS)
try {
    const { execSync } = require('child_process');
    if (isWin) {
        execSync('powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5173,8765 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"', { stdio: 'ignore' });
    } else {
        execSync('fuser -k 5173/tcp 8765/tcp 2>/dev/null || true', { stdio: 'ignore' });
    }
} catch (_) {}

// Quick pre-check: ensure dist exists
const distDir = path.join(ROOT_DIR, 'frontend', 'dist');
if (!fs.existsSync(distDir)) {
    try {
        const { execSync } = require('child_process');
        info('Building frontend assets...');
        execSync('npm --prefix frontend run build', { stdio: 'ignore' });
    } catch (_) {}
}

process.env.PYTHONIOENCODING = 'utf-8';
process.env.API_RELOAD = 'true';

const processes = [];

function launchProcess(label, cmd, args, opts = {}) {
    info(`Starting ${label}...`);
    const proc = spawn(cmd, args, {
        stdio: 'inherit',
        shell: false,
        env: process.env,
        cwd: opts.cwd || ROOT_DIR,
        ...opts,
    });
    proc.on('error', (e) => {
        warn(`${label} error: ${e.message}`);
    });
    proc.on('exit', (code) => {
        if (code !== 0 && code !== null) {
            warn(`${label} exited with code ${code}`);
        }
    });
    processes.push(proc);
    return proc;
}

// ── File watcher for frontend live auto-build & auto-update ─────────────────
let buildTimeout = null;
const frontendDir = path.join(ROOT_DIR, 'frontend');
const WATCH_FILES = new Set(['main.js', 'style.css', 'index.html', 'animations.js']);
try {
    fs.watch(frontendDir, { recursive: false }, (eventType, filename) => {
        if (!filename || !WATCH_FILES.has(filename)) return;
        if (buildTimeout) clearTimeout(buildTimeout);
        buildTimeout = setTimeout(() => {
            try {
                const { execSync } = require('child_process');
                execSync('npm --prefix frontend run build', { stdio: 'ignore' });
                info(`[Auto-Update] Built changes in frontend/${filename}`);
            } catch (_) {}
        }, 300);
    });
    info('Live auto-reload watcher active for code updates.');
} catch (_) {}

// ── Launch Python backend ───────────────────────────────────────────────────
launchProcess(
    'Python backend  (http://127.0.0.1:8765)',
    VENV_PYTHON,
    [path.join(BACKEND_DIR, 'main.py')],
    { cwd: BACKEND_DIR }
);

// ── Launch Vite frontend dev server ─────────────────────────────────────────
const viteCli = path.join(ROOT_DIR, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js');
launchProcess(
    'Frontend dev server  (http://localhost:5173)',
    process.execPath,
    [viteCli, '--port', '5173', '--strictPort'],
    { cwd: path.join(ROOT_DIR, 'frontend') }
);

console.log('');
info('Both backend and frontend services are active with auto-update enabled.');
info('Launching PC Doctor Desktop App Window...');
info('Press Ctrl+C to stop servers when done.');
console.log('');

// ── Dynamic 100% Platform-Independent Browser / App Window Finder ───────────
function findAppBrowserExecutable() {
    const isWin = process.platform === 'win32';
    const isMac = process.platform === 'darwin';
    const { execSync } = require('child_process');

    if (isWin) {
        const pf = process.env.PROGRAMFILES || 'C:\\Program Files';
        const pfx86 = process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)';
        const localAppData = process.env.LOCALAPPDATA || '';
        const winCandidates = [
            path.join(pfx86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
            path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
            path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            path.join(pfx86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            path.join(localAppData, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            path.join(localAppData, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
            path.join(localAppData, 'Vivaldi', 'Application', 'vivaldi.exe'),
            path.join(localAppData, 'Programs', 'Opera', 'opera.exe'),
            path.join(pf, 'Vivaldi', 'Application', 'vivaldi.exe'),
            path.join(pf, 'Opera', 'opera.exe'),
        ];
        for (const c of winCandidates) {
            if (fs.existsSync(c)) return c;
        }
        try {
            const out = execSync('where msedge chrome brave vivaldi opera thorium arc', { stdio: 'pipe', encoding: 'utf8' });
            const found = out.split(/\r?\n/).map(s => s.trim()).filter(Boolean)[0];
            if (found && fs.existsSync(found)) return found;
        } catch (_) {}
    } else if (isMac) {
        const macCandidates = [
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
            '/Applications/Vivaldi.app/Contents/MacOS/Vivaldi',
            '/Applications/Opera.app/Contents/MacOS/Opera',
            '/Applications/Arc.app/Contents/MacOS/Arc',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ];
        for (const c of macCandidates) {
            if (fs.existsSync(c)) return c;
        }
    } else {
        // Linux / BSD - dynamically search PATH for any installed browser
        const linuxBinaries = [
            'microsoft-edge-stable',
            'microsoft-edge',
            'google-chrome-stable',
            'google-chrome',
            'chromium-browser',
            'chromium',
            'brave-browser',
            'vivaldi-stable',
            'vivaldi',
            'opera',
            'yandex-browser',
            'thorium-browser',
            'epiphany',
            'falkon',
        ];
        for (const bin of linuxBinaries) {
            try {
                const out = execSync(`which ${bin}`, { stdio: 'pipe', encoding: 'utf8' }).trim();
                if (out && fs.existsSync(out)) return out;
            } catch (_) {}
        }
    }
    return null;
}

// Automatically launch PC Doctor in standalone desktop app window mode
setTimeout(() => {
    try {
        const browserExe = findAppBrowserExecutable();
        if (browserExe) {
            const { spawn } = require('child_process');
            spawn(browserExe, [
                '--app=http://localhost:5173',
                '--window-size=1440,900',
                '--user-data-dir=' + path.join(ROOT_DIR, '.pc-doctor-profile')
            ], { detached: true, stdio: 'ignore' });
        } else {
            const { exec } = require('child_process');
            const openCmd = isWin 
                ? 'start http://localhost:5173' 
                : (process.platform === 'darwin' ? 'open http://localhost:5173' : 'xdg-open http://localhost:5173');
            exec(openCmd);
        }
    } catch (_) {}
}, 1200);

// ── Graceful shutdown ────────────────────────────────────────────────────────
function shutdown() {
    warn('Shutting down...');
    for (const p of processes) {
        try { p.kill('SIGTERM'); } catch (_) {}
    }
    process.exit(0);
}

process.on('SIGINT',  shutdown);
process.on('SIGTERM', shutdown);
