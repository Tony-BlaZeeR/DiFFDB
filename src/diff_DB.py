from sqlalchemy import create_engine, inspect
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO)

def compare_environments(env1_name, conn_str1, env2_name, conn_str2, schema1=None, schema2=None):
    with create_engine(conn_str1).connect() as conn1, create_engine(conn_str2).connect() as conn2:
        inspector1 = inspect(conn1)
        inspector2 = inspect(conn2)

        tables_env1 = set(inspector1.get_table_names(schema=schema1))
        tables_env2 = set(inspector2.get_table_names(schema=schema2))

        views_env1 = set(inspector1.get_view_names(schema=schema1))
        views_env2 = set(inspector2.get_view_names(schema=schema2))

        synonyms_env1 = set(inspector1.get_schema_names())
        synonyms_env2 = set(inspector2.get_schema_names())

        sequences_env1 = set(inspector1.get_sequence_names(schema=schema1))
        sequences_env2 = set(inspector2.get_sequence_names(schema=schema2))

        common_tables = tables_env1.intersection(tables_env2)
        missing_tables_in_env1 = tables_env2 - tables_env1
        missing_tables_in_env2 = tables_env1 - tables_env2

        common_views = views_env1.intersection(views_env2)
        missing_views_in_env1 = views_env2 - views_env1
        missing_views_in_env2 = views_env1 - views_env2

        common_synonyms = synonyms_env1.intersection(synonyms_env2)
        missing_synonyms_in_env1 = synonyms_env2 - synonyms_env1
        missing_synonyms_in_env2 = synonyms_env1 - synonyms_env2

        common_sequences = sequences_env1.intersection(sequences_env2)
        missing_sequences_in_env1 = sequences_env2 - sequences_env1
        missing_sequences_in_env2 = sequences_env1 - sequences_env2

        table_diffs = []
        view_diffs = []
        synonym_diffs = []
        sequence_diffs = []

        for table in missing_tables_in_env1:
            table_diffs.append({'Nome': table, 'Ambiente': env1_name, 'Campo': None})
        for table in missing_tables_in_env2:
            table_diffs.append({'Nome': table, 'Ambiente': env2_name, 'Campo': None})

        for table in common_tables:
            columns_env1 = {col['name'] for col in inspector1.get_columns(table, schema=schema1)}
            columns_env2 = {col['name'] for col in inspector2.get_columns(table, schema=schema2)}
            missing_columns_in_env1 = columns_env2 - columns_env1
            missing_columns_in_env2 = columns_env1 - columns_env2

            for column in missing_columns_in_env1:
                table_diffs.append({'Nome': table, 'Ambiente': env1_name, 'Campo': column})
            for column in missing_columns_in_env2:
                table_diffs.append({'Nome': table, 'Ambiente': env2_name, 'Campo': column})

        for view in missing_views_in_env1:
            view_diffs.append({'Nome': view, 'Ambiente': env1_name})
        for view in missing_views_in_env2:
            view_diffs.append({'Nome': view, 'Ambiente': env2_name})

        for synonym in missing_synonyms_in_env1:
            synonym_diffs.append({'Nome': synonym, 'Ambiente': env1_name})
        for synonym in missing_synonyms_in_env2:
            synonym_diffs.append({'Nome': synonym, 'Ambiente': env2_name})

        for sequence in missing_sequences_in_env1:
            sequence_diffs.append({'Nome': sequence, 'Ambiente': env1_name})
        for sequence in missing_sequences_in_env2:
            sequence_diffs.append({'Nome': sequence, 'Ambiente': env2_name})

        return table_diffs, view_diffs, synonym_diffs, sequence_diffs

def generate_sql_scripts(table_diffs, view_diffs, synonym_diffs, sequence_diffs):
    scripts = {'tables': [], 'views': [], 'synonyms': [], 'sequences': []}

    for diff in table_diffs:
        if diff['Campo'] is None:
            scripts['tables'].append(f"CREATE TABLE {diff['Nome']} (...);")
        else:
            if diff['Ambiente'] in ['SVI', 'COL', 'PRE']:
                scripts['tables'].append(f"ALTER TABLE {diff['Nome']} ADD {diff['Campo']} ...;")
            else:
                scripts['tables'].append(f"ALTER TABLE {diff['Nome']} DROP COLUMN {diff['Campo']};")

    for diff in view_diffs:
        if diff['Ambiente'] in ['SVI', 'COL', 'PRE']:
            scripts['views'].append(f"CREATE VIEW {diff['Nome']} AS ...;")
        else:
            scripts['views'].append(f"DROP VIEW {diff['Nome']};")

    for diff in synonym_diffs:
        if diff['Ambiente'] in ['SVI', 'COL', 'PRE']:
            scripts['synonyms'].append(f"CREATE SYNONYM {diff['Nome']} FOR ...;")
        else:
            scripts['synonyms'].append(f"DROP SYNONYM {diff['Nome']};")

    for diff in sequence_diffs:
        if diff['Ambiente'] in ['SVI', 'COL', 'PRE']:
            scripts['sequences'].append(f"CREATE SEQUENCE {diff['Nome']} ...;")
        else:
            scripts['sequences'].append(f"DROP SEQUENCE {diff['Nome']};")

    return scripts

def generate_excel_report(table_diffs, view_diffs, synonym_diffs, sequence_diffs, filename):
    df_tables = pd.DataFrame(table_diffs)
    df_views = pd.DataFrame(view_diffs)
    df_synonyms = pd.DataFrame(synonym_diffs)
    df_sequences = pd.DataFrame(sequence_diffs)

    with pd.ExcelWriter(filename) as writer:
        df_tables.to_excel(writer, sheet_name='Tabelle', index=False)
        df_views.to_excel(writer, sheet_name='Viste', index=False)
        df_synonyms.to_excel(writer, sheet_name='Sinonimi', index=False)
        df_sequences.to_excel(writer, sheet_name='Sequenze', index=False)

    logging.info(f"Il report Excel è stato generato e salvato in '{filename}'.")