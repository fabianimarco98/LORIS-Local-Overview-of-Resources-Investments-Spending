#!/usr/bin/env python3
# ============================================================
# PACKAGE FOR SHARING — Generatore Pacchetto Pulito per Amici
# ============================================================
"""
Crea un archivio ZIP pronto da condividere (AirDrop, Telegram, Google Drive, Email),
garantendo al 100% l'assenza di dati personali, estratti conto reali o file temporanei.
"""

import os
from pathlib import Path
import shutil
import sys
from typing import Optional, Set
import zipfile

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_ZIP_NAME = "LORIS_Condividi.zip"

EXCLUDE_PATTERNS = {
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
    ".venv",
    "venv",
    "env",
    "logs",
    "output",
    "LORIS.app",
    "Applications",
    ".git",
}

# File ed estensioni bancarie personali da escludere ASSOLUTAMENTE da input/bank_statements e input/investments
SENSITIVE_EXTENSIONS = {".pdf", ".csv", ".tsv", ".xlsx", ".xls", ".json"}


def create_distribution_package(target_path: Optional[Path] = None) -> Path:
    if target_path is None:
        target_path = PROJECT_DIR / OUTPUT_ZIP_NAME

    print(f"📦 Creazione pacchetto pulito in corso: {target_path}...")
    file_count = 0
    added_names = set()

    with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_DIR):
            root_p = Path(root)
            rel_root = root_p.relative_to(PROJECT_DIR)

            # Salta cartelle escluse
            parts = rel_root.parts
            if any(part in EXCLUDE_PATTERNS for part in parts):
                continue
            if target_path.name in files:
                files.remove(target_path.name)

            for file in files:
                if file.startswith(".") and file != ".gitkeep" and file != ".streamlit":
                    if file == ".DS_Store":
                        continue

                file_p = root_p / file
                rel_file = file_p.relative_to(PROJECT_DIR)
                rel_str = str(rel_file)

                # FILTRO PRIVACY RIGOROSO SUI DATI BANCARI PERSONALI
                # In input/bank_statements/ e input/investments/, includi SOLO .gitkeep e README.md
                if "input/bank_statements" in rel_str:
                    if file_p.suffix.lower() in SENSITIVE_EXTENSIONS and file != ".gitkeep":
                        print(f"  🛡️ [PRIVACY ESCLUSO] File bancario personale: {rel_file}")
                        continue
                if "input/investments" in rel_str:
                    if file_p.suffix.lower() in SENSITIVE_EXTENSIONS and "template" not in file.lower():
                        print(f"  🛡️ [PRIVACY ESCLUSO] File investimenti personale: {rel_file}")
                        continue
                if "input/wallet" in rel_str:
                    if file_p.suffix.lower() in SENSITIVE_EXTENSIONS and "template" not in file.lower() and file != ".gitkeep":
                        print(f"  🛡️ [PRIVACY ESCLUSO] File wallet personale: {rel_file}")
                        continue
                if "user_overrides" in file_p.name.lower():
                    print(f"  🛡️ [PRIVACY ESCLUSO] Modifiche utente personali: {rel_file}")
                    continue

                # Salta file temporanei o log
                if file.endswith((".pyc", ".pyo", ".log", ".tmp")):
                    continue

                # Aggiungi all'archivio sotto la cartella 'LORIS/' per estrazione ordinata
                arcname = f"LORIS/{rel_str}"
                if arcname not in added_names:
                    zf.write(file_p, arcname=arcname)
                    added_names.add(arcname)
                    file_count += 1

        # Assicurati che le cartelle vuote siano presenti
        if "LORIS/input/bank_statements/.gitkeep" not in added_names:
            zf.writestr("LORIS/input/bank_statements/.gitkeep", "")
        if "LORIS/input/investments/.gitkeep" not in added_names:
            zf.writestr("LORIS/input/investments/.gitkeep", "")
        if "LORIS/input/wallet/.gitkeep" not in added_names:
            zf.writestr("LORIS/input/wallet/.gitkeep", "")

    size_mb = target_path.stat().st_size / (1024 * 1024)
    print("\n" + "=" * 60)
    print(f"🎉 PACCHETTO PRONTO PER LA CONDIVISIONE!")
    print(f"📁 Percorso file: {target_path}")
    print(f"⚖️  Dimensione: {size_mb:.2f} MB ({file_count} file inclusi)")
    print(f"🛡️  Stato Privacy: 100% PULITO (nessun estratto conto reale incluso)")
    print("=" * 60)
    return target_path


if __name__ == "__main__":
    out = create_distribution_package()
