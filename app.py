import json
import os
import re
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

from flask import Flask, abort, flash, has_request_context, redirect, render_template, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ModuleNotFoundError:
    # Compatibilidade com ambientes legados que ainda usam PyPDF2.
    from PyPDF2 import PdfReader
    from PyPDF2.errors import PdfReadError
from sqlalchemy import UniqueConstraint
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
if os.environ.get("PROXY_FIX"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "SQLALCHEMY_DATABASE_URI", "sqlite:///pedagogico.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Suporte a subcaminho (ex.: /pedagogico) atras do Traefik com stripprefix
_application_root = os.environ.get("APPLICATION_ROOT", "").rstrip("/")
if _application_root:

    class ScriptNameFix:
        def __init__(self, app, script_name):
            self.app = app
            self.script_name = script_name

        def __call__(self, environ, start_response):
            environ["SCRIPT_NAME"] = self.script_name
            return self.app(environ, start_response)

    app.wsgi_app = ScriptNameFix(app.wsgi_app, _application_root)


db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Faca login para acessar o sistema."
login_manager.login_message_category = "warning"

PERIODO_OPTIONS = ("1º ano", "2º ano", "3º ano")


@app.context_processor
def inject_ano_dashboard():
    """Disponibiliza ano selecionado e anos disponiveis para a navbar (combo ano)."""
    if not has_request_context():
        return {}
    anos_disponiveis = []
    try:
        result = (
            db.session.query(Turma.ano_letivo)
            .distinct()
            .order_by(Turma.ano_letivo.desc())
            .all()
        )
        anos_disponiveis = [r[0] for r in result if r[0] is not None]
    except Exception:
        pass
    ano_url = request.args.get("ano", type=int)
    if ano_url is not None:
        session["ano_dashboard"] = ano_url
    ano_selecionado = ano_url or session.get("ano_dashboard")
    if ano_selecionado is None and anos_disponiveis:
        ano_selecionado = max(anos_disponiveis)
    if ano_selecionado is None:
        ano_selecionado = datetime.now().year
    if not anos_disponiveis:
        anos_disponiveis = [datetime.now().year]
    return {
        "anos_disponiveis": anos_disponiveis,
        "ano_selecionado": ano_selecionado,
    }


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    logs = db.relationship("ActionLog", back_populates="actor", lazy=True)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class TurmaNome(db.Model):
    __tablename__ = "turma_nomes"
    __table_args__ = (UniqueConstraint("nome", "periodo", name="uq_turma_nome_periodo"),)

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    periodo = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    turmas = db.relationship("Turma", back_populates="turma_nome", lazy=True)


class Turma(db.Model):
    __tablename__ = "turmas"
    __table_args__ = (UniqueConstraint("turma_nome_id", "ano_letivo", name="uq_turma_ano"),)

    id = db.Column(db.Integer, primary_key=True)
    turma_nome_id = db.Column(db.Integer, db.ForeignKey("turma_nomes.id"), nullable=False)
    ano_letivo = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    turma_nome = db.relationship("TurmaNome", back_populates="turmas")
    boletins = db.relationship("BoletimBimestral", back_populates="turma", lazy=True)


class Aluno(db.Model):
    __tablename__ = "alunos"

    matricula = db.Column(db.String(20), primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    boletins = db.relationship("BoletimBimestral", back_populates="aluno", lazy=True)


class BoletimBimestral(db.Model):
    """Vincula aluno a uma turma. Notas e frequencia ficam em BoletimDisciplina (uma por disciplina)."""
    __tablename__ = "boletins_bimestrais"
    __table_args__ = (UniqueConstraint("aluno_matricula", "turma_id", name="uq_boletim_aluno_turma"),)

    id = db.Column(db.Integer, primary_key=True)
    aluno_matricula = db.Column(db.String(20), db.ForeignKey("alunos.matricula"), nullable=False)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    aluno = db.relationship("Aluno", back_populates="boletins")
    turma = db.relationship("Turma", back_populates="boletins")
    disciplinas = db.relationship("BoletimDisciplina", back_populates="boletim", lazy=True, cascade="all, delete-orphan")

    def resumo_bimestres(self):
        """Calcula media e total de faltas por bimestre a partir das disciplinas."""
        if not self.disciplinas:
            return {"media_b1": 0.0, "falta_b1": 0, "media_b2": 0.0, "falta_b2": 0, "media_b3": 0.0, "falta_b3": 0, "media_b4": 0.0, "falta_b4": 0}
        n = len(self.disciplinas)
        return {
            "media_b1": round(sum(d.nota_b1 for d in self.disciplinas) / n, 2),
            "falta_b1": sum(d.falta_b1 for d in self.disciplinas),
            "media_b2": round(sum(d.nota_b2 for d in self.disciplinas) / n, 2),
            "falta_b2": sum(d.falta_b2 for d in self.disciplinas),
            "media_b3": round(sum(d.nota_b3 for d in self.disciplinas) / n, 2),
            "falta_b3": sum(d.falta_b3 for d in self.disciplinas),
            "media_b4": round(sum(d.nota_b4 for d in self.disciplinas) / n, 2),
            "falta_b4": sum(d.falta_b4 for d in self.disciplinas),
        }


class BoletimDisciplina(db.Model):
    __tablename__ = "boletins_disciplinas"

    id = db.Column(db.Integer, primary_key=True)
    boletim_id = db.Column(db.Integer, db.ForeignKey("boletins_bimestrais.id", ondelete="CASCADE"), nullable=False)

    nome_disciplina = db.Column(db.String(200), nullable=False)
    codigo_disciplina = db.Column(db.String(50), nullable=True)
    frequencia_percent = db.Column(db.Float, nullable=True)
    total_faltas = db.Column(db.Integer, nullable=False, default=0)

    nota_b1 = db.Column(db.Float, nullable=False, default=0.0)
    falta_b1 = db.Column(db.Integer, nullable=False, default=0)
    nota_b2 = db.Column(db.Float, nullable=False, default=0.0)
    falta_b2 = db.Column(db.Integer, nullable=False, default=0)
    nota_b3 = db.Column(db.Float, nullable=False, default=0.0)
    falta_b3 = db.Column(db.Integer, nullable=False, default=0)
    nota_b4 = db.Column(db.Float, nullable=False, default=0.0)
    falta_b4 = db.Column(db.Integer, nullable=False, default=0)

    boletim = db.relationship("BoletimBimestral", back_populates="disciplinas")


class ImportacaoBoletimPreview(db.Model):
    __tablename__ = "importacao_boletim_preview"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), nullable=False)
    arquivo_nome = db.Column(db.String(255), nullable=False)
    payload_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ActionLog(db.Model):
    __tablename__ = "action_logs"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    actor = db.relationship("User", back_populates="logs")


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def register_action(
    action: str,
    details: Optional[str] = None,
    user: Optional[User] = None,
    auto_commit: bool = True,
):
    actor = user
    if actor is None and current_user.is_authenticated:
        actor = current_user

    entry = ActionLog(
        action=action,
        details=details,
        actor=actor,
        ip_address=request.remote_addr if has_request_context() else None,
    )
    db.session.add(entry)
    if auto_commit:
        db.session.commit()


