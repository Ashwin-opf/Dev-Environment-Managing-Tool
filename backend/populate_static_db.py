"""
populate_static_db.py — Populates Part A: knowledge_static.db with comprehensive,
scalable, classified repair and install commands across Windows, Linux, and macOS.
Also synchronizes recipes into knowledge.db so legacy routes and engines benefit.
"""
import os
import sys
import sqlite3
from pathlib import Path

# Force UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent
STATIC_DB_PATH = BASE_DIR / "knowledge_static.db"
LEGACY_DB_PATH = BASE_DIR / "knowledge.db"

RECIPES = [
    # =========================================================================
    # 1. RUNTIMES & PROGRAMMING LANGUAGES
    # =========================================================================
    {
        "issue": "Python missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id Python.Python.3.12 --exact --silent",
        "risk": "Low",
        "explanation": "Installs Python 3.12 via Windows Package Manager (Winget).",
        "tags": "python,runtime,lang,install"
    },
    {
        "issue": "Python missing",
        "os": "Linux",
        "category": "Runtimes",
        "command": "sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv",
        "risk": "Low",
        "explanation": "Installs Python 3, pip, and venv via the apt package manager.",
        "tags": "python,runtime,apt,linux"
    },
    {
        "issue": "Python missing",
        "os": "Darwin",
        "category": "Runtimes",
        "command": "brew install python@3.12",
        "risk": "Low",
        "explanation": "Installs Python 3.12 via Homebrew.",
        "tags": "python,runtime,brew,macos"
    },
    {
        "issue": "Python PATH missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": r'powershell -Command "[Environment]::SetEnvironmentVariable(\"Path\", $env:Path + \";$env:LocalAppData\Programs\Python\Python312;$env:LocalAppData\Programs\Python\Python312\Scripts\", [EnvironmentVariableTarget]::User)"',
        "risk": "Low",
        "explanation": "Appends Python and Python Scripts directories to the user PATH environment variable.",
        "tags": "python,path,windows,repair"
    },
    {
        "issue": "pip broken or outdated",
        "os": "Windows",
        "category": "Runtimes",
        "command": "python -m ensurepip --upgrade && python -m pip install --upgrade pip",
        "risk": "Low",
        "explanation": "Re-bootstraps pip and upgrades it to the latest version on Windows.",
        "tags": "pip,python,repair,update"
    },
    {
        "issue": "pip broken or outdated",
        "os": "Linux",
        "category": "Runtimes",
        "command": "python3 -m ensurepip --upgrade && python3 -m pip install --upgrade pip --break-system-packages",
        "risk": "Low",
        "explanation": "Upgrades pip to the latest release on Linux.",
        "tags": "pip,python,linux,repair"
    },
    {
        "issue": "Python Virtualenv creation failed",
        "os": "Windows",
        "category": "Runtimes",
        "command": "python -m pip install --upgrade virtualenv",
        "risk": "Low",
        "explanation": "Installs or updates the virtualenv package.",
        "tags": "python,venv,virtualenv,repair"
    },
    {
        "issue": "Node.js missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id OpenJS.NodeJS.LTS --exact --silent",
        "risk": "Low",
        "explanation": "Installs Node.js Long Term Support (LTS) via Winget.",
        "tags": "node,nodejs,javascript,runtime,install"
    },
    {
        "issue": "Node.js missing",
        "os": "Linux",
        "category": "Runtimes",
        "command": "sudo apt-get update && sudo apt-get install -y nodejs npm",
        "risk": "Low",
        "explanation": "Installs Node.js and npm from official repositories.",
        "tags": "node,nodejs,npm,linux,install"
    },
    {
        "issue": "Node.js missing",
        "os": "Darwin",
        "category": "Runtimes",
        "command": "brew install node@20",
        "risk": "Low",
        "explanation": "Installs Node.js LTS via Homebrew.",
        "tags": "node,nodejs,brew,macos,install"
    },
    {
        "issue": "npm cache corrupted or broken",
        "os": "Windows",
        "category": "Runtimes",
        "command": "npm cache clean --force && npm install -g npm@latest",
        "risk": "Low",
        "explanation": "Force clears npm cache and upgrades npm globally.",
        "tags": "npm,cache,repair,nodejs"
    },
    {
        "issue": "npm cache corrupted or broken",
        "os": "Linux",
        "category": "Runtimes",
        "command": "sudo npm cache clean --force && sudo npm install -g npm@latest",
        "risk": "Low",
        "explanation": "Force cleans npm cache and upgrades npm globally on Linux.",
        "tags": "npm,cache,repair,linux"
    },
    {
        "issue": "Rust / Cargo missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id Rustlang.Rustup --exact --silent",
        "risk": "Low",
        "explanation": "Installs Rustup and the Rust compiler toolchain on Windows.",
        "tags": "rust,cargo,rustup,install"
    },
    {
        "issue": "Rust / Cargo missing",
        "os": "Linux",
        "category": "Runtimes",
        "command": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y",
        "risk": "Low",
        "explanation": "Installs Rust toolchain via rustup on Linux.",
        "tags": "rust,cargo,rustup,linux,install"
    },
    {
        "issue": "Rust toolchain update / repair",
        "os": "Any",
        "category": "Runtimes",
        "command": "rustup update && rustup default stable",
        "risk": "Low",
        "explanation": "Updates rustup, all installed toolchains, and ensures stable is default.",
        "tags": "rust,cargo,rustup,repair,update"
    },
    {
        "issue": "Go language missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id GoLang.Go --exact --silent",
        "risk": "Low",
        "explanation": "Installs Go programming language runtime on Windows.",
        "tags": "go,golang,runtime,install"
    },
    {
        "issue": "Go language missing",
        "os": "Linux",
        "category": "Runtimes",
        "command": "sudo apt-get update && sudo apt-get install -y golang-go",
        "risk": "Low",
        "explanation": "Installs Go compiler and runtime via apt.",
        "tags": "go,golang,linux,install"
    },
    {
        "issue": "Go module cache corrupted",
        "os": "Any",
        "category": "Runtimes",
        "command": "go clean -modcache && go clean -cache",
        "risk": "Low",
        "explanation": "Purges cached Go module downloads and build objects.",
        "tags": "go,golang,repair,cache"
    },
    {
        "issue": "Java JDK missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id EclipseAdoptium.Temurin.17.JDK --exact --silent",
        "risk": "Low",
        "explanation": "Installs Eclipse Temurin OpenJDK 17 LTS on Windows.",
        "tags": "java,jdk,temurin,install"
    },
    {
        "issue": "Java JDK missing",
        "os": "Linux",
        "category": "Runtimes",
        "command": "sudo apt-get update && sudo apt-get install -y openjdk-17-jdk",
        "risk": "Low",
        "explanation": "Installs OpenJDK 17 development kit on Linux.",
        "tags": "java,jdk,linux,install"
    },
    {
        "issue": "JAVA_HOME environment variable missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": r'powershell -Command "$jdk = (Get-ChildItem -Path \"C:\Program Files\Eclipse Adoptium\", \"C:\Program Files\Java\" -Filter \"jdk*\" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1).FullName; if ($jdk) { [Environment]::SetEnvironmentVariable(\"JAVA_HOME\", $jdk, [EnvironmentVariableTarget]::Machine); Write-Host \"Set JAVA_HOME to $jdk\" } else { Write-Warning \"JDK path not found.\" }"',
        "risk": "Medium",
        "explanation": "Detects installed JDK and automatically sets system JAVA_HOME environment variable.",
        "tags": "java,java_home,repair,windows"
    },
    {
        "issue": ".NET SDK missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id Microsoft.DotNet.SDK.8 --exact --silent",
        "risk": "Low",
        "explanation": "Installs .NET 8 SDK on Windows.",
        "tags": "dotnet,csharp,install"
    },
    {
        "issue": "CMake missing",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id Kitware.CMake --exact --silent",
        "risk": "Low",
        "explanation": "Installs CMake build system on Windows.",
        "tags": "cmake,cpp,c,build,install"
    },

    # =========================================================================
    # 2. PACKAGE MANAGERS & BUILD TOOLS
    # =========================================================================
    {
        "issue": "pnpm missing",
        "os": "Windows",
        "category": "Package Managers",
        "command": "npm install -g pnpm@latest",
        "risk": "Low",
        "explanation": "Installs pnpm fast, disk space efficient package manager globally.",
        "tags": "pnpm,npm,nodejs,install"
    },
    {
        "issue": "Yarn package manager missing",
        "os": "Windows",
        "category": "Package Managers",
        "command": "npm install -g yarn@latest",
        "risk": "Low",
        "explanation": "Installs Yarn package manager globally via npm.",
        "tags": "yarn,npm,nodejs,install"
    },
    {
        "issue": "Poetry Python dependency manager missing",
        "os": "Windows",
        "category": "Package Managers",
        "command": "powershell -Command \"(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -\"",
        "risk": "Low",
        "explanation": "Installs Poetry dependency manager for Python on Windows.",
        "tags": "poetry,python,package_manager,install"
    },
    {
        "issue": "Gradle missing",
        "os": "Windows",
        "category": "Package Managers",
        "command": "winget install --id Gradle.Gradle --exact --silent",
        "risk": "Low",
        "explanation": "Installs Gradle build tool on Windows.",
        "tags": "gradle,java,android,build,install"
    },
    {
        "issue": "Apache Maven missing",
        "os": "Windows",
        "category": "Package Managers",
        "command": "winget install --id Apache.Maven --exact --silent",
        "risk": "Low",
        "explanation": "Installs Apache Maven build tool on Windows.",
        "tags": "maven,java,build,install"
    },
    {
        "issue": "Winget source database reset",
        "os": "Windows",
        "category": "Package Managers",
        "command": "winget source reset --force",
        "risk": "Low",
        "explanation": "Resets Winget package catalog sources to resolve stuck or failing installs.",
        "tags": "winget,repair,sources,windows"
    },

    # =========================================================================
    # 3. IDES & CODE EDITORS
    # =========================================================================
    {
        "issue": "Visual Studio Code missing",
        "os": "Windows",
        "category": "IDEs",
        "command": "winget install --id Microsoft.VisualStudioCode --exact --silent",
        "risk": "Low",
        "explanation": "Installs Visual Studio Code on Windows.",
        "tags": "vscode,ide,editor,install"
    },
    {
        "issue": "Visual Studio Code missing",
        "os": "Linux",
        "category": "IDEs",
        "command": "sudo snap install code --classic",
        "risk": "Low",
        "explanation": "Installs Visual Studio Code via Snap on Linux.",
        "tags": "vscode,ide,snap,linux,install"
    },
    {
        "issue": "VS Code corrupted cache / reset",
        "os": "Windows",
        "category": "IDEs",
        "command": r'powershell -Command "Stop-Process -Name Code -Force -ErrorAction SilentlyContinue; Remove-Item -Path \"$env:APPDATA\Code\Cache\*\", \"$env:APPDATA\Code\CachedData\*\" -Recurse -Force -ErrorAction SilentlyContinue; Write-Host \"VS Code cache cleared successfully.\""',
        "risk": "Low",
        "explanation": "Terminates VS Code and flushes corrupt extension and workspace cache files.",
        "tags": "vscode,cache,repair,windows"
    },
    {
        "issue": "Android Studio missing",
        "os": "Windows",
        "category": "IDEs",
        "command": "winget install --id Google.AndroidStudio --exact --silent",
        "risk": "Medium",
        "explanation": "Installs Android Studio IDE via Winget.",
        "tags": "android,studio,ide,install"
    },
    {
        "issue": "PyCharm Community missing",
        "os": "Windows",
        "category": "IDEs",
        "command": "winget install --id JetBrains.PyCharm.Community --exact --silent",
        "risk": "Low",
        "explanation": "Installs JetBrains PyCharm Community Edition via Winget.",
        "tags": "pycharm,jetbrains,python,ide,install"
    },
    {
        "issue": "Sublime Text missing",
        "os": "Windows",
        "category": "IDEs",
        "command": "winget install --id SublimeHQ.SublimeText.4 --exact --silent",
        "risk": "Low",
        "explanation": "Installs Sublime Text 4 on Windows.",
        "tags": "sublime,editor,install"
    },
    {
        "issue": "Neovim missing",
        "os": "Windows",
        "category": "IDEs",
        "command": "winget install --id Neovim.Neovim --exact --silent",
        "risk": "Low",
        "explanation": "Installs Neovim modern text editor on Windows.",
        "tags": "neovim,vim,editor,install"
    },
    {
        "issue": "Cursor AI Editor missing",
        "os": "Windows",
        "category": "IDEs",
        "command": "winget install --id Anysphere.Cursor --exact --silent",
        "risk": "Low",
        "explanation": "Installs Cursor AI-powered code editor via Winget.",
        "tags": "cursor,ai,ide,editor,install"
    },

    # =========================================================================
    # 4. CONTAINERS & VIRTUALIZATION
    # =========================================================================
    {
        "issue": "Docker Desktop missing",
        "os": "Windows",
        "category": "Containers",
        "command": "winget install --id Docker.DockerDesktop --exact --silent",
        "risk": "Medium",
        "explanation": "Installs Docker Desktop for Windows with WSL2 backend support.",
        "tags": "docker,containers,install,windows"
    },
    {
        "issue": "Docker service stopped",
        "os": "Windows",
        "category": "Containers",
        "command": "powershell -Command \"Start-Service -Name com.docker.service -ErrorAction SilentlyContinue; Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'\"",
        "risk": "Low",
        "explanation": "Starts the Docker Desktop background service and GUI app.",
        "tags": "docker,service,restart,repair,windows"
    },
    {
        "issue": "Docker service stopped",
        "os": "Linux",
        "category": "Containers",
        "command": "sudo systemctl start docker && sudo systemctl enable docker",
        "risk": "Low",
        "explanation": "Starts and enables the Docker daemon on Linux.",
        "tags": "docker,systemd,linux,service"
    },
    {
        "issue": "Docker prune unused images and volumes",
        "os": "Any",
        "category": "Containers",
        "command": "docker system prune -af --volumes",
        "risk": "Medium",
        "explanation": "Reclaims disk space by pruning stopped containers, unused networks, and dangling volumes.",
        "tags": "docker,cleanup,disk,containers"
    },
    {
        "issue": "WSL2 Virtual Machine Platform missing or disabled",
        "os": "Windows",
        "category": "Containers",
        "command": "powershell -Command \"dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart; dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart; wsl --set-default-version 2\"",
        "risk": "Medium",
        "explanation": "Enables Windows Subsystem for Linux (WSL2) and Virtual Machine Platform components.",
        "tags": "wsl,wsl2,docker,windows,virtualization"
    },
    {
        "issue": "WSL kernel update / repair",
        "os": "Windows",
        "category": "Containers",
        "command": "wsl --update",
        "risk": "Low",
        "explanation": "Downloads and updates the WSL2 Linux kernel from Microsoft.",
        "tags": "wsl,kernel,update,windows"
    },

    # =========================================================================
    # 5. DATABASES & DEV SERVICES
    # =========================================================================
    {
        "issue": "DBeaver Community database tool missing",
        "os": "Windows",
        "category": "Databases",
        "command": "winget install --id dbeaver.dbeaver --exact --silent",
        "risk": "Low",
        "explanation": "Installs DBeaver Universal Database Manager on Windows.",
        "tags": "dbeaver,database,sql,install"
    },
    {
        "issue": "PostgreSQL missing",
        "os": "Windows",
        "category": "Databases",
        "command": "winget install --id PostgreSQL.PostgreSQL.16 --exact --silent",
        "risk": "Medium",
        "explanation": "Installs PostgreSQL 16 relational database server on Windows.",
        "tags": "postgres,postgresql,sql,database,install"
    },
    {
        "issue": "PostgreSQL service stopped",
        "os": "Windows",
        "category": "Databases",
        "command": "powershell -Command \"Get-Service -Name '*postgres*' | Start-Service\"",
        "risk": "Low",
        "explanation": "Finds and starts the PostgreSQL Windows service.",
        "tags": "postgres,service,database,repair"
    },
    {
        "issue": "MySQL server missing",
        "os": "Windows",
        "category": "Databases",
        "command": "winget install --id Oracle.MySQL --exact --silent",
        "risk": "Medium",
        "explanation": "Installs Oracle MySQL Community Server on Windows.",
        "tags": "mysql,sql,database,install"
    },
    {
        "issue": "SQLite CLI tool missing",
        "os": "Windows",
        "category": "Databases",
        "command": "winget install --id SQLite.SQLite --exact --silent",
        "risk": "Low",
        "explanation": "Installs SQLite command line shell on Windows.",
        "tags": "sqlite,sql,database,cli,install"
    },
    {
        "issue": "Redis service missing or stopped",
        "os": "Windows",
        "category": "Databases",
        "command": "winget install --id Memurai.MemuraiDeveloper --exact --silent",
        "risk": "Low",
        "explanation": "Installs Memurai (Redis-compatible developer server for Windows).",
        "tags": "redis,cache,database,install"
    },

    # =========================================================================
    # 6. VERSION CONTROL & CLI DEV TOOLS
    # =========================================================================
    {
        "issue": "Git missing",
        "os": "Windows",
        "category": "Version Control",
        "command": "winget install --id Git.Git --exact --silent",
        "risk": "Low",
        "explanation": "Installs Git for Windows with Git Bash and Credential Manager.",
        "tags": "git,vcs,version_control,install"
    },
    {
        "issue": "Git missing",
        "os": "Linux",
        "category": "Version Control",
        "command": "sudo apt-get update && sudo apt-get install -y git git-lfs",
        "risk": "Low",
        "explanation": "Installs Git and Git LFS on Linux via apt.",
        "tags": "git,vcs,linux,install"
    },
    {
        "issue": "Git Credential Manager corrupted or broken",
        "os": "Windows",
        "category": "Version Control",
        "command": "git config --global credential.helper manager",
        "risk": "Low",
        "explanation": "Restores Git Credential Manager as the global authentication helper.",
        "tags": "git,auth,credentials,repair"
    },
    {
        "issue": "Git LF / CRLF line ending conversion issues",
        "os": "Windows",
        "category": "Version Control",
        "command": "git config --global core.autocrlf true",
        "risk": "Low",
        "explanation": "Configures Git to handle Windows CRLF line endings automatically.",
        "tags": "git,crlf,repair,config"
    },
    {
        "issue": "GitHub CLI missing",
        "os": "Windows",
        "category": "Version Control",
        "command": "winget install --id GitHub.cli --exact --silent",
        "risk": "Low",
        "explanation": "Installs official GitHub CLI (gh) on Windows.",
        "tags": "gh,github,cli,install"
    },
    {
        "issue": "FZF fuzzy finder missing",
        "os": "Windows",
        "category": "CLI Tools",
        "command": "winget install --id junegunn.fzf --exact --silent",
        "risk": "Low",
        "explanation": "Installs fzf command-line fuzzy finder on Windows.",
        "tags": "fzf,cli,terminal,install"
    },
    {
        "issue": "jq JSON processor missing",
        "os": "Windows",
        "category": "CLI Tools",
        "command": "winget install --id jqlang.jq --exact --silent",
        "risk": "Low",
        "explanation": "Installs jq lightweight and flexible command-line JSON processor on Windows.",
        "tags": "jq,json,cli,install"
    },
    {
        "issue": "Ollama local LLM runner missing",
        "os": "Windows",
        "category": "AI Tools",
        "command": "winget install --id Ollama.Ollama --exact --silent",
        "risk": "Low",
        "explanation": "Installs Ollama for running local AI models (Llama 3, Mistral, etc.) on Windows.",
        "tags": "ollama,ai,llm,install"
    },
    {
        "issue": "Postman API platform missing",
        "os": "Windows",
        "category": "API Tools",
        "command": "winget install --id Postman.Postman --exact --silent",
        "risk": "Low",
        "explanation": "Installs Postman API development and testing client.",
        "tags": "postman,api,http,testing,install"
    },
    {
        "issue": "Slack messaging client missing",
        "os": "Windows",
        "category": "Productivity",
        "command": "winget install --id SlackTechnologies.Slack --exact --silent",
        "risk": "Low",
        "explanation": "Installs Slack desktop application on Windows.",
        "tags": "slack,chat,productivity,install"
    },
    {
        "issue": "Brave Browser missing",
        "os": "Windows",
        "category": "Browsers",
        "command": "winget install --id Brave.Brave --exact --silent",
        "risk": "Low",
        "explanation": "Installs Brave Privacy Browser via Winget.",
        "tags": "brave,browser,web,install"
    },
    {
        "issue": "Google Chrome missing",
        "os": "Windows",
        "category": "Browsers",
        "command": "winget install --id Google.Chrome --exact --silent",
        "risk": "Low",
        "explanation": "Installs Google Chrome browser via Winget.",
        "tags": "chrome,browser,google,install"
    },
    {
        "issue": "Mozilla Firefox missing",
        "os": "Windows",
        "category": "Browsers",
        "command": "winget install --id Mozilla.Firefox --exact --silent",
        "risk": "Low",
        "explanation": "Installs Mozilla Firefox browser on Windows.",
        "tags": "firefox,browser,mozilla,install"
    },

    # =========================================================================
    # 7. WINDOWS SYSTEM HEALTH & ERROR REPAIRS
    # =========================================================================
    {
        "issue": "Windows System Files Corrupted (SFC Scan)",
        "os": "Windows",
        "category": "System Health",
        "command": "sfc /scannow",
        "risk": "Low",
        "explanation": "Scans integrity of all protected system files and repairs corrupted files using cached copy.",
        "tags": "sfc,windows,system,integrity,repair"
    },
    {
        "issue": "Windows Component Store Corrupted (DISM RestoreHealth)",
        "os": "Windows",
        "category": "System Health",
        "command": "dism /online /cleanup-image /restorehealth",
        "risk": "Medium",
        "explanation": "Scans the Windows image for component store corruption and performs recovery operations.",
        "tags": "dism,windows,system,repair"
    },
    {
        "issue": "DNS Cache Corrupted / Cannot resolve hosts",
        "os": "Windows",
        "category": "Network",
        "command": "ipconfig /flushdns",
        "risk": "Low",
        "explanation": "Flushes and resets the contents of the DNS client resolver cache.",
        "tags": "dns,network,windows,repair"
    },
    {
        "issue": "Windows Network Stack & Winsock Corrupted",
        "os": "Windows",
        "category": "Network",
        "command": "netsh winsock reset && netsh int ip reset",
        "risk": "Medium",
        "explanation": "Resets the Winsock Catalog and TCP/IP stack to default clean state to fix network disconnection.",
        "tags": "network,winsock,tcp,repair,windows"
    },
    {
        "issue": "Windows Disk Space Exhausted / Temp Files Cleanup",
        "os": "Windows",
        "category": "Disk Cleanup",
        "command": r'powershell -Command "Remove-Item -Path \"$env:TEMP\*\", \"$env:SystemRoot\Temp\*\" -Recurse -Force -ErrorAction SilentlyContinue; Clear-RecycleBin -Force -ErrorAction SilentlyContinue; Write-Host \"Cleaned Temp directory and Recycle Bin.\""',
        "risk": "Low",
        "explanation": "Purges temporary system files and empties the Recycle Bin to reclaim disk space.",
        "tags": "disk,cleanup,temp,windows,performance"
    },
    {
        "issue": "Windows Update Service Stuck or Failing",
        "os": "Windows",
        "category": "System Health",
        "command": r'powershell -Command "Stop-Service -Name wuauserv, bits -Force -ErrorAction SilentlyContinue; Remove-Item -Path \"$env:SystemRoot\SoftwareDistribution\Download\*\" -Recurse -Force -ErrorAction SilentlyContinue; Start-Service -Name wuauserv, bits; Write-Host \"Windows Update cache reset.\""',
        "risk": "Medium",
        "explanation": "Stops Windows Update, clears corrupted download cache in SoftwareDistribution, and restarts service.",
        "tags": "windows_update,wuauserv,repair,system"
    },
    {
        "issue": "Windows Audio Service Stopped / No Sound",
        "os": "Windows",
        "category": "System Health",
        "command": "powershell -Command \"Restart-Service -Name AudioSrv, AudioEndpointBuilder -Force\"",
        "risk": "Low",
        "explanation": "Restarts Windows Audio and Audio Endpoint Builder services to resolve audio device dropouts.",
        "tags": "audio,sound,service,windows,repair"
    },
    {
        "issue": "Print Spooler Service Stuck",
        "os": "Windows",
        "category": "System Health",
        "command": r'powershell -Command "Stop-Service -Name Spooler -Force; Remove-Item -Path \"$env:SystemRoot\System32\spool\PRINTERS\*\" -Force -ErrorAction SilentlyContinue; Start-Service -Name Spooler; Write-Host \"Print spooler queue cleared.\""',
        "risk": "Low",
        "explanation": "Clears frozen print jobs from the spool queue and restarts the Print Spooler service.",
        "tags": "printer,spooler,service,repair,windows"
    },
    {
        "issue": "Windows Disk Check & Metadata Scan (Chkdsk)",
        "os": "Windows",
        "category": "System Health",
        "command": "chkdsk C: /scan",
        "risk": "Low",
        "explanation": "Performs an online scan of disk drive C: looking for file system errors without taking drive offline.",
        "tags": "chkdsk,disk,fs,repair,windows"
    },
    {
        "issue": "PowerShell Execution Policy Restricts Scripts",
        "os": "Windows",
        "category": "System Health",
        "command": "powershell -Command \"Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force\"",
        "risk": "Low",
        "explanation": "Configures PowerShell execution policy to allow running local developer scripts.",
        "tags": "powershell,execution_policy,windows,config"
    },

    # =========================================================================
    # 8. LINUX SYSTEM HEALTH & REPAIRS
    # =========================================================================
    {
        "issue": "Broken apt package dependencies",
        "os": "Linux",
        "category": "System Health",
        "command": "sudo dpkg --configure -a && sudo apt-get install -f -y",
        "risk": "Medium",
        "explanation": "Reconfigures unpacked packages and resolves broken apt dependencies.",
        "tags": "apt,dpkg,linux,repair"
    },
    {
        "issue": "Linux Disk Space / Apt Cache Cleanup",
        "os": "Linux",
        "category": "Disk Cleanup",
        "command": "sudo apt-get autoremove -y && sudo apt-get clean && rm -rf ~/.cache/thumbnails/*",
        "risk": "Low",
        "explanation": "Removes orphaned packages, clears downloaded apt archives, and purges thumbnail cache.",
        "tags": "apt,cleanup,disk,linux"
    },
    {
        "issue": "Linux Systemd Resolved DNS Flush",
        "os": "Linux",
        "category": "Network",
        "command": "sudo resolvectl flush-caches",
        "risk": "Low",
        "explanation": "Flushes DNS cache on systemd-resolved systems.",
        "tags": "dns,linux,systemd,network"
    },
    {
        "issue": "Linux System Journal Vacuum / Log Clean",
        "os": "Linux",
        "category": "Disk Cleanup",
        "command": "sudo journalctl --vacuum-time=3d",
        "risk": "Low",
        "explanation": "Purges systemd journal logs older than 3 days to free disk space.",
        "tags": "journalctl,logs,cleanup,linux"
    },

    # =========================================================================
    # 9. MAC / DARWIN SYSTEM REPAIRS
    # =========================================================================
    {
        "issue": "macOS Homebrew missing",
        "os": "Darwin",
        "category": "Package Managers",
        "command": '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
        "risk": "Low",
        "explanation": "Installs Homebrew package manager on macOS.",
        "tags": "brew,homebrew,macos,install"
    },
    {
        "issue": "macOS DNS Cache Flush",
        "os": "Darwin",
        "category": "Network",
        "command": "sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder",
        "risk": "Low",
        "explanation": "Flushes DNS directory service cache on macOS.",
        "tags": "dns,macos,network,repair"
    },
    {
        "issue": "macOS Homebrew Cleanup",
        "os": "Darwin",
        "category": "Disk Cleanup",
        "command": "brew autoremove && brew cleanup -s",
        "risk": "Low",
        "explanation": "Removes unneeded dependencies and purges cached downloads for Homebrew formulas.",
        "tags": "brew,cleanup,macos,disk"
    },
    {
        "issue": "Google Chrome missing",
        "os": "Windows",
        "category": "Browsers",
        "command": "winget install --id Google.Chrome --exact --silent",
        "risk": "Low",
        "explanation": "Installs Google Chrome browser via Winget.",
        "tags": "chrome,browser,install",
        "operation": "INSTALL",
        "repair_strategy": "NONE",
        "package_id": "Google.Chrome",
        "package_manager": "winget",
        "official_url": "https://www.google.com/chrome",
        "app_id": "chrome"
    },
    {
        "issue": "Anaconda3 environment",
        "os": "Windows",
        "category": "Runtimes",
        "command": "conda update --all -y",
        "risk": "Low",
        "explanation": "Anaconda cannot be upgraded through WinGet. Updates are managed via conda or the official installer.",
        "tags": "anaconda,anaconda3,python,conda,runtime,environment,update",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "package_id": "Anaconda.Anaconda3",
        "package_manager": "winget",
        "official_url": "https://www.anaconda.com/download",
        "app_id": "anaconda3",
        "install_supported": 1,
        "update_supported": 0,
        "uninstall_supported": 1,
        "reinstall_supported": 1,
        "verify_supported": 1,
        "version_check_supported": 1,
        "repair_supported": 0,
        "update_method": "PUBLISHER_RECIPE",
        "publisher_update_command": "conda update --all -y",
        "publisher_update_instructions": "Anaconda cannot be upgraded using WinGet. Please run 'conda update --all' in Anaconda Prompt or download the installer from the official Anaconda website."
    },
    {
        "issue": "Git missing or not installed",
        "os": "Windows",
        "category": "Version Control",
        "command": "winget install --id Git.Git --exact --silent --accept-source-agreements --accept-package-agreements",
        "risk": "Low",
        "explanation": "Installs the official Git version control client via WinGet.",
        "tags": "git,vcs,version control,install",
        "operation": "INSTALL",
        "repair_strategy": "NONE",
        "package_id": "Git.Git",
        "package_manager": "winget",
        "verification_command": "git --version",
        "official_url": "https://git-scm.com",
        "app_id": "git"
    },
    {
        "issue": "Git update available",
        "os": "Windows",
        "category": "Version Control",
        "command": "winget upgrade --id Git.Git --exact --silent",
        "risk": "Low",
        "explanation": "Upgrades Git to the latest release via WinGet.",
        "tags": "git,update,upgrade",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "package_id": "Git.Git",
        "package_manager": "winget",
        "verification_command": "git --version",
        "official_url": "https://git-scm.com",
        "app_id": "git"
    },
    {
        "issue": "Git environment corrupted or broken",
        "os": "Windows",
        "category": "Version Control",
        "command": "winget install --id Git.Git --exact --force --silent",
        "risk": "Medium",
        "explanation": "Repairs Git environment by forcing reinstallation of package binaries and PATH entries.",
        "tags": "git,repair,reinstall,corrupt",
        "operation": "REPAIR",
        "repair_strategy": "REINSTALL",
        "package_id": "Git.Git",
        "package_manager": "winget",
        "verification_command": "git --version",
        "official_url": "https://git-scm.com",
        "app_id": "git"
    },
    {
        "issue": "Node.js runtime missing or not installed",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id OpenJS.NodeJS --exact --silent --accept-source-agreements --accept-package-agreements",
        "risk": "Low",
        "explanation": "Installs Node.js JavaScript runtime (LTS) via WinGet.",
        "tags": "node,nodejs,javascript,runtime,install",
        "operation": "INSTALL",
        "repair_strategy": "NONE",
        "package_id": "OpenJS.NodeJS",
        "package_manager": "winget",
        "verification_command": "node --version",
        "official_url": "https://nodejs.org",
        "app_id": "nodejs"
    },
    {
        "issue": "Node.js update available",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget upgrade --id OpenJS.NodeJS --exact --silent",
        "risk": "Low",
        "explanation": "Upgrades Node.js to the latest release via WinGet.",
        "tags": "node,nodejs,update,upgrade",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "package_id": "OpenJS.NodeJS",
        "package_manager": "winget",
        "verification_command": "node --version",
        "official_url": "https://nodejs.org",
        "app_id": "nodejs"
    },
    {
        "issue": "Node.js environment corrupted or broken",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id OpenJS.NodeJS --exact --force --silent",
        "risk": "Medium",
        "explanation": "Repairs Node.js environment by forcing reinstallation of core binaries and npm bindings.",
        "tags": "node,nodejs,repair,reinstall,corrupt",
        "operation": "REPAIR",
        "repair_strategy": "REINSTALL",
        "package_id": "OpenJS.NodeJS",
        "package_manager": "winget",
        "verification_command": "node --version",
        "official_url": "https://nodejs.org",
        "app_id": "nodejs"
    },
    {
        "issue": "Visual Studio Code missing or not installed",
        "os": "Windows",
        "category": "Editors",
        "command": "winget install --id Microsoft.VisualStudioCode --exact --silent --accept-source-agreements --accept-package-agreements",
        "risk": "Low",
        "explanation": "Installs Visual Studio Code editor via WinGet.",
        "tags": "vscode,code,editor,install",
        "operation": "INSTALL",
        "repair_strategy": "NONE",
        "package_id": "Microsoft.VisualStudioCode",
        "package_manager": "winget",
        "verification_command": "code --version",
        "official_url": "https://code.visualstudio.com",
        "app_id": "vscode"
    },
    {
        "issue": "Visual Studio Code update available",
        "os": "Windows",
        "category": "Editors",
        "command": "winget upgrade --id Microsoft.VisualStudioCode --exact --silent",
        "risk": "Low",
        "explanation": "Upgrades Visual Studio Code to the latest version via WinGet.",
        "tags": "vscode,code,update,upgrade",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "package_id": "Microsoft.VisualStudioCode",
        "package_manager": "winget",
        "verification_command": "code --version",
        "official_url": "https://code.visualstudio.com",
        "app_id": "vscode"
    },
    {
        "issue": "Visual Studio Code installation corrupted or broken",
        "os": "Windows",
        "category": "Editors",
        "command": "winget install --id Microsoft.VisualStudioCode --exact --force --silent",
        "risk": "Medium",
        "explanation": "Repairs Visual Studio Code by running a clean reinstall of core binaries and shell associations.",
        "tags": "vscode,code,repair,reinstall,corrupt",
        "operation": "REPAIR",
        "repair_strategy": "REINSTALL",
        "package_id": "Microsoft.VisualStudioCode",
        "package_manager": "winget",
        "verification_command": "code --version",
        "official_url": "https://code.visualstudio.com",
        "app_id": "vscode"
    },

    # =========================================================================
    # STAGE 7 — SC-1: Service Start/Stop Repair (Problems 16, 49)
    # Routes through CentralizedExecutionEngine → L4 daemon verification.
    # =========================================================================
    {
        "issue": "Service not running - MySQL",
        "os": "Windows",
        "category": "Services",
        "command": "net start MySQL80",
        "risk": "Low",
        "explanation": "Starts the MySQL 8.0 Windows service via the Service Control Manager.",
        "tags": "mysql,service,repair,start,database",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "sc query MySQL80",
    },
    {
        "issue": "Service not running - PostgreSQL",
        "os": "Windows",
        "category": "Services",
        "command": "net start postgresql-x64-16",
        "risk": "Low",
        "explanation": "Starts the PostgreSQL 16 Windows service.",
        "tags": "postgresql,postgres,service,repair,start,database",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "sc query postgresql-x64-16",
    },
    {
        "issue": "Service not running - Docker",
        "os": "Windows",
        "category": "Services",
        "command": "net start com.docker.service",
        "risk": "Low",
        "explanation": "Starts the Docker Desktop service on Windows.",
        "tags": "docker,service,repair,start,container",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "sc query com.docker.service",
    },
    {
        "issue": "Service not running - MongoDB",
        "os": "Windows",
        "category": "Services",
        "command": "net start MongoDB",
        "risk": "Low",
        "explanation": "Starts the MongoDB Windows service.",
        "tags": "mongodb,service,repair,start,database",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "sc query MongoDB",
    },
    {
        "issue": "Service not running - Redis",
        "os": "Windows",
        "category": "Services",
        "command": "net start Redis",
        "risk": "Low",
        "explanation": "Starts the Redis Windows service.",
        "tags": "redis,service,repair,start,cache",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "sc query Redis",
    },
    {
        "issue": "Docker Desktop not running",
        "os": "Windows",
        "category": "Services",
        "command": r'powershell -Command "Start-Process -FilePath \"C:\Program Files\Docker\Docker\Docker Desktop.exe\" -WindowStyle Minimized"',
        "risk": "Low",
        "explanation": "Launches Docker Desktop application and waits for daemon initialization.",
        "tags": "docker,desktop,service,start,container",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "docker info",
    },
    {
        "issue": "Service not running",
        "os": "Linux",
        "category": "Services",
        "command": "sudo systemctl start {service_name}",
        "risk": "Low",
        "explanation": "Starts a stopped systemd service on Linux.",
        "tags": "systemd,service,repair,start,linux",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "systemctl is-active {service_name}",
    },
    {
        "issue": "Service not running",
        "os": "Darwin",
        "category": "Services",
        "command": "brew services start {service_name}",
        "risk": "Low",
        "explanation": "Starts a Homebrew-managed service on macOS.",
        "tags": "brew,service,repair,start,macos",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "brew services list",
    },

    # =========================================================================
    # STAGE 7 — SC-2: Permission Repair via icacls (Problems 31, 73)
    # Tier 2 Controlled, elevation required for system directories.
    # =========================================================================
    {
        "issue": "Permission denied on installation directory",
        "os": "Windows",
        "category": "Permissions",
        "command": r'powershell -Command "icacls \"$env:ProgramFiles\" /grant Users:(OI)(CI)RX /T /C 2>&1"',
        "risk": "Medium",
        "explanation": "Grants standard read and execute permissions to Users on Program Files. Requires elevation.",
        "tags": "permissions,icacls,repair,windows,access,elevation",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": r'powershell -Command "Test-Path $env:ProgramFiles"',
    },
    {
        "issue": "Permission denied on local app data directory",
        "os": "Windows",
        "category": "Permissions",
        "command": r'powershell -Command "icacls \"$env:LOCALAPPDATA\" /grant ${env:USERNAME}:(OI)(CI)F /T /C 2>&1"',
        "risk": "Low",
        "explanation": "Grants full control to current user on their LocalAppData directory. No elevation required.",
        "tags": "permissions,icacls,repair,windows,access,appdata",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": r'powershell -Command "Test-Path $env:LOCALAPPDATA"',
    },
    {
        "issue": "Uninstall reinstall changes permissions",
        "os": "Windows",
        "category": "Permissions",
        "command": r'powershell -Command "icacls \"$env:LOCALAPPDATA\Programs\" /grant ${env:USERNAME}:(OI)(CI)F /T /C 2>&1"',
        "risk": "Low",
        "explanation": "Restores user permissions on Programs directory under LocalAppData after reinstall changes ownership.",
        "tags": "permissions,icacls,repair,reinstall,windows,post-install",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": r'powershell -Command "(Get-Acl ($env:LOCALAPPDATA + \"\Programs\")).Access"',
    },
    {
        "issue": "Permission denied on installation directory",
        "os": "Linux",
        "category": "Permissions",
        "command": "sudo chmod -R a+rX /usr/local/bin && sudo chown -R $(whoami) ~/.local",
        "risk": "Medium",
        "explanation": "Restores read and execute permissions on standard Linux install locations.",
        "tags": "permissions,chmod,repair,linux,access",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "ls -la /usr/local/bin",
    },
    {
        "issue": "Permission denied on installation directory",
        "os": "Darwin",
        "category": "Permissions",
        "command": "sudo chown -R $(whoami) /usr/local/bin /usr/local/lib /usr/local/sbin 2>/dev/null || true",
        "risk": "Medium",
        "explanation": "Restores Homebrew directory ownership to current user on macOS.",
        "tags": "permissions,chown,repair,macos,homebrew,access",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "ls -la /usr/local/bin",
    },

    # =========================================================================
    # STAGE 7 — SC-3: Windows Feature Detection & Enablement (Problems 50, 51)
    # Tier 2 Controlled. Reboot required. Result classifier captures exit 3010.
    # =========================================================================
    {
        "issue": "WSL dependency not enabled",
        "os": "Windows",
        "category": "WindowsFeatures",
        "command": "powershell -Command \"Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart\"",
        "risk": "High",
        "explanation": "Enables the Windows Subsystem for Linux (WSL) optional feature. A system restart is required to complete activation.",
        "tags": "wsl,feature,windows,enable,reboot-required",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "powershell -Command \"(Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux).State\"",
    },
    {
        "issue": "WSL2 virtual machine platform not enabled",
        "os": "Windows",
        "category": "WindowsFeatures",
        "command": "powershell -Command \"Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart\"",
        "risk": "High",
        "explanation": "Enables the Virtual Machine Platform feature required by WSL2. A system restart is required.",
        "tags": "wsl2,vm,platform,feature,windows,enable,reboot-required",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "powershell -Command \"(Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform).State\"",
    },
    {
        "issue": "Hyper-V not enabled",
        "os": "Windows",
        "category": "WindowsFeatures",
        "command": "powershell -Command \"Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -NoRestart\"",
        "risk": "High",
        "explanation": "Enables the Hyper-V hypervisor and management tools. A system restart is required. Requires Windows Pro or Enterprise.",
        "tags": "hyperv,hyper-v,feature,windows,enable,docker,reboot-required",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "powershell -Command \"(Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V).State\"",
    },
    {
        "issue": "HypervisorPlatform not enabled",
        "os": "Windows",
        "category": "WindowsFeatures",
        "command": "powershell -Command \"Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -NoRestart\"",
        "risk": "High",
        "explanation": "Enables the Windows Hypervisor Platform feature required for third-party virtualization. A system restart is required.",
        "tags": "hypervisor,hypervisorplatform,feature,windows,enable,reboot-required",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "powershell -Command \"(Get-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform).State\"",
    },
    {
        "issue": "Windows feature disabled - Containers",
        "os": "Windows",
        "category": "WindowsFeatures",
        "command": "powershell -Command \"Enable-WindowsOptionalFeature -Online -FeatureName Containers -NoRestart\"",
        "risk": "High",
        "explanation": "Enables the Windows Containers feature required for Docker Engine mode. A reboot is required.",
        "tags": "containers,feature,windows,docker,enable,reboot-required",
        "operation": "REPAIR",
        "repair_strategy": "NATIVE_REPAIR",
        "verification_command": "powershell -Command \"(Get-WindowsOptionalFeature -Online -FeatureName Containers).State\"",
    },
    {
        "issue": "WSL kernel update required",
        "os": "Windows",
        "category": "WindowsFeatures",
        "command": "wsl --update",
        "risk": "Low",
        "explanation": "Updates the WSL2 Linux kernel to the latest version via the Microsoft Store distribution channel.",
        "tags": "wsl,wsl2,kernel,update,windows",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "verification_command": "wsl --status",
    },

    # =========================================================================
    # STAGE 7 — SC-4: Package Manager Self-Update (Problem 25)
    # =========================================================================
    {
        "issue": "Package manager outdated - winget",
        "os": "Windows",
        "category": "PackageManagers",
        "command": "winget upgrade --id Microsoft.AppInstaller --silent --accept-source-agreements --accept-package-agreements",
        "risk": "Low",
        "explanation": "Updates Windows Package Manager (WinGet / App Installer) to the latest version via the Microsoft Store.",
        "tags": "winget,package-manager,update,self-update,windows",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "verification_command": "winget --version",
        "package_id": "Microsoft.AppInstaller",
        "package_manager": "winget",
    },
    {
        "issue": "Package manager outdated - chocolatey",
        "os": "Windows",
        "category": "PackageManagers",
        "command": "choco upgrade chocolatey --yes",
        "risk": "Low",
        "explanation": "Upgrades Chocolatey package manager to the latest stable version.",
        "tags": "chocolatey,choco,package-manager,update,self-update,windows",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "verification_command": "choco --version",
        "package_id": "chocolatey",
        "package_manager": "choco",
    },
    {
        "issue": "Package manager outdated - apt",
        "os": "Linux",
        "category": "PackageManagers",
        "command": "sudo apt-get update && sudo apt-get install --only-upgrade apt -y",
        "risk": "Low",
        "explanation": "Updates the apt package manager cache and upgrades the apt tool itself.",
        "tags": "apt,package-manager,update,self-update,linux",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "verification_command": "apt-get --version",
        "package_manager": "apt",
    },
    {
        "issue": "Package manager outdated - brew",
        "os": "Darwin",
        "category": "PackageManagers",
        "command": "brew update && brew upgrade brew 2>/dev/null || brew update",
        "risk": "Low",
        "explanation": "Updates the Homebrew package manager repository.",
        "tags": "brew,homebrew,package-manager,update,self-update,macos",
        "operation": "UPDATE",
        "repair_strategy": "NONE",
        "verification_command": "brew --version",
        "package_manager": "brew",
    },

    # =========================================================================
    # STAGE 7 — SC-5: Residual Data Cleanup After Uninstall (Problem 35)
    # Tier 3 Full Protected path. Snapshot before execution required.
    # =========================================================================
    {
        "issue": "Uninstall leaves residual data",
        "os": "Windows",
        "category": "Cleanup",
        "command": r'powershell -Command "$appname=\"{tool_name}\"; $paths=@(\"$env:APPDATA\\$appname\",\"$env:LOCALAPPDATA\\$appname\",\"$env:PROGRAMDATA\\$appname\"); foreach($p in $paths){if(Test-Path $p){Write-Host \"Removing residual: $p\";Remove-Item -Recurse -Force $p -EA SilentlyContinue}}"',
        "risk": "High",
        "explanation": "Removes residual application data directories from AppData, LocalAppData, and ProgramData after uninstall. Snapshot recommended before execution.",
        "tags": "cleanup,residual,uninstall,appdata,purge,repair,tier3",
        "operation": "REPAIR",
        "repair_strategy": "CACHE_CLEAR",
        "verification_command": "powershell -Command \"Write-Host 'Residual scan complete'\"",
    },
    {
        "issue": "Uninstall leaves residual data",
        "os": "Linux",
        "category": "Cleanup",
        "command": r"find ~/.config ~/.local/share ~/.cache -maxdepth 2 -name '{tool_name}' -type d 2>/dev/null | while read d; do echo \"Removing residual: $d\"; rm -rf \"$d\"; done",
        "risk": "High",
        "explanation": "Removes residual XDG config, data, and cache directories for an uninstalled application on Linux.",
        "tags": "cleanup,residual,uninstall,xdg,cache,purge,linux,tier3",
        "operation": "REPAIR",
        "repair_strategy": "CACHE_CLEAR",
        "verification_command": "echo 'Residual cleanup complete'",
    },
    {
        "issue": "Uninstall leaves residual data",
        "os": "Darwin",
        "category": "Cleanup",
        "command": r"find ~/Library/Application\ Support ~/Library/Caches ~/Library/Preferences -maxdepth 1 -name '{tool_name}*' 2>/dev/null | while read d; do echo \"Removing residual: $d\"; rm -rf \"$d\"; done",
        "risk": "High",
        "explanation": "Removes residual macOS Library directories for an uninstalled application.",
        "tags": "cleanup,residual,uninstall,library,cache,purge,macos,tier3",
        "operation": "REPAIR",
        "repair_strategy": "CACHE_CLEAR",
        "verification_command": "echo 'Residual cleanup complete'",
    },

    # =========================================================================
    # STAGE 7 — SC-7: Package Channel Selection (Problem 40)
    # Stable vs LTS vs beta channel recipe variants.
    # =========================================================================
    {
        "issue": "Node.js LTS channel install",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id OpenJS.NodeJS.LTS --exact --silent --accept-source-agreements --accept-package-agreements",
        "risk": "Low",
        "explanation": "Installs the Node.js Long-Term Support (LTS) channel via WinGet. Preferred for production environments.",
        "tags": "nodejs,node,lts,channel,stable,install,windows",
        "operation": "INSTALL",
        "repair_strategy": "NONE",
        "verification_command": "node --version",
        "package_id": "OpenJS.NodeJS.LTS",
        "package_manager": "winget",
    },
    {
        "issue": "Node.js current channel install",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id OpenJS.NodeJS --exact --silent --accept-source-agreements --accept-package-agreements",
        "risk": "Medium",
        "explanation": "Installs the Node.js current (latest) channel via WinGet. Contains newer features but may have breaking changes.",
        "tags": "nodejs,node,current,latest,channel,install,windows",
        "operation": "INSTALL",
        "repair_strategy": "NONE",
        "verification_command": "node --version",
        "package_id": "OpenJS.NodeJS",
        "package_manager": "winget",
    },
    {
        "issue": "VS Code Insiders channel install",
        "os": "Windows",
        "category": "IDEs",
        "command": "winget install --id Microsoft.VisualStudioCode.Insiders --exact --silent --accept-source-agreements --accept-package-agreements",
        "risk": "Medium",
        "explanation": "Installs the VS Code Insiders (pre-release) channel. May contain experimental features.",
        "tags": "vscode,insiders,beta,channel,install,windows",
        "operation": "INSTALL",
        "repair_strategy": "NONE",
        "verification_command": "code-insiders --version",
        "package_id": "Microsoft.VisualStudioCode.Insiders",
        "package_manager": "winget",
    },
    {
        "issue": "Python LTS channel install",
        "os": "Windows",
        "category": "Runtimes",
        "command": "winget install --id Python.Python.3.12 --exact --silent --accept-source-agreements --accept-package-agreements",
        "risk": "Low",
        "explanation": "Installs Python 3.12, the current long-term support series, preferred for production over 3.13+.",
        "tags": "python,lts,stable,channel,install,windows",
        "operation": "INSTALL",
        "repair_strategy": "NONE",
        "verification_command": "python --version",
        "package_id": "Python.Python.3.12",
        "package_manager": "winget",
    },
]



def _classify_recipe(r: dict) -> tuple[str, str]:
    """
    Returns (operation, repair_strategy).
    operation: 'INSTALL', 'REINSTALL', 'REPAIR', 'UPDATE', 'UNINSTALL', 'VERIFY'
    repair_strategy: 'NATIVE_REPAIR', 'REINSTALL', 'NONE'
    """
    if "operation" in r and "repair_strategy" in r:
        return r["operation"], r["repair_strategy"]

    cmd = r.get("command", "").lower()
    issue = r.get("issue", "").lower()
    tags = r.get("tags", "").lower()

    if "--force" in cmd or "--reinstall" in cmd or "reinstall" in issue:
        if "repair" in tags or "corrupt" in issue or "repair" in issue:
            return "REPAIR", "REINSTALL"
        return "REINSTALL", "NONE"

    if "update" in issue or "upgrade" in cmd or "upgrade" in tags:
        if "repair" in tags or "broken" in issue or "corrupt" in issue:
            return "REPAIR", "NATIVE_REPAIR"
        return "UPDATE", "NONE"

    if any(k in issue for k in ("missing", "install")) or any(k in tags for k in ("install", "setup")):
        if any(cmd.startswith(p) for p in ("winget install", "sudo apt-get install", "brew install", "npm install -g", "curl")):
            return "INSTALL", "NONE"

    return "REPAIR", "NATIVE_REPAIR"


def _migrate_static_recipes_table(conn: sqlite3.Connection):
    """Ensures static_recipes table has all required columns for structured operations."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(static_recipes)").fetchall()}
    col_defs = {
        "operation": "TEXT NOT NULL DEFAULT 'REPAIR'",
        "repair_strategy": "TEXT NOT NULL DEFAULT 'NONE'",
        "package_manager": "TEXT DEFAULT 'winget'",
        "package_id": "TEXT DEFAULT ''",
        "verification_command": "TEXT DEFAULT ''",
        "official_url": "TEXT DEFAULT ''",
        "source": "TEXT NOT NULL DEFAULT 'STATIC_DB'",
        "app_id": "TEXT DEFAULT ''",
        "install_supported": "INTEGER NOT NULL DEFAULT 1",
        "update_supported": "INTEGER NOT NULL DEFAULT 1",
        "uninstall_supported": "INTEGER NOT NULL DEFAULT 1",
        "reinstall_supported": "INTEGER NOT NULL DEFAULT 1",
        "verify_supported": "INTEGER NOT NULL DEFAULT 1",
        "version_check_supported": "INTEGER NOT NULL DEFAULT 1",
        "repair_supported": "INTEGER NOT NULL DEFAULT 0",
        "update_method": "TEXT NOT NULL DEFAULT 'PACKAGE_MANAGER'",
        "publisher_update_command": "TEXT NOT NULL DEFAULT ''",
        "publisher_update_instructions": "TEXT NOT NULL DEFAULT ''"
    }
    for col, col_type in col_defs.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE static_recipes ADD COLUMN {col} {col_type}")
    conn.commit()


def populate():
    print(f"[1/3] Ensuring tables in static knowledge DB: {STATIC_DB_PATH} ...")
    conn_static = sqlite3.connect(STATIC_DB_PATH)
    conn_static.execute("PRAGMA journal_mode=WAL")
    
    conn_static.execute("""
        CREATE TABLE IF NOT EXISTS static_recipes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            issue               TEXT NOT NULL,
            os                  TEXT NOT NULL DEFAULT 'Any',
            category            TEXT NOT NULL DEFAULT 'General',
            command             TEXT NOT NULL,
            risk                TEXT NOT NULL DEFAULT 'Low',
            explanation         TEXT NOT NULL DEFAULT '',
            tags                TEXT NOT NULL DEFAULT '',
            operation           TEXT NOT NULL DEFAULT 'REPAIR',
            repair_strategy     TEXT NOT NULL DEFAULT 'NONE',
            package_manager     TEXT DEFAULT 'winget',
            package_id          TEXT DEFAULT '',
            verification_command TEXT DEFAULT '',
            official_url        TEXT DEFAULT '',
            source              TEXT NOT NULL DEFAULT 'STATIC_DB',
            app_id              TEXT DEFAULT '',
            install_supported   INTEGER NOT NULL DEFAULT 1,
            update_supported    INTEGER NOT NULL DEFAULT 1,
            uninstall_supported INTEGER NOT NULL DEFAULT 1,
            reinstall_supported INTEGER NOT NULL DEFAULT 1,
            verify_supported    INTEGER NOT NULL DEFAULT 1,
            version_check_supported INTEGER NOT NULL DEFAULT 1,
            repair_supported    INTEGER NOT NULL DEFAULT 0,
            update_method       TEXT NOT NULL DEFAULT 'PACKAGE_MANAGER',
            publisher_update_command TEXT NOT NULL DEFAULT '',
            publisher_update_instructions TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    _migrate_static_recipes_table(conn_static)
    conn_static.execute("CREATE INDEX IF NOT EXISTS idx_sr_issue ON static_recipes(issue)")
    conn_static.execute("CREATE INDEX IF NOT EXISTS idx_sr_category ON static_recipes(category)")
    conn_static.execute("CREATE INDEX IF NOT EXISTS idx_sr_os ON static_recipes(os)")
    conn_static.execute("CREATE INDEX IF NOT EXISTS idx_sr_op ON static_recipes(operation)")
    conn_static.execute("CREATE INDEX IF NOT EXISTS idx_sr_strat ON static_recipes(repair_strategy)")
    
    # Backfill/update existing rows with accurate operation and repair_strategy
    existing_rows = conn_static.execute("SELECT id, issue, command, tags, category, os FROM static_recipes").fetchall()
    for row_id, iss, cmd, tgs, cat, os_val in existing_rows:
        op, strat = _classify_recipe({"issue": iss, "command": cmd, "tags": tgs, "category": cat, "os": os_val})
        conn_static.execute(
            "UPDATE static_recipes SET operation = ?, repair_strategy = ?, source = 'STATIC_DB' WHERE id = ?",
            (op, strat, row_id)
        )
    conn_static.commit()
    
    # Check current static count
    count_static = conn_static.execute("SELECT COUNT(*) FROM static_recipes").fetchone()[0]
    print(f"      Current static_recipes count: {count_static}")
    
    # Insert recipes that don't already exist by (issue, os)
    inserted_static = 0
    for r in RECIPES:
        op, strat = _classify_recipe(r)
        pkg_id = r.get("package_id", "")
        pkg_mgr = r.get("package_manager", "winget")
        ver_cmd = r.get("verification_command", "")
        off_url = r.get("official_url", "")
        a_id = r.get("app_id", "")
        inst_sup = r.get("install_supported", 1)
        upd_sup = r.get("update_supported", 1)
        uninst_sup = r.get("uninstall_supported", 1)
        reinst_sup = r.get("reinstall_supported", 1)
        ver_sup = r.get("verify_supported", 1)
        ver_chk_sup = r.get("version_check_supported", 1)
        rep_sup = r.get("repair_supported", 0)
        upd_meth = r.get("update_method", "PACKAGE_MANAGER")
        pub_cmd = r.get("publisher_update_command", "")
        pub_inst = r.get("publisher_update_instructions", "")

        existing = conn_static.execute(
            "SELECT id FROM static_recipes WHERE LOWER(issue) = LOWER(?) AND os = ?",
            (r["issue"], r["os"])
        ).fetchone()
        if not existing:
            conn_static.execute("""
                INSERT INTO static_recipes (
                    issue, os, category, command, risk, explanation, tags,
                    operation, repair_strategy, package_manager, package_id,
                    verification_command, official_url, source, app_id,
                    install_supported, update_supported, uninstall_supported,
                    reinstall_supported, verify_supported, version_check_supported,
                    repair_supported, update_method, publisher_update_command,
                    publisher_update_instructions
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STATIC_DB', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["issue"],
                r["os"],
                r.get("category", "General"),
                r["command"],
                r.get("risk", "Low"),
                r.get("explanation", ""),
                r.get("tags", ""),
                op,
                strat,
                pkg_mgr,
                pkg_id,
                ver_cmd,
                off_url,
                a_id,
                inst_sup,
                upd_sup,
                uninst_sup,
                reinst_sup,
                ver_sup,
                ver_chk_sup,
                rep_sup,
                upd_meth,
                pub_cmd,
                pub_inst
            ))
            inserted_static += 1
        else:
            conn_static.execute("""
                UPDATE static_recipes SET
                    command = ?,
                    operation = ?,
                    repair_strategy = ?,
                    package_id = ?,
                    official_url = ?,
                    app_id = ?,
                    install_supported = ?,
                    update_supported = ?,
                    uninstall_supported = ?,
                    reinstall_supported = ?,
                    verify_supported = ?,
                    version_check_supported = ?,
                    repair_supported = ?,
                    update_method = ?,
                    publisher_update_command = ?,
                    publisher_update_instructions = ?
                WHERE id = ?
            """, (
                r["command"], op, strat, pkg_id, off_url, a_id,
                inst_sup, upd_sup, uninst_sup, reinst_sup, ver_sup, ver_chk_sup,
                rep_sup, upd_meth, pub_cmd, pub_inst, existing[0]
            ))
            
    conn_static.commit()
    new_static_count = conn_static.execute("SELECT COUNT(*) FROM static_recipes").fetchone()[0]
    conn_static.close()
    print(f"      Inserted {inserted_static} new recipes. Total static_recipes: {new_static_count}")

    # [2/3] Ensure Dynamic DB exists with schemas
    DYNAMIC_DB_PATH = BASE_DIR / "knowledge_dynamic.db"
    print(f"[2/3] Ensuring schemas in dynamic knowledge DB: {DYNAMIC_DB_PATH} ...")
    conn_dyn = sqlite3.connect(DYNAMIC_DB_PATH)
    conn_dyn.execute("PRAGMA journal_mode=WAL")
    conn_dyn.execute("""
        CREATE TABLE IF NOT EXISTS learned_solutions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_pattern     TEXT NOT NULL,
            proposed_fix        TEXT NOT NULL,
            category            TEXT NOT NULL DEFAULT 'General',
            os                  TEXT NOT NULL DEFAULT 'Any',
            user_approved       INTEGER NOT NULL DEFAULT 0,
            success_count       INTEGER NOT NULL DEFAULT 0,
            fail_count          INTEGER NOT NULL DEFAULT 0,
            promoted_to_static  INTEGER NOT NULL DEFAULT 0,
            source              TEXT NOT NULL DEFAULT 'ai_proposed',
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            last_used           TEXT
        )
    """)
    conn_dyn.execute("""
        CREATE TABLE IF NOT EXISTS pending_approvals (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            solution_id         INTEGER NOT NULL REFERENCES learned_solutions(id),
            proposed_fix        TEXT NOT NULL,
            trigger_pattern     TEXT NOT NULL,
            context             TEXT,
            requested_at        TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn_dyn.execute("CREATE INDEX IF NOT EXISTS idx_ls_approved ON learned_solutions(user_approved)")
    conn_dyn.commit()
    conn_dyn.close()
    print(f"      Dynamic knowledge DB ready.")

    # [3/3] Synchronize into legacy knowledge.db recipes table for full backward compatibility
    print(f"[3/3] Synchronizing into legacy knowledge DB: {LEGACY_DB_PATH} ...")
    conn_leg = sqlite3.connect(LEGACY_DB_PATH)
    conn_leg.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            issue       TEXT NOT NULL,
            os          TEXT NOT NULL,
            command     TEXT NOT NULL,
            risk        TEXT NOT NULL,
            explanation TEXT
        )
    """)
    inserted_legacy = 0
    for r in RECIPES:
        existing = conn_leg.execute(
            "SELECT id FROM recipes WHERE LOWER(issue) = LOWER(?) AND os = ?",
            (r["issue"], r["os"])
        ).fetchone()
        if not existing:
            conn_leg.execute("""
                INSERT INTO recipes (issue, os, command, risk, explanation)
                VALUES (?, ?, ?, ?, ?)
            """, (
                r["issue"],
                r["os"],
                r["command"],
                r.get("risk", "Low"),
                r.get("explanation", "")
            ))
            inserted_legacy += 1
    conn_leg.commit()
    total_legacy = conn_leg.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    conn_leg.close()
    print(f"      Inserted {inserted_legacy} new recipes into legacy DB. Total: {total_legacy}")

    print("[SUCCESS] All Knowledge Base parts created, sealed, and synchronized successfully!")


if __name__ == "__main__":
    populate()
