# Dashboard Pedagogico (Flask + SQLite + SQLAlchemy)

Projeto com login obrigatorio para acesso ao dashboard, gerenciamento de usuarios, cadastro de turmas, importacao de boletins em PDF e log de acoes.

## Tecnologias
- Flask
- SQLite
- SQLAlchemy (Flask-SQLAlchemy)
- Jinja2
- Bootstrap 5
- pypdf (leitura de boletim PDF)

## Requisitos
- Python 3.10+

## Como executar
1. Criar e ativar ambiente virtual:
   - Windows (PowerShell):
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
2. Instalar dependencias:
   ```powershell
   pip install -r requirements.txt
   ```
3. Executar a aplicacao:
   ```powershell
   python app.py
   ```
4. Acessar no navegador:
   - http://127.0.0.1:5000

## Credencial inicial
- Usuario: `admin`
- Senha: `2026ifpb!`

No primeiro start, se o banco estiver vazio, o sistema cria automaticamente o usuario admin inicial.

## Funcionalidades
- Login/logout
- Dashboard protegido por login
- Cadastro e listagem de usuarios (somente admin)
- Cadastro de nome de turmas (nome + serie) (somente admin)
- Cadastro de turmas (nome da turma + ano letivo) (somente admin)
- Importacao de boletim PDF por turma (somente admin)
- Cadastro/atualizacao de alunos por matricula (matricula como chave primaria)
- Registro de medias e faltas por bimestre
- Logs de acoes (somente admin)

## Regra da importacao de boletim
- Seleciona a turma e o arquivo PDF
- O sistema le o boletim aluno a aluno
- Se a matricula nao existir em `alunos`, cria o aluno
- Se a matricula ja existir, atualiza o nome (se necessario) e atualiza notas/faltas
- As medias por bimestre sao calculadas pela media das notas de todas as disciplinas no respectivo bimestre
- As faltas por bimestre sao a soma das faltas das disciplinas no respectivo bimestre

## Estrutura
- `app.py`: aplicacao Flask, modelos, parser PDF, rotas e bootstrap do admin
- `templates/`: telas Jinja2 com Bootstrap
- `static/css/ifpb.css`: tema visual IFPB
- `pedagogico.db`: banco SQLite (gerado automaticamente na primeira execucao)

