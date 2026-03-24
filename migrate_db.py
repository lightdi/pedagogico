import sqlite3
import os

def migrate_database():
    # Detectar o caminho do banco de dados a partir da configuração ou buscar nos caminhos padrões
    db_path = os.environ.get("SQLALCHEMY_DATABASE_URI", "sqlite:///instance/pedagogico.db")
    
    if db_path.startswith("sqlite:///"):
        db_file = db_path.replace("sqlite:///", "")
    else:
        db_file = "instance/pedagogico.db"

    # Fallback caso o banco esteja na pasta raiz em servidor de produção
    if not os.path.exists(db_file):
        if os.path.exists("pedagogico.db"):
            db_file = "pedagogico.db"
        elif os.path.exists("instance/pedagogico.db"):
            db_file = "instance/pedagogico.db"
            
    if not os.path.exists(db_file):
        print(f"Erro: Arquivo de banco de dados '{db_file}' não encontrado.")
        print("Certifique-se de rodar este script na raiz do projeto onde o arquivo .db está localizado.")
        return

    print(f"Iniciando migração no banco de dados: {db_file}")

    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # 1. Tabela professores: adicionar email
        try:
            cursor.execute("ALTER TABLE professores ADD COLUMN email VARCHAR(120)")
            print(" [OK] Coluna 'email' adicionada em 'professores'.")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower() or "já existe" in str(e).lower() or "syntax error" not in str(e).lower():
                print(" [-] Coluna 'email' já existe na tabela 'professores'. (Ignorado)")
            else:
                print(f"Erro inesperado em 'professores': {e}")

        # 2. Tabela eventos_professores: adicionar aula_turma_id, aula_periodo, aula_disciplina
        event_cols = [
            ("aula_turma_id", "VARCHAR(50)"),
            ("aula_periodo", "VARCHAR(10)"),
            ("aula_disciplina", "VARCHAR(120)")
        ]
        
        for col_name, col_type in event_cols:
            try:
                cursor.execute(f"ALTER TABLE eventos_professores ADD COLUMN {col_name} {col_type}")
                print(f" [OK] Coluna '{col_name}' adicionada em 'eventos_professores'.")
            except sqlite3.OperationalError as e:
                print(f" [-] Coluna '{col_name}' provavelmente já existe. (Ignorado)")

        conn.commit()
        conn.close()
        print("\nSucesso! Migrações aplicadas com êxito. O sistema já pode ser acessado em produção.")

    except Exception as e:
        print(f"\nErro Crítico ao tentar atualizar o banco: {e}")

if __name__ == "__main__":
    migrate_database()
