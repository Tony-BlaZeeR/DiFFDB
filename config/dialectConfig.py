engines = {
        "sqlite": "sqlite:///{database}",
        "postgresql": "postgresql://{user}:{password}@{host}:{port}/{database}",
        "mysql": "mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}",
        "sqlserver": "mssql+pyodbc://{user}:{password}@{host}/{database}?driver=SQL+Server",
        "oracle": "oracle+cx_oracle://{user}:{password}@{host}:{port}/{database}"
    }

query_templates = {
        "postgresql": {
            "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
            "modify": "ALTER TABLE {table} ALTER COLUMN {column} TYPE {type};",
            "drop": "ALTER TABLE {table} DROP COLUMN {column};"
        },
        "mysql": {
            "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
            "modify": "ALTER TABLE {table} MODIFY COLUMN {column} {type};",
            "drop": "ALTER TABLE {table} DROP COLUMN {column};"
        },
        "oracle": {
            "add": "ALTER TABLE {table} ADD {column} {type};",
            "modify": "ALTER TABLE {table} MODIFY {column} {type};",
            "drop": "ALTER TABLE {table} DROP COLUMN {column};"
        },
        "sqlserver": {
            "add": "ALTER TABLE {table} ADD {column} {type};",
            "modify": "ALTER TABLE {table} ALTER COLUMN {column} {type};",
            "drop": "ALTER TABLE {table} DROP COLUMN {column};"
        },
        "sqlite": {
            "add": "ALTER TABLE {table} ADD COLUMN {column} {type};",
            "modify": "/* SQLite non supporta ALTER COLUMN, richiede la ricreazione della tabella */",
            "drop": "/* SQLite non supporta DROP COLUMN direttamente */"
        }
    }