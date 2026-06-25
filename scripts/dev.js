#!/usr/bin/env node
/**
 * PC Doctor - Desktop start script.
 * Starts the Python backend and Tauri desktop app in parallel.
 * Works on Windows, Linux, and macOS.
 * Run with: npm run dev
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
console.log(`${CYAN}  PC Doctor (Tauri Desktop App) - Starting...${RESET}`);
console.log('  --------------------------------------------');

// Refresh PATH on Windows so node/npm are available in sub-processes
if (isWin) {
    try {
        const { execSync } = require('child_process');
        const machinePath = execSync(
            'reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment" /v Path',
            { stdio: 'pipe', encoding: 'utf8' }
        ).match(/Path\s+REG(?:_EXPAND)?_SZ\s+(.*)/i)?.[1]?.trim() ?? '';
        const userPath = execSync(
            'reg query "HKCU\\Environment" /v Path',
            { stdio: 'pipe', encoding: 'utf8' }
        ).match(/Path\s+REG(?:_EXPAND)?_SZ\s+(.*)/i)?.[1]?.trim() ?? '';
        process.env.PATH = [machinePath, userPath, process.env.PATH].filter(Boolean).join(';');
    } catch (_) {}
}

process.env.PYTHONIOENCODING = 'utf-8';

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
        // If the Tauri desktop window exits, shut down everything
        if (label.includes('Tauri')) {
            shutdown();
        }
    });
    processes.push(proc);
    return proc;
}

// ── Launch Python backend ───────────────────────────────────────────────────
launchProcess(
    'Python backend  (http://127.0.0.1:8765)',
    VENV_PYTHON,
    [path.join(BACKEND_DIR, 'main.py')],
    { cwd: BACKEND_DIR }
);

// ── Launch Tauri dev app ────────────────────────────────────────────────────
const tauriJs = path.join(ROOT_DIR, 'node_modules', '@tauri-apps', 'cli', 'tauri.js');
launchProcess(
    'Tauri Desktop Window',
    process.execPath,
    [tauriJs, 'dev'],
    { cwd: ROOT_DIR }
);

console.log('');
info('Both services are starting up.');
info('The Tauri desktop window will open shortly.');
info('Press Ctrl+C in this terminal to stop everything.');
console.log('');

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
