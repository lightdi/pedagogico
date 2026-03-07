"""
Script para apagar todos os dados de alunos, boletins e disciplinas,
e recriar as tabelas boletins_bimestrais e boletins_disciplinas com o novo esquema
(sem colunas de media/falta em boletins_bimestrais; notas apenas em boletins_disciplinas).

Execute uma unica vez apos a alteracao do modelo:
  python limpar_dados_boletins.py
"""
import os
import sys

# Garante que o app seja carregado a partir do diretorio do projeto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Aluno, BoletimBimestral, BoletimDisciplina

def main():
    with app.app_context():
        print("Apagando dados de BoletimDisciplina...")
        BoletimDisciplina.query.delete()
        print("Apagando dados de BoletimBimestral...")
        BoletimBimestral.query.delete()
        print("Apagando dados de Aluno...")
        Aluno.query.delete()
        db.session.commit()
        print("Dados apagados.")

        # SQLite: drop e recria as tabelas para aplicar o novo esquema (sem media/falta em boletins_bimestrais)
        from sqlalchemy import text
        if "sqlite" in db.engine.url.drivername:
            print("Recriando tabelas (SQLite)...")
            with db.engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS boletins_disciplinas"))
                conn.execute(text("DROP TABLE IF EXISTS boletins_bimestrais"))
                conn.commit()
            db.create_all()
            print("Tabelas recriadas com sucesso.")
        else:
            print("Banco nao e SQLite. Execute manualmente: DROP TABLE boletins_disciplinas; DROP TABLE boletins_bimestrais; e depois db.create_all() ou use migrations.")

if __name__ == "__main__":
    main()