def bootstrap_admin_user():
    if User.query.count() > 0:
        return

    admin = User(
        username="admin",
        full_name="Administrador",
        role="admin",
    )
    admin.set_password("2026ifpb!")
    db.session.add(admin)
    db.session.flush()

    register_action(
        action="BOOTSTRAP_ADMIN",
        details="Primeiro usuario admin criado automaticamente.",
        user=admin,
        auto_commit=False,
    )
    db.session.commit()


def _extract_scores_by_subject(lines: list[str]) -> list[list[float]]:
    rows = _extract_subjects_with_scores(lines)
    return [
        [r["nota_b1"], r["falta_b1"], r["nota_b2"], r["falta_b2"], r["nota_b3"], r["falta_b3"], r["nota_b4"], r["falta_b4"]]
        for r in rows
    ]


def _extract_subjects_with_scores(lines: list[str]) -> list[dict]:
    """Extrai por disciplina: nome, frequencia e as 8 notas/faltas (n1,f1,n2,f2,n3,f3,n4,f4)."""
    result: list[dict] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        if not re.fullmatch(r"\d{5}", line):
            index += 1
            continue

        if index + 6 >= len(lines):
            index += 1
            continue

        if not re.fullmatch(r"\d+", lines[index + 2]):
            index += 1
            continue
        if not re.fullmatch(r"\d+", lines[index + 3]):
            index += 1
            continue
        if not re.fullmatch(r"\d+", lines[index + 4]):
            index += 1
            continue
        freq_token = lines[index + 5]
        if not (freq_token.endswith("%") or freq_token == "-"):
            index += 1
            continue

        nome_disciplina = lines[index + 1].strip() if index + 1 < len(lines) else ""
        try:
            frequencia = float(freq_token.replace("%", "").replace(",", ".").strip()) if freq_token != "-" else None
        except (ValueError, TypeError):
            frequencia = None

        probe = index + 7
        collected: list[float] = []
        max_probe = min(len(lines), index + 30)

        while probe < max_probe and len(collected) < 8:
            token = lines[probe].replace(",", ".")
            if token == "-":
                collected.append(0.0)
            elif re.fullmatch(r"\d+(?:\.\d+)?", token):
                collected.append(float(token))
            probe += 1

        if collected:
            if len(collected) < 8:
                collected.extend([0.0] * (8 - len(collected)))
            fb1, fb2, fb3, fb4 = int(round(collected[1])), int(round(collected[3])), int(round(collected[5])), int(round(collected[7]))
            result.append({
                "nome_disciplina": nome_disciplina or "Disciplina",
                "frequencia_percent": frequencia,
                "total_faltas": fb1 + fb2 + fb3 + fb4,
                "nota_b1": round(collected[0], 2),
                "falta_b1": fb1,
                "nota_b2": round(collected[2], 2),
                "falta_b2": fb2,
                "nota_b3": round(collected[4], 2),
                "falta_b3": fb3,
                "nota_b4": round(collected[6], 2),
                "falta_b4": fb4,
            })
            index = probe
            continue

        index += 1

    return result


