#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dump obsahu zadané složky (ve stejném adresáři jako tento skript) do TXT.
- Zapíše hierarchii (strom) adresářů.
- Zařadí obsah textových souborů (primárně .py, ale klidně i další).
- Lze definovat, které soubory/složky vynechat (glob patterny).
- Bezpečně přeskočí binární / příliš velké soubory.

Použití:
    python dump_folder.py --folder CILOVA_SLOZKA --out dump.txt
nebo jen uprav proměnnou FOLDER_NAME níže.
"""

from __future__ import annotations
import argparse
import fnmatch
import os
from pathlib import Path
from datetime import datetime
from typing import Iterable, List

# === Nastavení, které si můžeš upravit ===

# Název složky vedle skriptu (pokud nezadáš --folder)
FOLDER_NAME = "final"

# Kam se uloží výstup (pokud nezadáš --out), soubor vznikne vedle skriptu
DEFAULT_OUTPUT = "dump.txt"

# Vzorky složek, které se ve stromu i dumpech přeskočí
EXCLUDE_DIR_PATTERNS: List[str] = [
    ".git", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".venv", "venv", ".idea", ".vscode", ".DS_Store"
]

# Vzorky souborů, které se přeskočí (glob)
EXCLUDE_FILE_PATTERNS: List[str] = [
    "*.pyc", "*.pyo", "*.so", "*.dll", "*.dylib",
    "*.exe", "*.bin",
    "*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.ico",
    "*.pdf", "*.zip", "*.tar", "*.tar.*", "*.gz", "*.7z", "*.rar",
    "*.db", "*.sqlite*", "*.log",
    "dump.txt"  # aby se do sebe sama nenasypal
]

# Maximální velikost souboru pro vložení do dumpu (v MB). None = bez limitu
MAX_FILE_SIZE_MB: float | None = 2.0

# Kódování pro čtení textových souborů
READ_ENCODING = "utf-8"


# === Implementace ===

def match_any(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)

def is_binary_file(path: Path, sample_bytes: int = 2048) -> bool:
    """
    Heuristika: když najdeme NUL byte v úvodním vzorku, považuj za binární.
    """
    try:
        with path.open("rb") as f:
            chunk = f.read(sample_bytes)
        if b"\x00" in chunk:
            return True
        # Pokus o dekódování jen jako lehká kontrola; selhání -> spíš binární
        try:
            chunk.decode(READ_ENCODING)
        except UnicodeDecodeError:
            return True
    except Exception:
        # Když soubor nejde přečíst, raději ho považuj za binární (a přeskoč)
        return True
    return False

def build_tree_lines(root: Path) -> List[str]:
    """
    Vytvoří řádky se stromem adresářů (ASCII), respektuje EXCLUDE_DIR_PATTERNS / EXCLUDE_FILE_PATTERNS.
    """
    lines: List[str] = [f"{root.name}/"]

    def _walk(dir_path: Path, prefix: str = ""):
        # Seřadit: napřed složky, pak soubory, oba abecedně
        try:
            entries = sorted(list(dir_path.iterdir()), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        # Odfiltruj
        entries = [
            p for p in entries
            if not (p.is_dir() and match_any(p.name, EXCLUDE_DIR_PATTERNS))
            and not (p.is_file() and match_any(p.name, EXCLUDE_FILE_PATTERNS))
        ]

        for i, p in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            line = f"{prefix}{connector}{p.name}"
            if p.is_dir():
                lines.append(line + "/")
                new_prefix = f"{prefix}    " if i == len(entries) - 1 else f"{prefix}│   "
                _walk(p, new_prefix)
            else:
                lines.append(line)

    _walk(root)
    return lines

def iter_files(root: Path) -> Iterable[Path]:
    """
    Projde všechny soubory pod rootem s respektem na EXCLUDE vzory.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        # Vyřaď složky přímo v os.walk (in-place)
        dirnames[:] = [d for d in dirnames if not match_any(d, EXCLUDE_DIR_PATTERNS)]
        # Soubory
        for fname in sorted(filenames, key=str.lower):
            if match_any(fname, EXCLUDE_FILE_PATTERNS):
                continue
            path = Path(dirpath) / fname
            yield path

def should_skip_content(path: Path) -> tuple[bool, str | None]:
    """
    Rozhodne, zda přeskočit obsah (binární/velký). Vrací (skip, důvod).
    """
    if MAX_FILE_SIZE_MB is not None:
        try:
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                return True, f"Soubor přeskočen (velikost {size_mb:.2f} MB > {MAX_FILE_SIZE_MB} MB)."
        except Exception:
            return True, "Soubor přeskočen (nešlo zjistit velikost)."
    if is_binary_file(path):
        return True, "Soubor přeskočen (binární / nečitelné jako text)."
    return False, None

def dump_folder(root: Path, out_file: Path) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with out_file.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# DUMP SLOŽKY\n")
        out.write(f"Kořen: {root.resolve()}\n")
        out.write(f"Vytvořeno: {now}\n")
        out.write(f"Vynechané složky (glob): {EXCLUDE_DIR_PATTERNS}\n")
        out.write(f"Vynechané soubory (glob): {EXCLUDE_FILE_PATTERNS}\n")
        if MAX_FILE_SIZE_MB is not None:
            out.write(f"Limit velikosti souboru: {MAX_FILE_SIZE_MB} MB\n")
        out.write("\n")
        out.write("## STROM ADRESÁŘŮ\n")
        out.write("\n".join(build_tree_lines(root)))
        out.write("\n\n")
        out.write("## OBSAH SOUBORŮ\n")

        for file_path in iter_files(root):
            rel = file_path.relative_to(root)
            skip, reason = should_skip_content(file_path)

            out.write("\n")
            out.write(f"\n----- BEGIN: {rel.as_posix()} -----\n")
            if skip:
                out.write(f"{reason}\n")
            else:
                try:
                    with file_path.open("r", encoding=READ_ENCODING, errors="replace") as f:
                        out.write(f.read())
                        if not out.getvalue() if hasattr(out, "getvalue") else True:
                            pass  # placeholder pro kompatibilitu s různými writer objekty
                except Exception as e:
                    out.write(f"Soubor přeskočen (chyba čtení: {e}).\n")
            out.write(f"\n----- END: {rel.as_posix()} -----\n")

def main():
    
    parser = argparse.ArgumentParser(description="Vytvoří textový dump obsahu složky (strom + obsah souborů).")
    parser.add_argument(
        "--folder", "-f",
        help="Název cílové složky ležící ve stejném adresáři jako skript (přepíše FOLDER_NAME).",
        default=None
    )
    parser.add_argument(
        "--out", "-o",
        help="Cesta k výstupnímu TXT (výchozí: dump.txt vedle skriptu).",
        default=DEFAULT_OUTPUT
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    folder_name = args.folder if args.folder else FOLDER_NAME
    root = (script_dir / folder_name).resolve()
    out_file = (script_dir / args.out).resolve()

    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Chyba: složka '{root}' neexistuje nebo to není adresář.")

    dump_folder(root, out_file)
    print(f"Hotovo. Dump uložen do: {out_file}")

if __name__ == "__main__":
    main()