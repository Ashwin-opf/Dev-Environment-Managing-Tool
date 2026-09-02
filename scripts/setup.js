#!/usr/bin/env node
/**
 * PC Doctor - Cross-platform setup script.
 * Works on Windows, Linux, and macOS.
 * Run with: npm run setup
 */

'use strict';

const { spawnSync, execSync } = require('child_process');
const fs   = require('fs');
const path = require('path');

const isWin  = process.platform === 'win32';
const isMac  = process.platform === 'darwin';

const ROOT_DIR    = path.resolve(__dirname, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
const VENV_DIR    = path.join(BACKEND_DIR, '.venv');
const VENV_PYTHON = isWin
    ? path.join(VENV_DIR, 'Scripts', 'python.exe')
    : path.join(VENV_DIR, 'bin', 'python3');
const VENV_PIP    = isWin
    ? path.join(VENV_DIR, 'Scripts', 'pip.exe')
    : path.join(VENV_DIR, 'bin', 'pip3');

const GREEN  = '\x1b[32m';
const YELLOW = '\x1b[33m';
const RED    = '\x1b[31m';
const RESET  = '\x1b[0m';

function info(msg)  { console.log(`${GREEN}[ok]${RESET} ${msg}`); }
function warn(msg)  { console.log(`${YELLOW}[!]${RESET}  ${msg}`); }
function err(msg)   { console.error(`${RED}[x]${RESET}  ${msg}`); process.exit(1); }

function run(cmd, args = [], opts = {}) {
    const result = spawnSync(cmd, args, {
        stdio: 'inherit',
        env: process.env,
        shell: false,
        ...opts,
    });
    if (result.error) throw result.error;
    if (result.status !== 0 && !opts.ignoreErrors) {
        process.exit(result.status ?? 1);
    }
}

function hasCommand(cmd) {
    const r = spawnSync(cmd, ['--version'], {
        stdio: 'pipe',
        shell: isWin,
        env: process.env,
    });
    return r.status === 0;
}

// ── Refresh PATH on Windows so freshly-installed tools are visible ─────────
if (isWin) {
    try {
        const machinePath = execSync(
            'reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment" /v Path',
            { stdio: 'pipe', encoding: 'utf8' }
        ).match(/Path\s+REG(?:_EXPAND)?_SZ\s+(.*)/i)?.[1]?.trim() ?? '';
        const userPath = execSync(
            'reg query "HKCU\\Environment" /v Path',
            { stdio: 'pipe', encoding: 'utf8' }
        ).match(/Path\s+REG(?:_EXPAND)?_SZ\s+(.*)/i)?.[1]?.trim() ?? '';
        process.env.PATH = [machinePath, userPath, process.env.PATH].filter(Boolean).join(';');
    } catch (_) { /* PATH refresh optional */ }
}

console.log('');
console.log('  PC Doctor - Setup');
console.log('  -------------------------------------');

// ── Python ─────────────────────────────────────────────────────────────────
// On Windows prefer the Py launcher (py.exe) to bypass App Execution Alias stub
function findPython() {
    if (isWin && hasCommand('py')) return 'py';
    if (hasCommand('python3')) return 'python3';
    if (hasCommand('python'))  return 'python';
    return null;
}

let pythonCmd = findPython();
if (!pythonCmd) {
    warn('Python not found. Attempting install...');
    if (isWin)  run('winget', ['install', '--id', 'Python.Python.3.12', '--exact', '--silent'], { ignoreErrors: true });
    if (isMac)  run('brew',   ['install', 'python'], { ignoreErrors: true });
    pythonCmd = findPython();
    if (!pythonCmd) err('Python 3.10+ is required. Please install it manually.');
}

const pyVersionArgs = pythonCmd === 'py' ? ['-3', '--version'] : ['--version'];
const pyVer = spawnSync(pythonCmd, pyVersionArgs, { stdio: 'pipe', encoding: 'utf8' });
info(`Python found: ${(pyVer.stdout || pyVer.stderr || '').trim()}`);

// ── Node.js ─────────────────────────────────────────────────────────────────
const nodeVer = spawnSync('node', ['--version'], { stdio: 'pipe', encoding: 'utf8' });
if (nodeVer.status === 0) {
    info(`Node found: ${nodeVer.stdout.trim()}`);
} else {
    warn('Node.js not found. Attempting install...');
    if (isWin) run('winget', ['install', '--id', 'OpenJS.NodeJS.LTS', '--exact', '--silent'], { ignoreErrors: true });
    if (isMac) run('brew',   ['install', 'node'], { ignoreErrors: true });
    if (!hasCommand('node')) err('Node.js 18+ is required. Please install it manually.');
    info(`Node found: ${spawnSync('node', ['--version'], { stdio: 'pipe', encoding: 'utf8' }).stdout.trim()}`);
}

// ── Python virtual environment ──────────────────────────────────────────────
if (!fs.existsSync(VENV_DIR)) {
    info('Creating Python virtual environment...');
    const venvArgs = pythonCmd === 'py' ? ['-3', '-m', 'venv', VENV_DIR] : ['-m', 'venv', VENV_DIR];
    run(pythonCmd, venvArgs);
}

info('Installing Python backend dependencies...');
process.env.PYTHONIOENCODING = 'utf-8';
// Use python -m pip to avoid binary lock on Windows
run(VENV_PYTHON, ['-m', 'pip', 'install', '--quiet', '-r', path.join(BACKEND_DIR, 'requirements.txt')]);

info('Populating repair knowledge database...');
run(VENV_PYTHON, [path.join(BACKEND_DIR, 'populate_db.py')]);

// ── Node dependencies ───────────────────────────────────────────────────────
info('Installing Node app dependencies...');
const npmCmd = isWin ? 'npm.cmd' : 'npm';
run(npmCmd, ['install'], { cwd: ROOT_DIR, shell: isWin });

// ── Create / Update Desktop Shortcut ───────────────────────────────────────
if (fs.existsSync(path.join(ROOT_DIR, 'scripts', 'create_shortcut.js'))) {
    info('Creating / updating Desktop shortcut...');
    run('node', [path.join(ROOT_DIR, 'scripts', 'create_shortcut.js')]);
}

console.log('');
info('Setup complete. Run: npm start');
console.log('');