def parse_boletim_pdf(file_obj) -> list[dict]:
    stream = file_obj.stream if hasattr(file_obj, "stream") else file_obj
    if hasattr(stream, "seek"):
        stream.seek(0)

    reader = PdfReader(stream, strict=False)
    students: list[dict] = []

    for page in reader.pages:
        text = page.extract_text() or ""

        # Aceita "Estudante:" (boletim em lote) ou "Aluno(a):" (boletim 1º/2º ano)
        name_match = re.search(
            r"(?:Estudante|Aluno\s*\(\s*a\s*\))\s*:\s*\n\s*([^\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        matricula_match = re.search(r"Matr[íi]cula:\s*\n(\d+)", text, flags=re.IGNORECASE)

        if not name_match or not matricula_match:
            continue

        nome = name_match.group(1).strip()
        matricula = matricula_match.group(1).strip()

        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
        disciplinas_rows = _extract_subjects_with_scores(lines)
        rows = _extract_scores_by_subject(lines)

        total_notas = [0.0, 0.0, 0.0, 0.0]
        total_faltas = [0, 0, 0, 0]

        if rows:
            for row in rows:
                for bim in range(4):
                    total_notas[bim] += float(row[bim * 2])
                    total_faltas[bim] += int(round(row[(bim * 2) + 1]))

            count_rows = len(rows)
            medias = [round(total_notas[bim] / count_rows, 2) for bim in range(4)]
        else:
            medias = [0.0, 0.0, 0.0, 0.0]

        students.append(
            {
                "matricula": matricula,
                "nome": nome,
                "media_primeiro_bimestre": medias[0],
                "falta_primeiro_bimestre": total_faltas[0],
                "media_segundo_bimestre": medias[1],
                "falta_segundo_bimestre": total_faltas[1],
                "media_terceiro_bimestre": medias[2],
                "falta_terceiro_bimestre": total_faltas[2],
                "media_quarto_bimestre": medias[3],
                "falta_quarto_bimestre": total_faltas[3],
                "disciplinas": disciplinas_rows,
            }
        )

    return students


def _load_preview(preview_id: Optional[int]) -> tuple[Optional[ImportacaoBoletimPreview], list[dict]]:
    if preview_id is None:
        return None, []

    preview = ImportacaoBoletimPreview.query.filter_by(id=preview_id, user_id=current_user.id).first()
    if preview is None:
        return None, []

    try:
        payload = json.loads(preview.payload_json)
        if not isinstance(payload, list):
            return preview, []
        return preview, payload
    except Exception:
        return preview, []


def _upsert_boletins_por_turma(turma_id: int, parsed_students: list[dict]) -> dict:
    deduplicated: dict[str, dict] = {}
    for item in parsed_students:
        matricula = str(item.get("matricula", "")).strip()
        if matricula:
            deduplicated[matricula] = item

    created_students = 0
    updated_students = 0
    created_boletins = 0
    updated_boletins = 0

    for item in deduplicated.values():
        matricula = str(item.get("matricula", "")).strip()
        nome = str(item.get("nome", "")).strip() or "Aluno sem nome"

        aluno = Aluno.query.get(matricula)
        if aluno is None:
            aluno = Aluno(matricula=matricula, nome=nome)
            db.session.add(aluno)
            created_students += 1
        else:
            if aluno.nome != nome:
                aluno.nome = nome
            updated_students += 1

        boletim = BoletimBimestral.query.filter_by(
            aluno_matricula=matricula,
            turma_id=turma_id,
        ).first()

        if boletim is None:
            boletim = BoletimBimestral(
                aluno_matricula=matricula,
                turma_id=turma_id,
            )
            db.session.add(boletim)
            created_boletins += 1
        else:
            updated_boletins += 1

        db.session.flush()
        BoletimDisciplina.query.filter_by(boletim_id=boletim.id).delete()
        for d in item.get("disciplinas") or []:
            f1 = int(d.get("falta_b1", 0) or 0)
            f2 = int(d.get("falta_b2", 0) or 0)
            f3 = int(d.get("falta_b3", 0) or 0)
            f4 = int(d.get("falta_b4", 0) or 0)
            disc = BoletimDisciplina(
                boletim_id=boletim.id,
                nome_disciplina=str(d.get("nome_disciplina", "") or "Disciplina")[:200],
                frequencia_percent=d.get("frequencia_percent"),
                total_faltas=f1 + f2 + f3 + f4,
                nota_b1=float(d.get("nota_b1", 0) or 0),
                falta_b1=f1,
                nota_b2=float(d.get("nota_b2", 0) or 0),
                falta_b2=f2,
                nota_b3=float(d.get("nota_b3", 0) or 0),
                falta_b3=f3,
                nota_b4=float(d.get("nota_b4", 0) or 0),
                falta_b4=f4,
            )
            db.session.add(disc)

    return {
        "lidos": len(deduplicated),
        "alunos_novos": created_students,
        "alunos_atualizados": updated_students,
        "boletins_novos": created_boletins,
        "boletins_atualizados": updated_boletins,
    }


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            register_action("LOGIN", "Usuario autenticado com sucesso.", user=user)
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("dashboard"))

        flash("Usuario ou senha invalidos.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    register_action("LOGOUT", "Usuario saiu do sistema.")
    logout_user()
    flash("Sessao encerrada.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    ano = request.args.get("ano", type=int) or session.get("ano_dashboard")
    if ano is None:
        ano_row = db.session.query(Turma.ano_letivo).order_by(Turma.ano_letivo.desc()).first()
        ano = ano_row[0] if ano_row else datetime.now().year
    if ano is not None:
        session["ano_dashboard"] = ano

    total_users = User.query.count()
    total_logs = ActionLog.query.count()
    total_turma_nomes = TurmaNome.query.count()
    total_turmas = Turma.query.filter_by(ano_letivo=ano).count()
    total_boletins = (
        BoletimBimestral.query.join(Turma).filter(Turma.ano_letivo == ano).count()
    )
    total_alunos = (
        db.session.query(Aluno.matricula)
        .join(BoletimBimestral)
        .join(Turma)
        .filter(Turma.ano_letivo == ano)
        .distinct()
        .count()
    )

    turmas_ano = Turma.query.filter_by(ano_letivo=ano).join(TurmaNome).order_by(TurmaNome.nome.asc()).all()
    resumo_turmas = []
    for turma in turmas_ano:
        abaixo_b1 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id, BoletimDisciplina.nota_b1 < 70
        ).distinct().count()
        abaixo_b2 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id, BoletimDisciplina.nota_b2 < 70
        ).distinct().count()
        abaixo_b3 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id, BoletimDisciplina.nota_b3 < 70
        ).distinct().count()
        abaixo_b4 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id, BoletimDisciplina.nota_b4 < 70
        ).distinct().count()
        abaixo_40_b1 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id, BoletimDisciplina.nota_b1 < 40
        ).distinct().count()
        entre_40_70_b1 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id,
            BoletimDisciplina.nota_b1 >= 40, BoletimDisciplina.nota_b1 < 70
        ).distinct().count()
        abaixo_40_b2 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id, BoletimDisciplina.nota_b2 < 40
        ).distinct().count()
        entre_40_70_b2 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id,
            BoletimDisciplina.nota_b2 >= 40, BoletimDisciplina.nota_b2 < 70
        ).distinct().count()
        abaixo_40_b3 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id, BoletimDisciplina.nota_b3 < 40
        ).distinct().count()
        entre_40_70_b3 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id,
            BoletimDisciplina.nota_b3 >= 40, BoletimDisciplina.nota_b3 < 70
        ).distinct().count()
        abaixo_40_b4 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id, BoletimDisciplina.nota_b4 < 40
        ).distinct().count()
        entre_40_70_b4 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id,
            BoletimDisciplina.nota_b4 >= 40, BoletimDisciplina.nota_b4 < 70
        ).distinct().count()
        alunos_faltas_maior_15 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id,
            BoletimDisciplina.frequencia_percent.isnot(None),
            BoletimDisciplina.frequencia_percent < 85,
        ).distinct().count()
        alunos_faltas_maior_20 = db.session.query(BoletimBimestral.id).join(BoletimDisciplina).filter(
            BoletimBimestral.turma_id == turma.id,
            BoletimDisciplina.frequencia_percent.isnot(None),
            BoletimDisciplina.frequencia_percent < 80,
        ).distinct().count()
        resumo_turmas.append({
            "turma": turma,
            "abaixo_b1": abaixo_b1,
            "abaixo_b2": abaixo_b2,
            "abaixo_b3": abaixo_b3,
            "abaixo_b4": abaixo_b4,
            "abaixo_40_b1": abaixo_40_b1,
            "entre_40_70_b1": entre_40_70_b1,
            "abaixo_40_b2": abaixo_40_b2,
            "entre_40_70_b2": entre_40_70_b2,
            "abaixo_40_b3": abaixo_40_b3,
            "entre_40_70_b3": entre_40_70_b3,
            "abaixo_40_b4": abaixo_40_b4,
            "entre_40_70_b4": entre_40_70_b4,
            "alunos_faltas_maior_15": alunos_faltas_maior_15,
            "alunos_faltas_maior_20": alunos_faltas_maior_20,
        })

    recent_logs = ActionLog.query.order_by(ActionLog.timestamp.desc()).limit(5).all()
    return render_template(
        "dashboard.html",
        ano_selecionado=ano,
        total_users=total_users,
        total_logs=total_logs,
        total_turma_nomes=total_turma_nomes,
        total_turmas=total_turmas,
        total_alunos=total_alunos,
        total_boletins=total_boletins,
        recent_logs=recent_logs,
        resumo_turmas=resumo_turmas,
    )


