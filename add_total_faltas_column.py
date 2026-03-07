"""
Adiciona a coluna total_faltas na tabela boletins_disciplinas, se ainda nao existir.
Execute uma unica vez apos atualizar o modelo BoletimDisciplina com total_faltas:
  python add_total_faltas_column.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    from app import app, db
    from sqlalchemy import text
    with app.app_context():
        if "sqlite" not in db.engine.url.drivername:
            print("Use apenas com SQLite ou adicione a coluna manualmente.")
            return
        with db.engine.connect() as conn:
            r = conn.execute(text("PRAGMA table_info(boletins_disciplinas)"))
            cols = [row[1] for row in r]
            if "total_faltas" in cols:
                print("Coluna total_faltas ja existe.")
                return
            conn.execute(text("ALTER TABLE boletins_disciplinas ADD COLUMN total_faltas INTEGER NOT NULL DEFAULT 0"))
            conn.commit()
            print("Coluna total_faltas adicionada.")
            # Atualizar registros existentes com a soma dos bimestres
            conn.execute(text("""
                UPDATE boletins_disciplinas
                SET total_faltas = falta_b1 + falta_b2 + falta_b3 + falta_b4
            """))
            conn.commit()
            print("Registros existentes atualizados com total de faltas.")

if __name__ == "__main__":
    main()
