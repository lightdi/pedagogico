import sqlite3
import os

def update_schema(db_path="instance/pedagogico.db"):
    if not os.path.exists(db_path):
        db_path = "pedagogico.db"
        if not os.path.exists(db_path):
            print("Erro: Banco de dados não encontrado. Rode o script no mesmo diretório do app.py ou dentro da pasta instance.")
            return

    print(f"Atualizando o banco de dados: {db_path}")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    commands = [
        # Coluna arquivo_reposicao da tabela eventos_professores (feature de upload anterior)
        "ALTER TABLE eventos_professores ADD COLUMN arquivo_reposicao VARCHAR(255);",
        
        # Colunas de eventos
        "ALTER TABLE eventos ADD COLUMN is_restrito BOOLEAN DEFAULT 0;",
        "ALTER TABLE eventos ADD COLUMN criador_id INTEGER REFERENCES users(id);",
        
        # Colunas de eventos de professor
        "ALTER TABLE eventos_professores ADD COLUMN is_restrito BOOLEAN DEFAULT 0;",
        "ALTER TABLE eventos_professores ADD COLUMN criador_id INTEGER REFERENCES users(id);",
        
        # Tabela associativa de eventos de alunos
        """
        CREATE TABLE evento_user_permitido (
            evento_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (evento_id, user_id),
            FOREIGN KEY(evento_id) REFERENCES eventos(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """,
        
        # Tabela associativa de eventos de professores
        """
        CREATE TABLE evento_professor_user_permitido (
            evento_professor_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (evento_professor_id, user_id),
            FOREIGN KEY(evento_professor_id) REFERENCES eventos_professores(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        """
    ]
    
    commands.extend([
        # Colunas de eventos no horário
        "ALTER TABLE professores ADD COLUMN email VARCHAR(255);",
        "ALTER TABLE eventos_professores ADD COLUMN aula_turma_id VARCHAR(255);",
        "ALTER TABLE eventos_professores ADD COLUMN aula_periodo VARCHAR(50);",
        "ALTER TABLE eventos_professores ADD COLUMN aula_disciplina VARCHAR(255);"
    ])

    for cmd in commands:
        try:
            c.execute(cmd)
            print("Executado com sucesso:", cmd.split("\n")[0][:60], "...")
        except sqlite3.OperationalError as e:
            # Ignora erros de "duplicate column" ou "table already exists"
            if "duplicate column name" in str(e).lower() or "table" in str(e).lower() and "already exists" in str(e).lower():
                print(f"Ignorado (já existia): {cmd.split(chr(10))[0][:60]}...")
            else:
                print(f"Erro ao executar: {cmd}\nMotivo: {e}")
        except Exception as e:
            print(f"Erro inesperado em {cmd}: {e}")

    conn.commit()
    conn.close()
    print("Atualização finalizada!")

if __name__ == "__main__":
    update_schema()
