from utils.tableutils import *

old_ddl = """
CREATE TABLE utenti (
    id INT,
    nome VARCHAR(100),
    eta INT,
    altezza NUMBER
);
"""

new_ddl = """
CREATE TABLE utenti (
    id INT,
    nome VARCHAR(150),
    cognome VARCHAR(100),
    eta SMALLINT
);
"""

alter_script = compare_ddl(old_ddl, new_ddl)
for i in alter_script:
    print(i)