use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use rand::distributions::Alphanumeric;
use rand::Rng;
use tauri::{Emitter, Manager, State};

use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::time::sleep;

// ─── Shared App State ────────────────────────────────────────────────────────
//
// `process`    – the Child handle for the Python backend we spawned (None if
//                not spawned by us, or already stopped).
// `api_token`  – secret generated at startup, injected into the Python process
//                via env so the HTTP middleware can validate callers.
// `status`     – last known status string ("offline"|"starting"|"online"|
//                "external"|"stopping"|"error").
// `starting`   – concurrency guard; true while a spawn attempt is in progress.
//                Prevents duplicate backend processes if the user clicks
//                "Start Backend" while auto-start is still waiting.

struct BackendState {
    process:   Option<Child>,
    api_token: String,
    status:    String,
    starting:  bool,
}

impl BackendState {
    fn new(token: String) -> Self {
        Self {
            process:   None,
            api_token: token,
            status:    "offline".into(),
            starting:  false,
        }
    }
}

type SharedBackend = Arc<Mutex<BackendState>>;

// ─── Helper: token generator ──────────────────────────────────────────────────

fn generate_token() -> String {
    rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(64)
        .map(char::from)
        .collect()
}

// ─── Helper: locate python interpreter ───────────────────────────────────────
//
// Prefer the venv interpreter inside backend/.venv so we always get the exact
// dependencies installed there, rather than the system-wide Python.

fn find_python(backend_dir: &PathBuf) -> PathBuf {
    let venv = if cfg!(windows) {
        backend_dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        backend_dir.join(".venv").join("bin").join("python")
    };
    if venv.exists() {
        venv
    } else if cfg!(windows) {
        PathBuf::from("python")
    } else {
        PathBuf::from("python3")
    }
}

// ─── Helper: locate backend directory ────────────────────────────────────────
//
// Walks up from the exe location (at most 8 levels) looking for a directory
// named "backend" that contains "main.py".  This works whether we are running
// `tauri dev` (exe is deep inside target/debug) or a packaged binary.

fn find_backend_dir() -> Option<PathBuf> {
    // 1. Check current working directory
    if let Ok(cwd) = std::env::current_dir() {
        let candidate = cwd.join("backend");
        if candidate.join("main.py").exists() {
            return Some(candidate);
        }
        if cwd.join("main.py").exists() {
            return Some(cwd);
        }
    }

    // 2. Check parents of executable location
    if let Ok(exe_path) = std::env::current_exe() {
        let mut dir = exe_path.parent().map(|p| p.to_path_buf());
        for _ in 0..8 {
            if let Some(ref d) = dir {
                let candidate = d.join("backend");
                if candidate.join("main.py").exists() {
                    return Some(candidate);
                }
                dir = d.parent().map(|p| p.to_path_buf());
            } else {
                break;
            }
        }
    }

    // 3. Fallback: check project root path
    if let Ok(home) = std::env::var("USERPROFILE").or_else(|_| std::env::var("HOME")) {
        let fallback = PathBuf::from(home)
            .join(".gemini")
            .join("antigravity")
            .join("scratch")
            .join("pc-doc")
            .join("backend");
        if fallback.join("main.py").exists() {
            return Some(fallback);
        }
    }

    None
}

// ─── Helper: health probe ─────────────────────────────────────────────────────
//
// Returns true if the backend /health endpoint responds with HTTP < 500.
// Timeout is kept short (800 ms) so callers don't block the UI for long.

async fn check_health() -> bool {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_millis(1500))
        .build()
    {
        Ok(c)  => c,
        Err(_) => return false,
    };
    client
        .get("http://127.0.0.1:8765/health")
        .send()
        .await
        .map(|r| r.status().as_u16() < 500)
        .unwrap_or(false)
}

// ─── Helper: wait for backend to become healthy ───────────────────────────────
//
// Polls `check_health()` every 350 ms until either it returns true or the
// deadline (ms milliseconds) is exceeded.

async fn wait_online(ms: u64) -> bool {
    let deadline = Instant::now() + Duration::from_millis(ms);
    while Instant::now() < deadline {
        if check_health().await {
            return true;
        }
        sleep(Duration::from_millis(350)).await;
    }
    false
}

