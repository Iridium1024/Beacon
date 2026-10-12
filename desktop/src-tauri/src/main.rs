#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .plugin(navigation_guard())
        .run(tauri::generate_context!())
        .expect("Beacon Desktop failed to start");
}

fn navigation_guard<R: tauri::Runtime>() -> tauri::plugin::TauriPlugin<R> {
    tauri::plugin::Builder::new("navigation-guard")
        .on_navigation(|_webview, url| {
            let bundled_asset = url.scheme() == "tauri"
                || (url.scheme() == "http" && url.host_str() == Some("tauri.localhost"));
            let development_asset = cfg!(debug_assertions)
                && url.scheme() == "http"
                && url.host_str() == Some("127.0.0.1")
                && url.port() == Some(1420);
            bundled_asset || development_asset
        })
        .build()
}
