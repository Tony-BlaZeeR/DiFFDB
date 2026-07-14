"""Scrittura degli output. Nessuna dipendenza da Qt: la usano sia la GUI sia la CLI."""

import os

from src.diff_DB import generate_excel_report, generate_sql_scripts, write_sql_script


def write_outputs(diff, output_dir: str):
    """Report Excel e uno script SQL per ciascuna direzione."""
    os.makedirs(output_dir, exist_ok=True)

    excel_path = os.path.join(output_dir, "differenze_ambienti.xlsx")
    generate_excel_report(diff, excel_path)
    written = [excel_path]

    for target in (diff.snapshot1.env_name, diff.snapshot2.env_name):
        scripts = generate_sql_scripts(diff, target)
        if not any(scripts.values()):
            continue
        sql_path = os.path.join(output_dir, f"allinea_{slug(target)}.sql")
        write_sql_script(scripts, sql_path, target)
        written.append(sql_path)

    return written


def slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text).strip("_").lower() or "target"