// ─── Helper: kill orphaned process on port ────────────────────────────────────
//
// Called ONLY when we already know the backend is NOT healthy (check_health()
// returned false) but something is still listening on port 8765 — i.e. a
// zombie/orphan from a previous crashed session.
//
// Safety guarantee: we call this function only after confirming `!check_health()`,
// so we never kill a healthy backend that we (or the user) intentionally started.
//
// On Linux/macOS: uses `fuser -k <port>/tcp` (fast, kills the whole process
// group), with a `ss -tlnp` + kill -9 fallback for systems without fuser.
//
// On Windows: uses `netstat -ano` to find the PID and `taskkill /F /PID`.

async fn kill_orphaned_on_port(port: u16) {
    #[cfg(unix)]
    {
        // Fast path via fuser.  Exit code 1 means nothing was killed (no
        // process on that port), which is also fine.
        let killed = Command::new("fuser")
            .args(["-k", "-KILL", &format!("{port}/tcp")])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .await
            .map(|s| s.code().unwrap_or(1) == 0)   // fuser exits 0 if it killed something
            .unwrap_or(false);

        if killed {
            // Give the kernel time to release the socket/TIME_WAIT.
            sleep(Duration::from_millis(500)).await;
            return;
        }

        // Fallback 1: `lsof -t -i:<port>` (very standard on Linux/macOS, does not require root)
        let mut lsof_killed = false;
        if let Ok(out) = Command::new("lsof")
            .args(["-t", &format!("-i:{port}")])
            .output()
            .await
        {
            let stdout = String::from_utf8_lossy(&out.stdout);
            for line in stdout.lines() {
                let pid_str = line.trim();
                if let Ok(pid) = pid_str.parse::<u32>() {
                    let _ = Command::new("kill")
                        .args(["-9", &pid.to_string()])
                        .status()
                        .await;
                    lsof_killed = true;
                }
            }
        }

        if lsof_killed {
            sleep(Duration::from_millis(500)).await;
            return;
        }

        // Fallback 2: `ss -tlnp` (requires root privileges/sudo to see process names/PIDs)
        // Example line:
        //   LISTEN 0 128 127.0.0.1:8765  0.0.0.0:* users:(("python",pid=12345,fd=6))
        if let Ok(out) = Command::new("ss")
            .args(["-tlnp"])
            .output()
            .await
        {
            let stdout = String::from_utf8_lossy(&out.stdout);
            for line in stdout.lines() {
                // Match only lines that reference our specific port.
                if !line.contains(&format!(":{port}")) {
                    continue;
                }
                // Extract every "pid=<N>" token from the line.
                for segment in line.split("pid=").skip(1) {
                    let pid_str = segment.split(',').next().unwrap_or("").trim();
                    if let Ok(pid) = pid_str.parse::<u32>() {
                        let _ = Command::new("kill")
                            .args(["-9", &pid.to_string()])
                            .status()
                            .await;
                    }
                }
            }
            sleep(Duration::from_millis(500)).await;
        }
    }

    #[cfg(windows)]
    {
        let ps_cmd = format!(
            "Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"
        );
        let _ = Command::new("powershell")
            .args(["-NoProfile", "-Command", &ps_cmd])
            .status()
            .await;
        sleep(Duration::from_millis(500)).await;
    }
}

// ─── Core: do_start_backend ───────────────────────────────────────────────────
//
// Single authoritative function that both the auto-start (setup hook) and the
// manual "Start Backend" command call.  Having one code path avoids drift.
//
// Steps:
//   1. If backend is already healthy → return its current status immediately.
//   2. Set the concurrency guard (starting = true).
//   3. Kill any orphaned process on port 8765 (only safe because health check
//      already confirmed the port is NOT serving a live backend).
//   4. Spawn Python, pipe stdout/stderr to the Tauri console.
//   5. Store the Child handle so stop_backend() can kill it cleanly.
//   6. Wait up to `timeout_ms` for /health to respond.
//   7. Clear the concurrency guard and emit the final status.

