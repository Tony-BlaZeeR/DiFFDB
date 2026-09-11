from enum import Enum


class ErrorMessages(Enum):
    TABLE_NOT_FOUND = "La tabella '{table}' non esiste nel database."
    TABLES_NAME_DIFFERENT = "I nomi delle tabelle non coincidono!"
    DIALECT_NOT_SUPPORTED = "Il dialetto '{dialect}' non è supportato."
    CONNECTION_FAILED = "Impossibile connettersi al database '{database}'. Verifica le credenziali."
    SQLA_CLOSE = "Errore nella chiusura della sessione: {error}"
    SQLA_QUERY = "Errore nell'esecuzione della query: {error}"

def get_error_message(error: ErrorMessages, **kwargs):
    return error.value.format(**kwargs)
