// ============================================================
// LORIS — Native macOS Desktop Host Application
// Written in Swift with AppKit & WebKit
// ============================================================
import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var childProcess: Process?
    var targetPort: Int = 8502
    var projectPath: String = ""
    var isServerReady: Bool = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        setupMainMenu()
        locateProjectPath()
        setupWindow()
        startOrConnectBackend()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        terminateBackend()
    }

    // MARK: - Localizzazione Directory Progetto
    func locateProjectPath() {
        // 1. Controlla cartella genitore del bundle .app
        let bundleURL = Bundle.main.bundleURL.resolvingSymlinksInPath()
        let candidate1 = bundleURL.deletingLastPathComponent().path
        if FileManager.default.fileExists(atPath: candidate1 + "/src/app_streamlit.py") || FileManager.default.fileExists(atPath: candidate1 + "/app_streamlit.py") {
            projectPath = candidate1
            return
        }

        // 2. Controlla path standard di sviluppo
        let candidate2 = "/Users/USER/Documents/projects/expenses_prediction/v4_speciale"
        if FileManager.default.fileExists(atPath: candidate2 + "/src/app_streamlit.py") || FileManager.default.fileExists(atPath: candidate2 + "/app_streamlit.py") {
            projectPath = candidate2
            return
        }

        // 3. Fallback sulla directory corrente
        projectPath = FileManager.default.currentDirectoryPath
    }

    // MARK: - Configurazione Finestra Principale
    func setupWindow() {
        let screenRect = NSScreen.main?.visibleFrame ?? NSRect(x: 100, y: 100, width: 1320, height: 860)
        let initialWidth: CGFloat = min(1340, screenRect.width * 0.9)
        let initialHeight: CGFloat = min(880, screenRect.height * 0.9)
        let x = (screenRect.width - initialWidth) / 2 + screenRect.origin.x
        let y = (screenRect.height - initialHeight) / 2 + screenRect.origin.y

        let windowRect = NSRect(x: x, y: y, width: initialWidth, height: initialHeight)

        let style: NSWindow.StyleMask = [
            .titled,
            .closable,
            .miniaturizable,
            .resizable
        ]

        window = NSWindow(contentRect: windowRect, styleMask: style, backing: .buffered, defer: false)
        window.title = "LORIS — Local Overview of Resources, Investments & Spending"
        window.minSize = NSSize(width: 940, height: 620)
        window.delegate = self
        window.backgroundColor = NSColor(red: 11/255.0, green: 15/255.0, blue: 25/255.0, alpha: 1.0)
        window.appearance = NSAppearance(named: .darkAqua)
        window.titlebarAppearsTransparent = false
        window.titleVisibility = .visible

        // Configurazione WKWebView
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")

        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground") // Trasparente finché non carica

        window.contentView!.addSubview(webView)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // Schermata iniziale di caricamento elegante
        showLoadingScreen()
    }

    // MARK: - Splash / Loading Screen
    func showLoadingScreen() {
        let resourcePath = Bundle.main.resourcePath ?? ""
        let iconPath = "\(resourcePath)/loris_icon_128.png"
        let hasIcon = FileManager.default.fileExists(atPath: iconPath)
        let iconMarkup = hasIcon
            ? "<img src=\"file://\(iconPath)\" width=\"100\" height=\"100\" class=\"logo-img\" alt=\"LORIS\" />"
            : "<div class=\"logo\">🐾</div>"

        let html = """
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            * { box-sizing: border-box; }
            body {
              background-color: #0b0f19;
              color: #f8fafc;
              font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
              display: flex;
              flex-direction: column;
              align-items: center;
              justify-content: center;
              height: 100vh;
              margin: 0;
              user-select: none;
              -webkit-user-select: none;
            }
            .logo-img {
              border-radius: 22px;
              box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6), 0 0 20px rgba(56, 189, 248, 0.3);
              border: 2px solid rgba(56, 189, 248, 0.5);
              margin-bottom: 18px;
              animation: pulse 2.4s infinite ease-in-out;
            }
            .logo {
              font-size: 88px;
              margin-bottom: 8px;
              filter: drop-shadow(0 0 24px rgba(56, 189, 248, 0.35));
              animation: pulse 2.4s infinite ease-in-out;
            }
            h1 {
              margin: 0 0 6px 0;
              font-size: 32px;
              font-weight: 800;
              letter-spacing: 4px;
              background: linear-gradient(135deg, #f8fafc 0%, #94a3b8 100%);
              -webkit-background-clip: text;
              -webkit-text-fill-color: transparent;
            }
            p.sub {
              color: #38bdf8;
              font-size: 14px;
              font-weight: 500;
              letter-spacing: 1px;
              margin: 0 0 32px 0;
            }
            .spinner-container {
              position: relative;
              width: 44px;
              height: 44px;
              margin-bottom: 24px;
            }
            .spinner {
              width: 100%;
              height: 100%;
              border: 3.5px solid rgba(56, 189, 248, 0.15);
              border-top-color: #38bdf8;
              border-radius: 50%;
              animation: spin 0.75s linear infinite;
            }
            .status-text {
              color: #64748b;
              font-size: 13px;
              letter-spacing: 0.5px;
            }
            @keyframes spin { to { transform: rotate(360deg); } }
            @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.05); } }
          </style>
        </head>
        <body>
          \(iconMarkup)
          <h1>LORIS</h1>
          <p class="sub">LOCAL OVERVIEW OF RESOURCES, INVESTMENTS & SPENDING</p>
          <div class="spinner-container">
            <div class="spinner"></div>
          </div>
          <div class="status-text">Avvio del motore finanziario locale in corso...</div>
        </body>
        </html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // MARK: - Backend Management
    func isPortOpen(port: Int) -> Bool {
        guard let url = URL(string: "http://localhost:\(port)") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 0.5
        var ready = false
        let sema = DispatchSemaphore(value: 0)
        let task = URLSession.shared.dataTask(with: request) { _, response, _ in
            if let http = response as? HTTPURLResponse, (200...399).contains(http.statusCode) {
                ready = true
            }
            sema.signal()
        }
        task.resume()
        _ = sema.wait(timeout: .now() + 0.6)
        return ready
    }

    func findFreePort(startingAt start: Int) -> Int {
        var p = start
        while p < start + 20 {
            // Se la porta è già occupata e risponde a HTTP, potrebbe essere già LORIS
            if isPortOpen(port: p) {
                return p
            }
            // Verifica se libera per il bind
            var addr = sockaddr_in()
            addr.sin_family = sa_family_t(AF_INET)
            addr.sin_port = in_port_t(p).bigEndian
            addr.sin_addr.s_addr = in_addr_t(0)
            let sock = Darwin.socket(AF_INET, SOCK_STREAM, 0)
            let bindRes = withUnsafePointer(to: &addr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.bind(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
            Darwin.close(sock)
            if bindRes == 0 {
                return p
            }
            p += 1
        }
        return start
    }

    func startOrConnectBackend() {
        targetPort = findFreePort(startingAt: 8502)

        // Se risponde già, colleghiamoci subito
        if isPortOpen(port: targetPort) {
            self.loadAppURL()
            return
        }

        // Altrimenti avviamo il processo Streamlit in background
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }

            let pythonEnv = "/opt/homebrew/Caskroom/miniforge/base/envs/previsione_spese/bin/streamlit"
            let pythonBin = "/opt/homebrew/Caskroom/miniforge/base/envs/previsione_spese/bin/python"

            let proc = Process()
            proc.currentDirectoryURL = URL(fileURLWithPath: self.projectPath)

            let scriptRel = FileManager.default.fileExists(atPath: self.projectPath + "/src/app_streamlit.py")
                ? "src/app_streamlit.py"
                : "app_streamlit.py"

            if FileManager.default.fileExists(atPath: pythonEnv) {
                proc.executableURL = URL(fileURLWithPath: pythonEnv)
                proc.arguments = [
                    "run",
                    scriptRel,
                    "--server.port", String(self.targetPort),
                    "--server.headless", "true",
                    "--browser.serverAddress", "localhost",
                    "--browser.gatherUsageStats", "false"
                ]
            } else {
                proc.executableURL = URL(fileURLWithPath: pythonBin)
                proc.arguments = [
                    "-m", "streamlit", "run",
                    scriptRel,
                    "--server.port", String(self.targetPort),
                    "--server.headless", "true",
                    "--browser.serverAddress", "localhost",
                    "--browser.gatherUsageStats", "false"
                ]
            }

            var env = ProcessInfo.processInfo.environment
            env["PATH"] = "/opt/homebrew/Caskroom/miniforge/base/envs/previsione_spese/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
            env["PYTHONPATH"] = "\(self.projectPath)/src:\(self.projectPath):\(env["PYTHONPATH"] ?? "")"
            env["STREAMLIT_CONFIG_DIR"] = self.projectPath + "/.streamlit"
            proc.environment = env

            // Log su file
            let logDir = URL(fileURLWithPath: self.projectPath + "/logs")
            try? FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true)
            let logFile = logDir.appendingPathComponent("loris_app.log")
            if !FileManager.default.fileExists(atPath: logFile.path) {
                FileManager.default.createFile(atPath: logFile.path, contents: nil)
            }
            if let fileHandle = try? FileHandle(forWritingTo: logFile) {
                fileHandle.seekToEndOfFile()
                proc.standardOutput = fileHandle
                proc.standardError = fileHandle
            }

            do {
                try proc.run()
                self.childProcess = proc
            } catch {
                print("[ERROR] Impossibile avviare il processo backend: \(error)")
            }

            // Polling finché non è pronto
            self.pollServerUntilReady()
        }
    }

    func pollServerUntilReady() {
        var attempts = 0
        let maxAttempts = 50 // 15 secondi massimo

        while attempts < maxAttempts {
            Thread.sleep(forTimeInterval: 0.3)
            attempts += 1
            if isPortOpen(port: targetPort) {
                DispatchQueue.main.async { [weak self] in
                    self?.loadAppURL()
                }
                return
            }
        }

        // Se dopo 15s non risponde, mostra comunque l'URL o l'errore
        DispatchQueue.main.async { [weak self] in
            self?.loadAppURL()
        }
    }

    func loadAppURL() {
        guard let url = URL(string: "http://localhost:\(targetPort)") else { return }
        self.isServerReady = true
        let req = URLRequest(url: url)
        webView.load(req)
    }

    func terminateBackend() {
        if let proc = childProcess, proc.isRunning {
            proc.terminate()
            // Invia SIGTERM esplicito
            kill(proc.processIdentifier, SIGTERM)
            proc.waitUntilExit()
            childProcess = nil
        }
    }

    // MARK: - Native macOS Menu Bar
    func setupMainMenu() {
        let mainMenu = NSMenu()

        // 1. App Menu (LORIS)
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenuItem.submenu = appMenu

        appMenu.addItem(withTitle: "Informazioni su LORIS", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())

        let hideItem = NSMenuItem(title: "Nascondi LORIS", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(hideItem)

        let hideOthersItem = NSMenuItem(title: "Nascondi altre", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthersItem.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(hideOthersItem)

        appMenu.addItem(withTitle: "Mostra tutte", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "Esci da LORIS", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenu.addItem(quitItem)

        // 2. Edit Menu (fondamentale per copia/incolla nella WebView)
        let editMenuItem = NSMenuItem()
        mainMenu.addItem(editMenuItem)
        let editMenu = NSMenu(title: "Modifica")
        editMenuItem.submenu = editMenu

        editMenu.addItem(withTitle: "Annulla", action: Selector(("undo:")), keyEquivalent: "z")
        let redoItem = NSMenuItem(title: "Ripeti", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(redoItem)
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Taglia", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copia", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Incolla", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Seleziona tutto", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        // 3. View Menu
        let viewMenuItem = NSMenuItem()
        mainMenu.addItem(viewMenuItem)
        let viewMenu = NSMenu(title: "Vista")
        viewMenuItem.submenu = viewMenu

        let reloadItem = NSMenuItem(title: "Ricarica Pagina", action: #selector(reloadApp), keyEquivalent: "r")
        viewMenu.addItem(reloadItem)
        viewMenu.addItem(NSMenuItem.separator())
        let fullScreenItem = NSMenuItem(title: "Schermo Intero", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        fullScreenItem.keyEquivalentModifierMask = [.command, .control]
        viewMenu.addItem(fullScreenItem)

        // 4. Window Menu
        let windowMenuItem = NSMenuItem()
        mainMenu.addItem(windowMenuItem)
        let windowMenu = NSMenu(title: "Finestra")
        windowMenuItem.submenu = windowMenu

        windowMenu.addItem(withTitle: "Riduci a icona", action: #selector(NSWindow.miniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Ingrandisci", action: #selector(NSWindow.zoom(_:)), keyEquivalent: "")

        NSApp.mainMenu = mainMenu
    }

    @objc func showAbout() {
        let alert = NSAlert()
        alert.messageText = "LORIS — Primate Loris Edition"
        alert.informativeText = "Versione 4.0 (Build Speciale macOS)\n\nLocal Overview of Resources, Investments & Spending\n(Ispirato al primate notturno Loris / Nycticebus, famiglia Lorisidae)\n\nSistema di finanza personale 100% locale, basato unicamente su estratti conto bancari con AI locale e simulazione Monte Carlo stocastica.\n\nSviluppato per garantire riservatezza totale (Zero-Knowledge)."
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Chiudi")
        alert.runModal()
    }

    @objc func reloadApp() {
        if isServerReady {
            webView.reload()
        } else {
            loadAppURL()
        }
    }
}

// MARK: - Main Entry Point
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