async fn do_start_backend(
    state:      &SharedBackend,
    app_handle: &tauri::AppHandle,
    timeout_ms: u64,
) -> String {
    // ── 1. Already healthy? ───────────────────────────────────────────────
    if check_health().await {
        let mut s = state.lock().unwrap();
        let status = if s.process.is_some() { "online" } else { "external" };
        s.status   = status.into();
        // Clear the guard if it somehow got stuck.
        s.starting = false;
        let _ = app_handle.emit("backend-status", status);
        return status.into();
    }

    // ── 2. Concurrency guard ──────────────────────────────────────────────
    {
        let mut s = state.lock().unwrap();
        if s.starting {
            // Another call is already spawning; just return current status.
            return s.status.clone();
        }
        s.starting = true;
        s.status   = "starting".into();
    }
    let _ = app_handle.emit("backend-status", "starting");

    // ── 3. Locate backend dir and python binary ───────────────────────────
    let backend_dir = match find_backend_dir() {
        Some(d) => d,
        None => {
            eprintln!("[PC Doctor] Cannot find backend/main.py");
            let mut s = state.lock().unwrap();
            s.status   = "error".into();
            s.starting = false;
            let _ = app_handle.emit("backend-status", "error");
            return "error".into();
        }
    };
    let main_py    = backend_dir.join("main.py");
    let python_bin = find_python(&backend_dir);
    let token      = state.lock().unwrap().api_token.clone();

    // ── 4. Kill orphaned process (safe: we already know health == false) ──
    kill_orphaned_on_port(8765).await;

    // ── 5. Spawn Python ───────────────────────────────────────────────────
    let child_result = Command::new(&python_bin)
        .arg(&main_py)
        .current_dir(&backend_dir)
        .env("PYTHONUNBUFFERED", "1")
        .env("PC_DOCTOR_API_TOKEN", &token)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn();

    let mut child = match child_result {
        Ok(c)  => c,
        Err(e) => {
            eprintln!("[PC Doctor] Failed to spawn Python: {e}");
            let mut s   = state.lock().unwrap();
            s.status    = "error".into();
            s.starting  = false;
            let _ = app_handle.emit("backend-status", "error");
            return "error".into();
        }
    };

    // Pipe stdout → tauri console (non-blocking background task).
    if let Some(stdout) = child.stdout.take() {
        tokio::spawn(async move {
            let mut lines = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                println!("[PC Doctor Backend] {line}");
            }
        });
    }

    // Pipe stderr → tauri console (non-blocking background task).
    if let Some(stderr) = child.stderr.take() {
        tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                eprintln!("[PC Doctor Backend ERR] {line}");
            }
        });
    }

    // Store the child handle so stop_backend can kill it.
    state.lock().unwrap().process = Some(child);

    // ── 6. Wait for the backend to become healthy ─────────────────────────
    let online = wait_online(timeout_ms).await;
    let status: &str = if online { "online" } else { "error" };

    // ── 7. Finalise state ─────────────────────────────────────────────────
    {
        let mut s = state.lock().unwrap();
        s.status   = status.into();
        s.starting = false;
    }
    let _ = app_handle.emit("backend-status", status);
    status.into()
}

// ─── Tauri Command: start_backend ─────────────────────────────────────────────

#[tauri::command]
async fn start_backend(
    state: State<'_, SharedBackend>,
    app:   tauri::AppHandle,
) -> Result<String, String> {
    // 12 s timeout for manual start (user is watching).
    Ok(do_start_backend(&state, &app, 12_000).await)
}

// ─── Tauri Command: stop_backend ──────────────────────────────────────────────
//
// Kills the child process we own, then waits up to 3 s for the port to clear.
// Reports "offline" if the port is free afterwards, or "external" if something
// else is still listening (e.g. the user started a separate backend).

#[tauri::command]
async fn stop_backend(
    state: State<'_, SharedBackend>,
    app:   tauri::AppHandle,
) -> Result<String, String> {
    let _ = app.emit("backend-status", "stopping");

    // Take the child out of the mutex BEFORE awaiting so we don't hold the
    // lock across an await point (would block other threads).
    let child_opt = state.lock().unwrap().process.take();

    if let Some(mut child) = child_opt {
        // kill() sends SIGKILL; then wait() reaps the zombie.
        let _ = child.kill().await;
        let _ = child.wait().await;
    }

    // Give the OS up to 3 s to release the socket.
    let deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < deadline {
        if !check_health().await {
            break;
        }
        sleep(Duration::from_millis(250)).await;
    }

    let status: &str = if check_health().await { "external" } else { "offline" };
    {
        let mut s = state.lock().unwrap();
        s.status   = status.into();
        s.starting = false;
    }
    let _ = app.emit("backend-status", status);
    Ok(status.into())
}

