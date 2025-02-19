from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from utils.errorMessages import get_error_message, ErrorMessages

class DatabaseConnector:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def get_new_session(self) -> Session:
        return self.SessionLocal()

    def close_session(self: Session):
        try:
            self.close()
        except SQLAlchemyError as e:
            raise SQLAlchemyError(get_error_message(ErrorMessages.SQLA_CLOSE, error=e))

    def execute_query(self, query: str):
        session = self.get_new_session()
        try:
            result = session.execute(query)
            session.commit()
            return result.fetchall()
        except SQLAlchemyError as e:
            session.rollback()
            raise SQLAlchemyError(get_error_message(ErrorMessages.SQLA_QUERY, error=e))
        finally:
            self.close_session()

    def test_connection(self) -> bool:
        try:
            with self.engine.connect() as conn:
                return conn.closed == False
        except SQLAlchemyError as e:
            print(f"Errore di connessione: {e}")
            return False

    def dispose_engine(self):
        self.engine.dispose()