"""Confronto di due script DDL testuali (file .sql), senza connessione al DB.

Complementare a src/diff_DB.py, che invece confronta due database vivi.
"""

import sqlparse
from config.dialectConfig import templates_for
from utils.errorMessages import ErrorMessages, get_error_message

def get_table_name(tokens):
    for token in reversed(tokens):
        if token.ttype is None:
            return token.value
    return " "

def get_columns_and_types(columns):
    col_types = {}
    for col in columns:
        c = ' '.join(col.split()).split()
        c_name = c[0].replace('\"', "")
        c_type = " ".join(c[1:])
        col_types[c_name] = c_type
    return col_types

def parse_ddl(line):
    tablename = ""
    columns_and_types = {}
    parse = sqlparse.parse(line)
    for stmt in parse:
        tokens = [t for t in sqlparse.sql.TokenList(stmt.tokens)
                  if t.ttype != sqlparse.tokens.Whitespace]
        is_create_stmt = False
        for i, token in enumerate(tokens):
            if token.match(sqlparse.tokens.DDL, 'CREATE'):
                is_create_stmt = True
                continue
            if is_create_stmt and token.value.startswith("("):
                # Parse nome tabella
                tablename = get_table_name(tokens[:i])
                # Parse delle colonne e dei tipi
                txt = token.value
                columns_and_types = (
                    get_columns_and_types(txt[1:txt.rfind(")")].split(",\n")))
                break
    return tablename, columns_and_types

def compare_ddl(old_ddl: str, new_ddl: str, dialect = "postgresql"):
    old_table, old_columns = parse_ddl(old_ddl)
    new_table, new_columns = parse_ddl(new_ddl)

    dialect_queries = templates_for(dialect)

    if old_table != new_table:
        raise ValueError(get_error_message(ErrorMessages.TABLES_NAME_DIFFERENT))

    alter_statements = []

    for col, col_type in new_columns.items():
        if col not in old_columns:
            alter_statements.append(dialect_queries["add"].format(table=new_table, column=col, type=col_type))
        elif old_columns[col] != col_type:
            alter_statements.append(dialect_queries["modify"].format(table=new_table, column=col, type=col_type))

    for col in old_columns:
        if col not in new_columns:
            alter_statements.append(dialect_queries["drop"].format(table=new_table, column=col))

    return alter_statements