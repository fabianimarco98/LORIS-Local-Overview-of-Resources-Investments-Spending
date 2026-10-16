#!/usr/bin/env python3
# ============================================================
# PACKAGE FOR SHARING — Generatore Pacchetto Pulito per Amici
# ============================================================
"""
Crea un archivio ZIP pronto da condividere (AirDrop, Telegram, Google Drive, Email).

Whitelist: l'archivio contiene SOLO i file tracciati da git (`git ls-files`), quindi
tutto ciò che è in .gitignore (estratti conto, override utente, build, zip, ecc.)
non può finire nel pacchetto. Come difesa aggiuntiva, in `input/` sono ammessi solo
README, template e .gitkeep.
"""

from pathlib import Path
import subprocess
from typing import List, Optional
import zipfile

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_ZIP_NAME = "LORIS_Condividi.zip"

# Cartelle vuote che l'app si aspetta di trovare
EMPTY_DIRS = ["input/bank_statements", "input/investments", "input/wallet"]


def _is_allowed(rel: str) -> bool:
    """Difesa in profondità: in input/ solo README, template e .gitkeep."""
    parts = Path(rel).parts
    if parts and parts[0] == "input":
        name = parts[-1]
        return name == ".gitkeep" or name == "README.md" or "templates" in parts or name.startswith("template_")
    return True


def list_shareable_files(project_dir: Path = PROJECT_DIR) -> List[str]:
    """File condivisibili: tracciati da git e ammessi dal filtro privacy."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=project_dir, capture_output=True, check=True
    ).stdout.decode("utf-8")
    files = [f for f in out.split("\0") if f]
    return [f for f in files if (project_dir / f).is_file() and _is_allowed(f)]


def create_distribution_package(target_path: Optional[Path] = None) -> Path:
    if target_path is None:
        target_path = PROJECT_DIR / OUTPUT_ZIP_NAME

    print(f"📦 Creazione pacchetto pulito in corso: {target_path}...")
    files = list_shareable_files()

    with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(PROJECT_DIR / rel, arcname=f"LORIS/{rel}")
        for d in EMPTY_DIRS:
            if f"{d}/.gitkeep" not in files:
                zf.writestr(f"LORIS/{d}/.gitkeep", "")

    size_mb = target_path.stat().st_size / (1024 * 1024)
    print("\n" + "=" * 60)
    print("🎉 PACCHETTO PRONTO PER LA CONDIVISIONE!")
    print(f"📁 Percorso file: {target_path}")
    print(f"⚖️  Dimensione: {size_mb:.2f} MB ({len(files)} file inclusi, solo file tracciati da git)")
    print("=" * 60)
    return target_path


if __name__ == "__main__":
    create_distribution_package()