// ─── Tauri Command: get_backend_status ───────────────────────────────────────
//
// Lightweight probe used by the frontend on startup to set the initial UI state
// without triggering a full start sequence.

#[tauri::command]
async fn get_backend_status(state: State<'_, SharedBackend>) -> Result<String, String> {
    if check_health().await {
        let has_proc = state.lock().unwrap().process.is_some();
        Ok(if has_proc { "online".into() } else { "external".into() })
    } else {
        Ok("offline".into())
    }
}

// Proxy for frontend → backend API calls.
// Used to route loopback fetches via the Rust client to bypass Webview
// Mixed Content / CORS security restrictions on local HTTP calls.

#[tauri::command]
async fn fetch_api(
    url:     String,
    method:  Option<String>,
    headers: Option<HashMap<String, String>>,
    body:    Option<String>,
    state:   State<'_, SharedBackend>,
) -> Result<serde_json::Value, String> {
    let token = state.lock().unwrap().api_token.clone();

    // Normalise relative /api/* paths to the full local URL.
    let full_url = if url.starts_with("/api") || (url.starts_with("api") && !url.starts_with("http")) {
        format!("http://127.0.0.1:8765/{}", url.trim_start_matches('/'))
    } else {
        url.clone()
    };

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;

    let http_method = method.unwrap_or_else(|| "GET".into()).to_uppercase();
    let mut req = match http_method.as_str() {
        "POST"   => client.post(&full_url),
        "PUT"    => client.put(&full_url),
        "DELETE" => client.delete(&full_url),
        "PATCH"  => client.patch(&full_url),
        _        => client.get(&full_url),
    };

    req = req.header("Authorization", format!("Bearer {token}"));

    if let Some(hdrs) = headers {
        for (k, v) in hdrs {
            req = req.header(k, v);
        }
    }
    if let Some(b) = body {
        req = req.header("Content-Type", "application/json").body(b);
    }

    let resp         = req.send().await.map_err(|e| e.to_string())?;
    let status       = resp.status().as_u16();
    let ok           = resp.status().is_success();
    let content_type = resp
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let text         = resp.text().await.unwrap_or_default();
    let body_json: Option<serde_json::Value> = if content_type.contains("application/json") {
        serde_json::from_str(&text).ok()
    } else {
        None
    };

    Ok(serde_json::json!({
        "ok":       ok,
        "status":   status,
        "bodyJson": body_json,
        "bodyText": text,
    }))
}

#[tauri::command]
fn log_console(msg: String) {
    println!("[JS Webview] {}", msg);
}

// ─── App Entry ────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let token:  String        = generate_token();
    let shared: SharedBackend = Arc::new(Mutex::new(BackendState::new(token)));
    let shared_for_setup      = shared.clone();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::default().level(log::LevelFilter::Info).build())
        .manage(shared)
        .invoke_handler(tauri::generate_handler![
            start_backend,
            stop_backend,
            get_backend_status,
            fetch_api,
            log_console,
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let state  = shared_for_setup.clone();

            // Auto-start backend in a background task so the window opens
            // immediately without waiting for Python to spin up.
            tauri::async_runtime::spawn(async move {
                // Use a generous 20 s timeout for auto-start since the user
                // isn't actively watching a spinner.
                do_start_backend(&state, &handle, 20_000).await;
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Tauri application");

    app.run(move |app_handle, event| {
        // On window close, kill the backend we own so it doesn't become an
        // orphan on the next launch.
        if let tauri::RunEvent::Exit = event {
            let state = app_handle.state::<SharedBackend>();
            let mut s = state.lock().unwrap();
            if let Some(mut child) = s.process.take() {
                // start_kill() is synchronous (doesn't need an async runtime)
                // which is safe here because we're inside the event callback.
                let _ = child.start_kill();
            }
        }
    });
}
