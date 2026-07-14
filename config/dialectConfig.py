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
        "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
        "modify": "ALTER TABLE {table} ALTER COLUMN {column} TYPE {type};",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "create_sequence": "CREATE SEQUENCE {name} START WITH 1 INCREMENT BY 1;",
        "create_synonym": None,  # PostgreSQL non ha i sinonimi
    },
    "mysql": {
        "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
        "modify": "ALTER TABLE {table} MODIFY COLUMN {column} {type};",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "create_sequence": None,  # MySQL non ha le sequenze classiche
        "create_synonym": None,
    },
    "oracle": {
        "add": "ALTER TABLE {table} ADD {column} {type};",
        "modify": "ALTER TABLE {table} MODIFY {column} {type};",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "create_sequence": "CREATE SEQUENCE {name} START WITH 1 INCREMENT BY 1 NOCACHE;",
        "create_synonym": "CREATE SYNONYM {name} FOR {target};",
    },
    "mssql": {
        "add": "ALTER TABLE {table} ADD {column} {type};",
        "modify": "ALTER TABLE {table} ALTER COLUMN {column} {type};",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "create_sequence": "CREATE SEQUENCE {name} START WITH 1 INCREMENT BY 1;",
        "create_synonym": "CREATE SYNONYM {name} FOR {target};",
    },
    "sqlite": {
        "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
        "modify": "-- SQLite non supporta ALTER COLUMN: {table}.{column} ({type}) richiede di ricreare la tabella",
        "drop": "ALTER TABLE {table} DROP COLUMN {column};",
        "create_sequence": None,
        "create_synonym": None,
    },
}


def templates_for(dialect: str) -> dict:
    """Template del dialetto richiesto. Solleva ValueError se non supportato."""
    from utils.errorMessages import ErrorMessages, get_error_message

    d = normalize_dialect(dialect)
    if d not in query_templates:
        raise ValueError(get_error_message(ErrorMessages.DIALECT_NOT_SUPPORTED, dialect=dialect))
    return query_templates[d]
