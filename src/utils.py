import logging

from PyQt5 import QtWidgets
from sqlalchemy import create_engine, inspect
import sqlalchemy.exc
from diff_DB import compare_environments, generate_sql_scripts, generate_excel_report

def compare_environments(env1, conn_str1, env2, conn_str2):
    try:
        with create_engine(conn_str1).connect() as conn1, create_engine(conn_str2).connect() as conn2:
            inspector1 = inspect(conn1)
            inspector2 = inspect(conn2)

            table_diffs, view_diffs, synonym_diffs, sequence_diffs = compare_environments(env1, conn_str1, env2, conn_str2)

            scripts = generate_sql_scripts(table_diffs, view_diffs, synonym_diffs, sequence_diffs)
            with open('script_mancanti.sql', 'w') as f:
                for script_type in scripts:
                    f.write(f"-- {script_type.capitalize()} Scripts --\n")
                    for script in scripts[script_type]:
                        f.write(script + '\n')

            logging.info("Gli script SQL per gli oggetti mancanti sono stati generati e salvati in 'script_mancanti.sql'.")
            generate_excel_report(table_diffs, view_diffs, synonym_diffs, sequence_diffs, 'differenze_ambienti.xlsx')
    except sqlalchemy.exc.DatabaseError as e:
        logging.error(f"Database connection error: {e}")
        QtWidgets.QMessageBox.critical(None, "Database Error", f"Failed to connect to the database: {e}")