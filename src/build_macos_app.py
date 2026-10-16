#!/usr/bin/env python3
"""
BUILD SCRIPT — Crea il bundle nativo LORIS.app per macOS.
- Genera AppIcon.icns con iconutil
- Compila il binary nativo Swift con Cocoa e WebKit
- Crea la struttura standard .app (Contents/MacOS, Contents/Resources, Info.plist)
- Applica firma ad-hoc con codesign
- Crea un alias/collegamento in ~/Applications per integrazione Spotlight e Dock
"""

import os
import shutil
import subprocess
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
MACOS_DIR = SRC_DIR / "macos_app"
APP_NAME = "LORIS.app"
APP_BUNDLE = PROJECT_ROOT / APP_NAME


def build():
    print("=" * 68)
    print(" 🐾 CREAZIONE BUNDLE NATIVO MACOS: LORIS.app")
    print("=" * 68)

    # 1. Generazione Icona Nativa (.icns)
    icns_path = MACOS_DIR / "AppIcon.icns"
    if not icns_path.exists():
        print("🎨 Generazione AppIcon.icns in corso...")
        subprocess.run([
            "/opt/homebrew/Caskroom/miniforge/base/envs/previsione_spese/bin/python",
            str(MACOS_DIR / "generate_icon.py")
        ], check=True)
    else:
        print("🎨 Icona nativa trovata: AppIcon.icns")

    # 2. Compilazione Binary Swift
    swift_src = MACOS_DIR / "main.swift"
    binary_dest = MACOS_DIR / "LORIS"
    print("⚡ Compilazione binario nativo macOS (Swift 6.x + Cocoa + WebKit)...")
    cmd_swift = [
        "swiftc",
        "-O",
        "-framework", "Cocoa",
        "-framework", "WebKit",
        str(swift_src),
        "-o", str(binary_dest)
    ]
    subprocess.run(cmd_swift, check=True)
    print(f"✅ Binario compilato con successo: {binary_dest}")

    # 3. Creazione Struttura Bundle LORIS.app
    if APP_BUNDLE.exists():
        shutil.rmtree(APP_BUNDLE)

    contents_dir = APP_BUNDLE / "Contents"
    macos_bin_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"

    macos_bin_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Copia binario eseguibile
    shutil.copy2(binary_dest, macos_bin_dir / "LORIS")
    os.chmod(macos_bin_dir / "LORIS", 0o755)

    # Copia icona ICNS e assets PNG
    shutil.copy2(icns_path, resources_dir / "AppIcon.icns")
    assets_dir = SRC_DIR / "assets"
    if (assets_dir / "loris_icon_128.png").exists():
        shutil.copy2(assets_dir / "loris_icon_128.png", resources_dir / "loris_icon_128.png")
    if (assets_dir / "loris_icon.png").exists():
        shutil.copy2(assets_dir / "loris_icon.png", resources_dir / "loris_icon.png")

    # Creazione PkgInfo
    with open(contents_dir / "PkgInfo", "w") as f:
        f.write("APPL????")

    # Creazione Info.plist
    info_plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>it</string>
    <key>CFBundleExecutable</key>
    <string>LORIS</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.marcofabiani.loris</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>LORIS</string>
    <key>CFBundleDisplayName</key>
    <string>LORIS</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>4.0.0</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleVersion</key>
    <string>4.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key>
    <true/>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
</dict>
</plist>
"""
    with open(contents_dir / "Info.plist", "w", encoding="utf-8") as f:
        f.write(info_plist_content)

    print(f"📦 Bundle creato in: {APP_BUNDLE}")

    # 4. Firma Ad-Hoc con codesign per macOS Security
    print("🔐 Applicazione firma di sicurezza ad-hoc (codesign)...")
    try:
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP_BUNDLE)], check=True)
        print("✅ Firma ad-hoc applicata correttamente.")
    except Exception as e:
        print(f"⚠️ Impossibile applicare firma codesign: {e}")

    # 5. Collegamento in ~/Applications (Accessibile da Spotlight & Launchpad)
    user_apps = Path.home() / "Applications"
    user_apps.mkdir(parents=True, exist_ok=True)
    target_link = user_apps / "LORIS.app"

    try:
        if target_link.is_symlink() or target_link.exists():
            if target_link.is_symlink():
                target_link.unlink()
            else:
                shutil.rmtree(target_link)
        target_link.symlink_to(APP_BUNDLE.resolve())
        print(f"🔗 Registrato in {target_link} (indicizzato da Spotlight e Finder)")
    except Exception as e:
        print(f"ℹ️ Nota creazione collegamento in ~/Applications: {e}")

    print("-" * 68)
    print("🎉 LORIS.app è ora un'applicazione nativa per macOS a tutti gli effetti!")
    print(f"👉 Per aprirla: fai doppio clic su '{APP_BUNDLE.name}' o digita 'open {APP_BUNDLE}'")
    print("👉 Puoi anche cercarla direttamente in Spotlight premendo Cmd+Spazio e scrivendo 'LORIS'!")
    print("=" * 68)


if __name__ == "__main__":
    build()
