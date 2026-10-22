# ============================================================
# USER PROFILE — dati personali caricati da file locale (gitignored)
# ============================================================
"""
Nome del titolare, datore di lavoro e parole chiave personali NON vanno scritti nel
codice: vivono in `input/user_profile.json` (ignorato da git e dallo zip di condivisione).
Percorso alternativo: variabile d'ambiente LORIS_USER_PROFILE.

Esempio:
{
  "owner_names": ["mario rossi"],
  "employer_keywords": ["acme gmbh"],
  "category_keywords": {"Affitto": ["musterstrasse"]},
  "tax_country": "IT"
}
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_cache: Tuple[Any, Dict[str, Any]] = (None, {})


def _profile_path() -> Path:
    env = os.environ.get("LORIS_USER_PROFILE")
    return Path(env) if env else _PROJECT_ROOT / "input" / "user_profile.json"


def get_profile() -> Dict[str, Any]:
    """Profilo corrente; ricaricato solo se il file cambia. Dict vuoto se assente/invalido."""
    global _cache
    path = _profile_path()
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        key = (str(path), None)
    if _cache[0] == key:
        return _cache[1]
    data: Dict[str, Any] = {}
    if key[1] is not None:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}
    _cache = (key, data)
    return data


def _lower_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip().lower() for v in value if str(v).strip()]


def owner_names() -> List[str]:
    return _lower_list(get_profile().get("owner_names"))


def employer_keywords() -> List[str]:
    return _lower_list(get_profile().get("employer_keywords"))


def extra_keywords(category: str) -> List[str]:
    cats = get_profile().get("category_keywords")
    return _lower_list(cats.get(category)) if isinstance(cats, dict) else []