@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "user").strip().lower()

        if not username or not full_name or not password:
            flash("Preencha usuario, nome e senha.", "warning")
            return redirect(url_for("users"))

        if role not in {"admin", "user"}:
            flash("Perfil invalido.", "danger")
            return redirect(url_for("users"))

        if User.query.filter_by(username=username).first():
            flash("Este nome de usuario ja existe.", "danger")
            return redirect(url_for("users"))

        new_user = User(username=username, full_name=full_name, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()

        register_action(
            "CREATE_USER",
            f"Usuario '{username}' criado com perfil '{role}'.",
            auto_commit=False,
        )
        db.session.commit()
        flash("Usuario cadastrado com sucesso.", "success")
        return redirect(url_for("users"))

    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("users.html", users=all_users)


@app.route("/users/<int:user_id>/alterar-senha", methods=["POST"])
@admin_required
def user_alterar_senha(user_id: int):
    user = User.query.get(user_id)
    if user is None:
        flash("Usuario nao encontrado.", "danger")
        return redirect(url_for("users"))
    nova_senha = request.form.get("nova_senha", "")
    confirmar = request.form.get("confirmar_senha", "")
    if not nova_senha or len(nova_senha) < 4:
        flash("Informe uma nova senha com no minimo 4 caracteres.", "warning")
        return redirect(url_for("users"))
    if nova_senha != confirmar:
        flash("A senha e a confirmacao nao conferem.", "danger")
        return redirect(url_for("users"))
    user.set_password(nova_senha)
    register_action(
        "CHANGE_PASSWORD",
        f"Senha do usuario '{user.username}' alterada por admin.",
        auto_commit=False,
    )
    db.session.commit()
    flash("Senha alterada com sucesso.", "success")
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/excluir", methods=["POST"])
@admin_required
def user_excluir(user_id: int):
    user = User.query.get(user_id)
    if user is None:
        flash("Usuario nao encontrado.", "danger")
        return redirect(url_for("users"))
    if user.id == current_user.id:
        flash("Voce nao pode excluir a si mesmo.", "danger")
        return redirect(url_for("users"))
    admins_count = User.query.filter_by(role="admin").count()
    if user.role == "admin" and admins_count <= 1:
        flash("Nao e possivel excluir o unico usuario admin.", "danger")
        return redirect(url_for("users"))
    username = user.username
    ActionLog.query.filter_by(user_id=user_id).update({ActionLog.user_id: None})
    db.session.delete(user)
    register_action(
        "DELETE_USER",
        f"Usuario '{username}' excluido.",
        auto_commit=False,
    )
    db.session.commit()
    flash("Usuario excluido com sucesso.", "success")
    return redirect(url_for("users"))


@app.route("/turma-nomes", methods=["GET", "POST"])
@admin_required
def turma_nomes():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        periodo = request.form.get("periodo", "").strip()

        if not nome or not periodo:
            flash("Preencha nome e serie da turma.", "warning")
            return redirect(url_for("turma_nomes"))

        if periodo not in PERIODO_OPTIONS:
            flash("Serie invalida. Use 1º, 2º ou 3º ano.", "danger")
            return redirect(url_for("turma_nomes"))

        exists = TurmaNome.query.filter_by(nome=nome, periodo=periodo).first()
        if exists:
            flash("Ja existe um nome de turma com essa serie.", "danger")
            return redirect(url_for("turma_nomes"))

        item = TurmaNome(nome=nome, periodo=periodo)
        db.session.add(item)
        db.session.flush()

        register_action(
            "CREATE_TURMA_NOME",
            f"Nome de turma '{nome}' ({periodo}) cadastrado.",
            auto_commit=False,
        )
        db.session.commit()
        flash("Nome de turma cadastrado com sucesso.", "success")
        return redirect(url_for("turma_nomes"))

    all_turma_nomes = TurmaNome.query.order_by(TurmaNome.created_at.desc()).all()
    return render_template(
        "turma_nomes.html",
        turma_nomes=all_turma_nomes,
        periodo_options=PERIODO_OPTIONS,
    )


@app.route("/turma-nomes/<int:turma_nome_id>/alterar", methods=["POST"])
@admin_required
def alterar_turma_nome(turma_nome_id: int):
    item = TurmaNome.query.get(turma_nome_id)
    if item is None:
        flash("Nome de turma nao encontrado.", "danger")
        return redirect(url_for("turma_nomes"))

    nome = request.form.get("nome", "").strip()
    periodo = request.form.get("periodo", "").strip()

    if not nome or not periodo:
        flash("Preencha nome e serie.", "warning")
        return redirect(url_for("turma_nomes"))

    if periodo not in PERIODO_OPTIONS:
        flash("Serie invalida. Use 1º, 2º ou 3º ano.", "danger")
        return redirect(url_for("turma_nomes"))

    exists = TurmaNome.query.filter(
        TurmaNome.nome == nome,
        TurmaNome.periodo == periodo,
        TurmaNome.id != turma_nome_id,
    ).first()
    if exists:
        flash("Ja existe outro nome de turma com esse nome e serie.", "danger")
        return redirect(url_for("turma_nomes"))

    item.nome = nome
    item.periodo = periodo
    db.session.flush()

    register_action(
        "UPDATE_TURMA_NOME",
        f"Nome de turma alterado para '{nome}' ({periodo}).",
        auto_commit=False,
    )
    db.session.commit()
    flash("Nome de turma alterado com sucesso.", "success")
    return redirect(url_for("turma_nomes"))


@app.route("/turma-nomes/<int:turma_nome_id>/excluir", methods=["POST"])
@admin_required
def excluir_turma_nome(turma_nome_id: int):
    item = TurmaNome.query.get(turma_nome_id)
    if item is None:
        flash("Nome de turma nao encontrado.", "danger")
        return redirect(url_for("turma_nomes"))

    turmas_vinculadas = Turma.query.filter_by(turma_nome_id=turma_nome_id).count()
    if turmas_vinculadas > 0:
        flash(
            f"Nao e possivel excluir: existem {turmas_vinculadas} turma(s) vinculada(s). Exclua as turmas antes.",
            "danger",
        )
        return redirect(url_for("turma_nomes"))

    label = f"{item.nome} ({item.periodo})"
    db.session.delete(item)
    db.session.flush()

    register_action(
        "DELETE_TURMA_NOME",
        f"Nome de turma '{label}' excluido.",
        auto_commit=False,
    )
    db.session.commit()
    flash("Nome de turma excluido com sucesso.", "success")
    return redirect(url_for("turma_nomes"))


@app.route("/turmas", methods=["GET", "POST"])
@admin_required
def turmas():
    all_turma_nomes = TurmaNome.query.order_by(TurmaNome.nome.asc()).all()

    if request.method == "POST":
        turma_nome_id_raw = request.form.get("turma_nome_id", "").strip()
        ano_letivo_raw = request.form.get("ano_letivo", "").strip()

        if not turma_nome_id_raw or not ano_letivo_raw:
            flash("Selecione o nome da turma e informe o ano letivo.", "warning")
            return redirect(url_for("turmas"))

        try:
            turma_nome_id = int(turma_nome_id_raw)
            ano_letivo = int(ano_letivo_raw)
        except ValueError:
            flash("Dados invalidos para cadastro da turma.", "danger")
            return redirect(url_for("turmas"))

        if ano_letivo < 2000 or ano_letivo > 2100:
            flash("Ano letivo deve estar entre 2000 e 2100.", "warning")
            return redirect(url_for("turmas"))

        turma_nome = TurmaNome.query.get(turma_nome_id)
        if turma_nome is None:
            flash("Nome de turma selecionado nao existe.", "danger")
            return redirect(url_for("turmas"))

        exists = Turma.query.filter_by(turma_nome_id=turma_nome_id, ano_letivo=ano_letivo).first()
        if exists:
            flash("Esta turma ja foi cadastrada para o ano letivo informado.", "danger")
            return redirect(url_for("turmas"))

        turma = Turma(turma_nome_id=turma_nome_id, ano_letivo=ano_letivo)
        db.session.add(turma)
        db.session.flush()

        register_action(
            "CREATE_TURMA",
            f"Turma '{turma_nome.nome}' ({turma_nome.periodo}) cadastrada para {ano_letivo}.",
            auto_commit=False,
        )
        db.session.commit()
        flash("Turma cadastrada com sucesso.", "success")
        return redirect(url_for("turmas", ano=ano_letivo))

    ano_filtro = request.args.get("ano", type=int)
    query = Turma.query.join(TurmaNome)
    if ano_filtro is not None:
        query = query.filter(Turma.ano_letivo == ano_filtro)
    all_turmas = query.order_by(Turma.ano_letivo.desc(), TurmaNome.nome.asc()).all()

    anos_turmas = [r[0] for r in db.session.query(Turma.ano_letivo).distinct().order_by(Turma.ano_letivo.desc()).all() if r[0] is not None]
    if not anos_turmas:
        anos_turmas = [datetime.now().year]

    return render_template(
        "turmas.html",
        turmas=all_turmas,
        turma_nomes=all_turma_nomes,
        ano_atual=datetime.now().year,
        ano_filtro=ano_filtro,
        anos_turmas=anos_turmas,
    )


@app.route("/turmas/<int:turma_id>/alterar", methods=["POST"])
@admin_required
def alterar_turma(turma_id: int):
    turma = Turma.query.get(turma_id)
    if turma is None:
        flash("Turma nao encontrada.", "danger")
        return redirect(url_for("turmas"))

    turma_nome_id_raw = request.form.get("turma_nome_id", "").strip()
    ano_letivo_raw = request.form.get("ano_letivo", "").strip()
    if not turma_nome_id_raw or not ano_letivo_raw:
        flash("Informe o nome da turma e o ano letivo.", "warning")
        return redirect(url_for("turmas", ano=turma.ano_letivo))

    try:
        turma_nome_id = int(turma_nome_id_raw)
        ano_letivo = int(ano_letivo_raw)
    except ValueError:
        flash("Dados invalidos.", "danger")
        return redirect(url_for("turmas", ano=turma.ano_letivo))

    if ano_letivo < 2000 or ano_letivo > 2100:
        flash("Ano letivo deve estar entre 2000 e 2100.", "warning")
        return redirect(url_for("turmas", ano=turma.ano_letivo))

    turma_nome = TurmaNome.query.get(turma_nome_id)
    if turma_nome is None:
        flash("Nome de turma selecionado nao existe.", "danger")
        return redirect(url_for("turmas", ano=turma.ano_letivo))

    exists = Turma.query.filter(
        Turma.turma_nome_id == turma_nome_id,
        Turma.ano_letivo == ano_letivo,
        Turma.id != turma_id,
    ).first()
    if exists:
        flash("Ja existe outra turma com esse nome e ano letivo.", "danger")
        return redirect(url_for("turmas", ano=turma.ano_letivo))

    antigo_label = f"{turma.turma_nome.nome} - {turma.turma_nome.periodo} ({turma.ano_letivo})"
    turma.turma_nome_id = turma_nome_id
    turma.ano_letivo = ano_letivo
    register_action(
        "UPDATE_TURMA",
        f"Turma alterada: de '{antigo_label}' para '{turma_nome.nome} - {turma_nome.periodo} ({ano_letivo})'.",
        auto_commit=False,
    )
    db.session.commit()
    flash("Turma alterada com sucesso.", "success")
    return redirect(url_for("turmas", ano=ano_letivo))


@app.route("/turmas/<int:turma_id>/excluir", methods=["POST"])
@admin_required
def excluir_turma(turma_id: int):
    turma = Turma.query.get(turma_id)
    if turma is None:
        flash("Turma nao encontrada.", "danger")
        return redirect(url_for("turmas"))

    turma_label = f"{turma.turma_nome.nome} - {turma.turma_nome.periodo} ({turma.ano_letivo})"
    ano_letivo = turma.ano_letivo

    BoletimBimestral.query.filter_by(turma_id=turma_id).delete()
    ImportacaoBoletimPreview.query.filter_by(turma_id=turma_id).delete()
    db.session.delete(turma)
    db.session.flush()

    register_action(
        "DELETE_TURMA",
        f"Turma '{turma_label}' excluida (boletins vinculados tambem foram removidos).",
        auto_commit=False,
    )
    db.session.commit()

    flash("Turma excluida com sucesso.", "success")
    return redirect(url_for("turmas", ano=ano_letivo))


@app.route("/turmas/<int:turma_id>/detalhes")
@login_required
def turma_detalhes(turma_id: int):
    turma = Turma.query.get(turma_id)
    if turma is None:
        flash("Turma nao encontrada.", "danger")
        return redirect(url_for("dashboard"))

    boletins = (
        BoletimBimestral.query.filter_by(turma_id=turma_id)
        .join(Aluno)
        .order_by(Aluno.nome.asc())
        .all()
    )
    has_disciplinas = any(getattr(b, "disciplinas", None) and len(b.disciplinas) > 0 for b in boletins)
    return render_template(
        "turma_detalhes.html",
        turma=turma,
        boletins=boletins,
        has_disciplinas=has_disciplinas,
    )


@app.route("/turmas/<int:turma_id>/grafico")
@login_required
def turma_grafico(turma_id: int):
    turma = Turma.query.get(turma_id)
    if turma is None:
        flash("Turma nao encontrada.", "danger")
        return redirect(url_for("dashboard"))

    boletins = (
        BoletimBimestral.query.filter_by(turma_id=turma_id)
        .join(Aluno)
        .order_by(Aluno.nome.asc())
        .all()
    )
    disciplinas_nomes = set()
    for b in boletins:
        for d in b.disciplinas:
            disciplinas_nomes.add(d.nome_disciplina)
    disciplinas_nomes = sorted(disciplinas_nomes)

    chart_data_por_disciplina = []
    for nome_disc in disciplinas_nomes:
        alunos_data = []
        for b in boletins:
            disc = next((d for d in b.disciplinas if d.nome_disciplina == nome_disc), None)
            if disc is not None:
                alunos_data.append({
                    "aluno": b.aluno.nome,
                    "b1": disc.nota_b1,
                    "b2": disc.nota_b2,
                    "b3": disc.nota_b3,
                    "b4": disc.nota_b4,
                })
        if alunos_data:
            chart_data_por_disciplina.append({
                "disciplina": nome_disc,
                "alunos": alunos_data,
            })

    return render_template(
        "turma_grafico.html",
        turma=turma,
        chart_data_por_disciplina=chart_data_por_disciplina,
    )


@app.route("/turmas/<int:turma_id>/bimestre/<int:num>/avaliacao")
@login_required
def avaliacao_bimestre(turma_id: int, num: int):
    if num < 1 or num > 4:
        flash("Bimestre invalido.", "danger")
        return redirect(url_for("dashboard"))

    turma = Turma.query.get(turma_id)
    if turma is None:
        flash("Turma nao encontrada.", "danger")
        return redirect(url_for("dashboard"))

    boletins = (
        BoletimBimestral.query.filter_by(turma_id=turma_id)
        .join(Aluno)
        .order_by(Aluno.nome.asc())
        .all()
    )

    notas_campo = ("nota_b1", "nota_b2", "nota_b3", "nota_b4")[num - 1]
    alunos_abaixo_70 = []
    for b in boletins:
        count_70 = sum(1 for d in b.disciplinas if getattr(d, notas_campo) < 70)
        count_40 = sum(1 for d in b.disciplinas if getattr(d, notas_campo) < 40)
        if count_70 > 0:
            alunos_abaixo_70.append((b, count_70, count_40))
    alunos_abaixo_70.sort(key=lambda x: x[1], reverse=True)

    chart_por_aluno = []
    labels_bimestres = ["B1", "B2", "B3", "B4"][:num]
    for b in boletins:
        if not b.disciplinas:
            continue
        count_70 = sum(1 for d in b.disciplinas if getattr(d, notas_campo) < 70)
        count_40 = sum(1 for d in b.disciplinas if getattr(d, notas_campo) < 40)
        disciplinas_chart = []
        for d in b.disciplinas:
            nota_bim = getattr(d, notas_campo)
            disciplinas_chart.append({
                "nome": d.nome_disciplina,
                "notas": [d.nota_b1, d.nota_b2, d.nota_b3, d.nota_b4][:num],
                "abaixo_70": nota_bim < 70,
                "abaixo_40": nota_bim < 40,
            })
        chart_por_aluno.append({
            "aluno_nome": b.aluno.nome,
            "matricula": b.aluno_matricula,
            "disciplinas": disciplinas_chart,
            "tem_abaixo_70": count_70 > 0,
            "tem_abaixo_40": count_40 > 0,
        })

    return render_template(
        "avaliacao_bimestre.html",
        turma=turma,
        num_bimestre=num,
        alunos_abaixo_70=alunos_abaixo_70,
        chart_por_aluno=chart_por_aluno,
        labels_bimestres=labels_bimestres,
    )


@app.route("/turmas/<int:turma_id>/aluno/<matricula>/grafico")
@login_required
def aluno_grafico(turma_id: int, matricula: str):
    turma = Turma.query.get(turma_id)
    if turma is None:
        flash("Turma nao encontrada.", "danger")
        return redirect(url_for("dashboard"))

    boletim = (
        BoletimBimestral.query.filter_by(turma_id=turma_id, aluno_matricula=matricula)
        .join(Aluno)
        .first()
    )
    if boletim is None:
        flash("Aluno nao encontrado nesta turma.", "danger")
        return redirect(url_for("turma_detalhes", turma_id=turma_id))

    disciplinas_data = []
    for d in boletim.disciplinas:
        disciplinas_data.append({
            "nome": d.nome_disciplina,
            "b1": d.nota_b1,
            "b2": d.nota_b2,
            "b3": d.nota_b3,
            "b4": d.nota_b4,
        })

    return render_template(
        "aluno_grafico.html",
        turma=turma,
        aluno_nome=boletim.aluno.nome,
        matricula=matricula,
        disciplinas_data=disciplinas_data,
    )


@app.route("/importar-boletim", methods=["GET", "POST"])
@admin_required
def importar_boletim():
    all_turmas = Turma.query.join(TurmaNome).order_by(Turma.ano_letivo.desc(), TurmaNome.nome.asc()).all()
    anos_disponiveis = sorted(
        {t.ano_letivo for t in all_turmas if t.ano_letivo is not None},
        reverse=True,
    )
    ano_filtro = request.args.get("ano", type=int)
    if ano_filtro is None and anos_disponiveis:
        ano_filtro = anos_disponiveis[0]
    if ano_filtro is not None:
        turmas = [t for t in all_turmas if t.ano_letivo == ano_filtro]
    else:
        turmas = all_turmas

    def _url_importar(turma_id=None, preview_id=None):
        kw = {}
        if turma_id is not None:
            kw["turma_id"] = turma_id
        if preview_id is not None:
            kw["preview_id"] = preview_id
        if ano_filtro is not None:
            kw["ano"] = ano_filtro
        return url_for("importar_boletim", **kw)

    if not all_turmas:
        flash("Cadastre ao menos uma turma antes de importar boletins.", "warning")
        return render_template(
            "importar_boletim.html",
            turmas=[],
            anos_disponiveis=[],
            ano_filtro=None,
            selected_turma_id=None,
            registros=[],
            preview_rows=[],
            preview_id=None,
            preview_arquivo_nome=None,
        )

    selected_turma_id = request.args.get("turma_id", type=int)
    if selected_turma_id is None and turmas:
        selected_turma_id = turmas[0].id
    elif selected_turma_id is not None and turmas and not any(t.id == selected_turma_id for t in turmas):
        selected_turma_id = turmas[0].id if turmas else None

    if request.method == "POST":
        acao = request.form.get("acao", "carregar").strip()

        if acao == "carregar":
            turma_id_raw = request.form.get("turma_id", "").strip()
            arquivo_pdf = request.files.get("arquivo_pdf")

            if not turma_id_raw:
                flash("Selecione uma turma para conferencia.", "warning")
                return redirect(_url_importar(turma_id=selected_turma_id))

            try:
                selected_turma_id = int(turma_id_raw)
            except ValueError:
                flash("Turma invalida.", "danger")
                return redirect(_url_importar())

            turma = Turma.query.get(selected_turma_id)
            if turma is None:
                flash("Turma selecionada nao existe.", "danger")
                return redirect(_url_importar())

            if arquivo_pdf is None or not arquivo_pdf.filename:
                flash("Selecione um arquivo PDF.", "warning")
                return redirect(_url_importar(turma_id=selected_turma_id))

            if not arquivo_pdf.filename.lower().endswith(".pdf"):
                flash("Arquivo invalido. Envie um PDF de boletim.", "danger")
                return redirect(_url_importar(turma_id=selected_turma_id))

            try:
                parsed_students = parse_boletim_pdf(arquivo_pdf)
            except PdfReadError:
                flash("Nao foi possivel ler o PDF informado. Verifique se o arquivo nao esta corrompido.", "danger")
                return redirect(_url_importar(turma_id=selected_turma_id))
            except Exception:
                flash("Nao foi possivel ler o PDF informado.", "danger")
                return redirect(_url_importar(turma_id=selected_turma_id))

            if not parsed_students:
                flash("Nenhum aluno encontrado no PDF.", "warning")
                return redirect(_url_importar(turma_id=selected_turma_id))

            deduplicated = list({item["matricula"]: item for item in parsed_students if item.get("matricula")}.values())
            if not deduplicated:
                flash("Nenhum aluno valido encontrado para conferencia.", "warning")
                return redirect(_url_importar(turma_id=selected_turma_id))

            ImportacaoBoletimPreview.query.filter_by(user_id=current_user.id).delete()

            preview = ImportacaoBoletimPreview(
                user_id=current_user.id,
                turma_id=selected_turma_id,
                arquivo_nome=arquivo_pdf.filename,
                payload_json=json.dumps(deduplicated, ensure_ascii=False),
            )
            db.session.add(preview)
            db.session.commit()

            flash(
                f"Conferencia carregada com {len(deduplicated)} alunos. Verifique a lista e clique em importar.",
                "info",
            )
            return redirect(_url_importar(turma_id=selected_turma_id, preview_id=preview.id))

        if acao == "importar_conferencia":
            preview_id_raw = request.form.get("preview_id", "").strip()

            try:
                preview_id = int(preview_id_raw)
            except ValueError:
                flash("Conferencia invalida. Recarregue o arquivo.", "danger")
                return redirect(_url_importar(turma_id=selected_turma_id))

            preview = ImportacaoBoletimPreview.query.filter_by(id=preview_id, user_id=current_user.id).first()
            if preview is None:
                flash("Conferencia nao encontrada. Recarregue o arquivo.", "warning")
                return redirect(_url_importar(turma_id=selected_turma_id))

            turma = Turma.query.get(preview.turma_id)
            if turma is None:
                flash("Turma da conferencia nao encontrada.", "danger")
                db.session.delete(preview)
                db.session.commit()
                return redirect(_url_importar())

            try:
                parsed_students = json.loads(preview.payload_json)
            except Exception:
                parsed_students = []

            if not parsed_students:
                flash("Conferencia vazia. Carregue o arquivo novamente.", "warning")
                db.session.delete(preview)
                db.session.commit()
                return redirect(_url_importar(turma_id=turma.id))

            resultado = _upsert_boletins_por_turma(turma.id, parsed_students)

            turma_label = f"{turma.turma_nome.nome} - {turma.turma_nome.periodo} ({turma.ano_letivo})"
            register_action(
                "IMPORT_BOLETIM",
                (
                    f"Importacao confirmada da conferencia para turma '{turma_label}': "
                    f"{resultado['lidos']} alunos lidos, "
                    f"{resultado['alunos_novos']} alunos novos, "
                    f"{resultado['alunos_atualizados']} alunos atualizados, "
                    f"{resultado['boletins_novos']} boletins novos, "
                    f"{resultado['boletins_atualizados']} boletins atualizados."
                ),
                auto_commit=False,
            )
            db.session.delete(preview)
            db.session.commit()

            flash(
                (
                    f"Importacao concluida: {resultado['lidos']} alunos lidos, "
                    f"{resultado['alunos_novos']} alunos novos, {resultado['alunos_atualizados']} alunos atualizados, "
                    f"{resultado['boletins_novos']} boletins novos e {resultado['boletins_atualizados']} boletins atualizados."
                ),
                "success",
            )
            return redirect(_url_importar(turma_id=turma.id))

        flash("Acao invalida.", "danger")
        return redirect(_url_importar(turma_id=selected_turma_id))

    turma_id_na_url = request.args.get("turma_id", type=int)
    preview_id = request.args.get("preview_id", type=int)
    if preview_id is None and turma_id_na_url is None:
        latest_preview = (
            ImportacaoBoletimPreview.query.filter_by(user_id=current_user.id)
            .order_by(ImportacaoBoletimPreview.id.desc())
            .first()
        )
        if latest_preview is not None:
            preview_id = latest_preview.id

    preview, preview_rows = _load_preview(preview_id)

    preview_arquivo_nome = None
    if preview is not None:
        if turma_id_na_url is None:
            selected_turma_id = preview.turma_id
        elif preview.turma_id != selected_turma_id:
            preview = None
            preview_rows = []
            preview_id = None
        else:
            preview_arquivo_nome = preview.arquivo_nome
    if preview is not None and preview_arquivo_nome is None:
        preview_arquivo_nome = preview.arquivo_nome

    registros = (
        BoletimBimestral.query.join(Aluno)
        .filter(BoletimBimestral.turma_id == selected_turma_id)
        .order_by(Aluno.nome.asc())
        .all()
    )

    return render_template(
        "importar_boletim.html",
        turmas=turmas,
        anos_disponiveis=anos_disponiveis,
        ano_filtro=ano_filtro,
        selected_turma_id=selected_turma_id,
        registros=registros,
        preview_rows=preview_rows,
        preview_id=preview.id if preview else None,
        preview_arquivo_nome=preview_arquivo_nome,
    )


@app.route("/logs", methods=["GET"])
@admin_required
def logs():
    all_logs = ActionLog.query.order_by(ActionLog.timestamp.desc()).limit(300).all()
    return render_template("logs.html", logs=all_logs)


@app.route("/logs/limpar", methods=["POST"])
@admin_required
def logs_limpar():
    try:
        dias = int(request.form.get("dias", 30))
    except (ValueError, TypeError):
        dias = 30
    if dias < 1:
        dias = 1
    if dias > 3650:
        dias = 3650
    limite = datetime.utcnow() - timedelta(days=dias)
    deletados = ActionLog.query.filter(ActionLog.timestamp < limite).delete()
    db.session.commit()
    flash(f"Foram removidos {deletados} log(s) com mais de {dias} dia(s).", "success")
    return redirect(url_for("logs"))


@app.errorhandler(403)
def forbidden(_error):
    return render_template("403.html"), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


with app.app_context():
    db.create_all()
    bootstrap_admin_user()


if __name__ == "__main__":
    app.run(debug=True)




