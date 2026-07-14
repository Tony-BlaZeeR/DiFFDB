"""Il parsing delle connessioni non deve rompersi sulle virgole nelle URL."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.connections import _parse  # noqa: E402


def test_conn_string_con_virgola():
    """SQL Server usa 'host,porta': lo split ingenuo su ',' faceva crashare l'app."""
    righe = ["prod,mssql+pyodbc://user:pwd@srv.local,1433/db?driver=SQL+Server"]
    connections = _parse(righe)
    assert len(connections) == 1
    assert connections[0].name == "prod"
    assert connections[0].conn_string.endswith("srv.local,1433/db?driver=SQL+Server")


def test_righe_vuote_e_commenti_ignorati():
    assert _parse(["", "   ", "# un commento", "db1,sqlite:///a.db"]) != []
    assert len(_parse(["", "# commento", "db1,sqlite:///a.db"])) == 1


def test_riga_malformata_ignorata_senza_crash():
    assert _parse(["senza_virgola", "nome,"]) == []
