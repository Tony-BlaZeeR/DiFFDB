"""Template SQL per dialetto.

Le chiavi sono i nomi dei dialetti SQLAlchemy (engine.dialect.name), cosi' il
tipo di database si ricava direttamente dall'engine invece di essere indovinato.
"""

engines = {
    "sqlite": "sqlite:///{database}",
    "postgresql": "postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}",
    "mysql": "mysql+pymysql://{user}:{password}@{host}:{port}/{database}",
    "mssql": "mssql+pyodbc://{user}:{password}@{host}/{database}?driver=SQL+Server",
    "oracle": "oracle+cx_oracle://{user}:{password}@{host}:{port}/{database}",
}

# Alias accettati in input, normalizzati sui nomi dei dialetti SQLAlchemy.
DIALECT_ALIASES = {
    "sqlserver": "mssql",
    "postgres": "postgresql",
    "psql": "postgresql",
    "oracledb": "oracle",
}

SUPPORTED_DIALECTS = ("postgresql", "mysql", "oracle", "mssql", "sqlite")


def normalize_dialect(dialect: str) -> str:
    d = (dialect or "").lower()
    return DIALECT_ALIASES.get(d, d)


query_templates = {
    "postgresql": {
        "drop_check": None,   # usa drop_constraint
        "drop_table": "DROP TABLE {table};",
        "drop_index": "DROP INDEX {index};",
        "drop_constraint": "ALTER TABLE {table} DROP CONSTRAINT {name};",
        "drop_foreign_key": None,   # usa drop_constraint
        "drop_view": "DROP VIEW {name};",
        "drop_trigger": "DROP TRIGGER {name} ON {table};",
        "drop_sequence": "DROP SEQUENCE {name};",
        "drop_synonym": None,
        # PostgreSQL sa annullare un DDL: lo script sta in una transazione.
        "begin": "BEGIN;",
        "commit": "COMMIT;",
        "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
        "modify": "ALTER TABLE {table} ALTER COLUMN {column} TYPE {type};",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "set_default": "ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default};",
        "drop_default": "ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT;",
        # ALTER COLUMN ... TYPE non tocca la nullability (e non accetta NOT NULL).
        "modify_nullability": "never",
        "alter_add_constraint": True,
        "view_or_replace": True,   # supporta CREATE OR REPLACE VIEW
        "sequences": True,
        "alter_sequence": "ALTER SEQUENCE {name} INCREMENT BY {increment} RESTART WITH {start};",
        "create_synonym": None,  # PostgreSQL non ha i sinonimi
    },
    "mysql": {
        "drop_check": "ALTER TABLE {table} DROP CHECK {name};",
        "drop_table": "DROP TABLE {table};",
        "drop_index": "DROP INDEX {index} ON {table};",
        "drop_constraint": "ALTER TABLE {table} DROP INDEX {name};",
        "drop_foreign_key": "ALTER TABLE {table} DROP FOREIGN KEY {name};",
        "drop_view": "DROP VIEW {name};",
        "drop_trigger": "DROP TRIGGER {name};",
        "drop_sequence": None,
        "drop_synonym": None,
        # MySQL fa commit implicito a ogni DDL: non c'e' transazione da aprire.
        "begin": None,
        "commit": None,
        "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
        "modify": "ALTER TABLE {table} MODIFY COLUMN {column} {type};",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "set_default": "ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default};",
        "drop_default": "ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT;",
        # MODIFY riscrive la colonna da capo: quello che non si ripete va perso.
        "modify_nullability": "always",
        "alter_add_constraint": True,
        "view_or_replace": True,
        "sequences": False,  # MySQL non ha le sequenze classiche
        "alter_sequence": None,
        "create_synonym": None,
    },
    "oracle": {
        "drop_check": None,   # usa drop_constraint
        "drop_table": "DROP TABLE {table};",
        "drop_index": "DROP INDEX {index};",
        "drop_constraint": "ALTER TABLE {table} DROP CONSTRAINT {name};",
        "drop_foreign_key": None,   # usa drop_constraint
        "drop_view": "DROP VIEW {name};",
        "drop_trigger": "DROP TRIGGER {name};",
        "drop_sequence": "DROP SEQUENCE {name};",
        "drop_synonym": "DROP SYNONYM {name};",
        # Oracle fa commit implicito a ogni DDL: non c'e' transazione da aprire.
        "begin": None,
        "commit": None,
        "add": "ALTER TABLE {table} ADD {column} {type};",
        "modify": "ALTER TABLE {table} MODIFY {column} {type};",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "set_default": "ALTER TABLE {table} MODIFY {column} DEFAULT {default};",
        "drop_default": "ALTER TABLE {table} MODIFY {column} DEFAULT NULL;",
        # MODIFY conserva gli attributi, e ripetere un NOT NULL gia' presente e'
        # un errore (ORA-01442): si riafferma solo quando cambia davvero.
        "modify_nullability": "when_changed",
        "alter_add_constraint": True,
        "view_or_replace": True,
        "sequences": True,
        "alter_sequence": "ALTER SEQUENCE {name} INCREMENT BY {increment};",
        "create_synonym": "CREATE SYNONYM {name} FOR {target};",
    },
    "mssql": {
        "drop_check": None,   # usa drop_constraint
        "drop_table": "DROP TABLE {table};",
        "drop_index": "DROP INDEX {index} ON {table};",
        "drop_constraint": "ALTER TABLE {table} DROP CONSTRAINT {name};",
        "drop_foreign_key": None,   # usa drop_constraint
        "drop_view": "DROP VIEW {name};",
        "drop_trigger": "DROP TRIGGER {name};",
        "drop_sequence": "DROP SEQUENCE {name};",
        "drop_synonym": "DROP SYNONYM {name};",
        # SQL Server sa annullare un DDL: lo script sta in una transazione.
        "begin": "BEGIN TRANSACTION;",
        "commit": "COMMIT TRANSACTION;",
        "add": "ALTER TABLE {table} ADD {column} {type};",
        "modify": "ALTER TABLE {table} ALTER COLUMN {column} {type};",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        # Su SQL Server il default e' un constraint con nome proprio: per cambiarlo
        # va prima eliminato quello esistente. Si segnala invece di generare SQL fragile.
        "set_default": None,
        "drop_default": None,
        # ALTER COLUMN senza NULL/NOT NULL esplicito rende la colonna nullable.
        "modify_nullability": "always",
        "alter_add_constraint": True,
        "view_or_replace": False,  # niente OR REPLACE: si usa DROP + CREATE
        "sequences": True,
        "alter_sequence": "ALTER SEQUENCE {name} RESTART WITH {start} INCREMENT BY {increment};",
        "create_synonym": "CREATE SYNONYM {name} FOR {target};",
    },
    "sqlite": {
        "drop_check": None,
        "drop_table": "DROP TABLE {table};",
        "drop_index": "DROP INDEX {index};",
        "drop_constraint": None,
        "drop_foreign_key": None,
        "drop_view": "DROP VIEW {name};",
        "drop_trigger": "DROP TRIGGER {name};",
        "drop_sequence": None,
        "drop_synonym": None,
        # SQLite sa annullare un DDL.
        "begin": "BEGIN;",
        "commit": "COMMIT;",
        "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
        "modify": ("-- SQLite non supporta ALTER COLUMN: {table}.{column} ({type}) "
                   "richiede di ricreare la tabella"),
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "set_default": None,   # SQLite non sa cambiare il default di una colonna esistente
        "drop_default": None,
        "modify_nullability": "never",  # il modify e' comunque solo un commento
        "alter_add_constraint": False,  # SQLite non aggiunge vincoli a tabelle esistenti
        "view_or_replace": False,
        "sequences": False,
        "alter_sequence": None,
        "create_synonym": None,
    },
}


def templates_for(dialect: str) -> dict:
    """Template del dialetto richiesto. Solleva ValueError se non supportato."""
    from diffdb.utils.errorMessages import ErrorMessages, get_error_message

    d = normalize_dialect(dialect)
    if d not in query_templates:
        raise ValueError(get_error_message(ErrorMessages.DIALECT_NOT_SUPPORTED, dialect=dialect))
    return query_templates[d]
