use std::sync::Mutex;
use std::sync::mpsc::{Receiver, channel};
use std::time::Duration;

use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};

/// Packaged backend process (PyInstaller one-folder build shipped as resource "backend/").
struct Backend {
    child: CommandChild,
    exited: Receiver<()>,
}

struct BackendState(Mutex<Option<Backend>>);

fn spawn_backend(app: &tauri::App) -> Result<Option<Backend>, Box<dyn std::error::Error>> {
    let resources = app.path().resource_dir()?;
    let exe = resources.join("backend").join(if cfg!(windows) { "xqc-backend.exe" } else { "xqc-backend" });
    if !exe.is_file() {
        eprintln!("[xqc-backend] dev mode: {} not found, start the backend manually (python -m app)", exe.display());
        return Ok(None);
    }
    let engine = resources.join("pikafish").join(if cfg!(windows) { "pikafish.exe" } else { "pikafish" });
    let (mut rx, child) = app
        .shell()
        .command(exe)
        .env("XQC_PORT", "8765")
        .env("XQC_PIKAFISH_PATH", engine)
        .env("XQC_EXIT_ON_STDIN_EOF", "1")
        .set_process_group(true) // job object on Windows: the fallback kill also takes down Pikafish
        .spawn()?;
    let (tx, exited) = channel();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    eprintln!("[xqc-backend] {}", String::from_utf8_lossy(&line).trim_end())
                }
                CommandEvent::Error(err) => eprintln!("[xqc-backend] error: {err}"),
                CommandEvent::Terminated(p) => {
                    eprintln!("[xqc-backend] exited: code {:?}", p.code);
                    let _ = tx.send(());
                }
                _ => {}
            }
        }
    });
    Ok(Some(Backend { child, exited }))
}

/// Ask the backend to stop (a line on stdin -> uvicorn shutdown, engine quit, DB closed); kill after 3 s.
fn stop_backend(app: &AppHandle) {
    let Some(state) = app.try_state::<BackendState>() else { return };
    let backend = state.0.lock().unwrap().take();
    if let Some(Backend { mut child, exited }) = backend {
        let _ = child.write(b"\n");
        if exited.recv_timeout(Duration::from_secs(3)).is_err() {
            let _ = child.kill();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Must be first: a second launch focuses this window and exits before spawning its own backend.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // A failed spawn must not stop the UI: the frontend shows "backend offline".
            let backend = spawn_backend(app).unwrap_or_else(|e| {
                eprintln!("[xqc-backend] failed to start: {e}");
                None
            });
            app.manage(BackendState(Mutex::new(backend)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_backend(app);
            }
        });
}
