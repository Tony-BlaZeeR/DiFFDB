"""Scrittura degli output. Nessuna dipendenza da Qt: la usano sia la GUI sia la CLI."""

import os

from src.diff_DB import generate_excel_report, generate_sql_scripts, write_sql_script


def write_excel(diff, output_dir: str) -> str:
    """Solo il report Excel. Restituisce il percorso scritto."""
    os.makedirs(output_dir, exist_ok=True)
    excel_path = os.path.join(output_dir, "differenze_ambienti.xlsx")
    generate_excel_report(diff, excel_path)
    return excel_path


def write_sql(diff, output_dir: str):
    """Uno script SQL per direzione. Restituisce i percorsi scritti (puo' essere vuoto)."""
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for target in (diff.snapshot1.env_name, diff.snapshot2.env_name):
        scripts = generate_sql_scripts(diff, target)
        if not any(scripts.values()):
            continue
        sql_path = os.path.join(output_dir, f"allinea_{slug(target)}.sql")
        write_sql_script(scripts, sql_path, target)
        written.append(sql_path)
    return written


def write_outputs(diff, output_dir: str):
    """Report Excel piu' gli script SQL (usato dalla CLI)."""
    return [write_excel(diff, output_dir), *write_sql(diff, output_dir)]


def slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text).strip("_").lower() or "target"
