"""GreenID - Gestão e priorização da recuperação de áreas verdes."""
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash

import database as db
import biometria

BASE_DIR = Path(__file__).parent
app = Flask(__name__)
app.secret_key = 'chave-secreta-aps-greenid-trocar-em-producao'

ENROLL_SENHA = 'novocadastro'
POR_PAGINA = 50
NIVEL_LABEL = {1: 'Nível 1 — Acesso Geral', 2: 'Nível 2 — Direção', 3: 'Nível 3 — Administrador'}


# --------------------------------------------------------------- filtros Jinja
def format_int(v):
    try:
        return f'{int(v):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return '0'


def format_m2(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return '—'
    if x == 0:
        return '0 m²'
    if x >= 1_000_000:
        return f'{x / 1_000_000:.2f} mi m²'.replace('.', ',')
    return f'{x:,.0f} m²'.replace(',', 'X').replace('.', ',').replace('X', '.')


app.jinja_env.filters['format_int'] = format_int
app.jinja_env.filters['format_m2'] = format_m2


# ------------------------------------------------------------------- helpers
def garantir_base_pronta():
    db.init_db()
    if not (BASE_DIR / 'instance' / 'greenid.db').exists():
        return
    try:
        c = db.get_conn()
        c.execute('SELECT 1 FROM areas_verdes LIMIT 1')
        c.close()
    except Exception:
        print("Tabela areas_verdes ausente. Execute: python etl.py")


def parse_pagina():
    """Lê o parâmetro ?pagina= da querystring, sempre >= 1."""
    try:
        return max(int(request.args.get('pagina', 1)), 1)
    except ValueError:
        return 1


def paginar(pagina, total, por_pagina=POR_PAGINA):
    """A partir do total de registros, devolve (pagina_corrigida, total_paginas)."""
    total_paginas = max((total + por_pagina - 1) // por_pagina, 1)
    return min(pagina, total_paginas), total_paginas


def login_requerido(f):
    @wraps(f)
    def w(*a, **kw):
        if 'user_id' not in session:
            db.registrar_log(None, 'ACESSO_NEGADO', False,
                              f"Acesso a '{request.path}' sem autenticação.", request.remote_addr)
            flash('Você precisa entrar no sistema para continuar.', 'erro')
            return redirect(url_for('login'))
        return f(*a, **kw)
    return w


def nivel_requerido(n):
    def d(f):
        @wraps(f)
        def w(*a, **kw):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('nivel_acesso', 0) < n:
                db.registrar_log(session.get('username'), 'ACESSO_NEGADO', False,
                                  f"Nível insuficiente em '{request.path}'.", request.remote_addr)
                flash('Acesso negado.', 'erro')
                return redirect(url_for('consulta'))
            return f(*a, **kw)
        return w
    return d


# ------------------------------------------------------------- autenticação
@app.route('/')
def index():
    if 'user_id' not in session:
        return render_template('splash.html')
    return redirect(url_for('dashboard') if session.get('nivel_acesso', 0) >= 2 else url_for('consulta'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    username = request.form.get('username', '').strip()
    senha = request.form.get('senha', '')
    u = db.get_usuario_por_username(username)

    if not u or not check_password_hash(u['senha_hash'], senha):
        db.registrar_log(username, 'LOGIN', False, 'Usuário ou senha incorretos.', request.remote_addr)
        flash('Usuário ou senha incorretos.', 'erro')
        return redirect(url_for('login'))

    if u['nivel_acesso'] == 3:
        session['pendente_id'] = u['id']
        session['pendente_username'] = u['username']
        return redirect(url_for('verificar_face'))

    session.update(user_id=u['id'], nome=u['nome'], username=u['username'], nivel_acesso=u['nivel_acesso'])
    db.registrar_log(username, 'LOGIN', True, 'Login concluído com sucesso.', request.remote_addr)
    return redirect(url_for('dashboard') if u['nivel_acesso'] >= 2 else url_for('consulta'))


@app.route('/verificar-face', methods=['GET', 'POST'])
def verificar_face():
    uid = session.get('pendente_id')
    if not uid:
        return redirect(url_for('login'))
    u = db.get_usuario_por_id(uid)

    if request.method == 'GET':
        return render_template('verificar_face.html', usuario=u, tem_cadastro=biometria.fotos_cadastradas(uid) > 0)

    imagem = request.form.get('imagem')
    if not imagem:
        return jsonify(ok=False, mensagem='Não foi possível capturar a imagem.')

    try:
        ok, msg, conf = biometria.reconhecer_face(imagem, uid)
    except Exception as e:
        ok, msg, conf = False, f'Falha no reconhecimento facial: {e}', None

    if not ok:
        db.registrar_log(u['username'], 'BIOMETRIA_FALHA', False, f'{msg} (confiança={conf})', request.remote_addr)
        return jsonify(ok=False, mensagem=msg)

    session.pop('pendente_id', None)
    session.pop('pendente_username', None)
    session.update(user_id=u['id'], nome=u['nome'], username=u['username'], nivel_acesso=u['nivel_acesso'])
    db.registrar_log(u['username'], 'BIOMETRIA_OK', True, f'Face reconhecida (confiança={conf:.1f}).', request.remote_addr)
    return jsonify(ok=True, mensagem='Face reconhecida com sucesso.', redirect=url_for('dashboard'))


@app.route('/cadastrar-face', methods=['GET', 'POST'])
def cadastrar_face():
    uid = session.get('pendente_id') or session.get('admin_enroll_target')
    if not uid:
        return redirect(url_for('login'))
    u = db.get_usuario_por_id(uid)
    if not u:
        return redirect(url_for('login'))
    modo_admin = 'admin_enroll_target' in session

    if request.method == 'GET':
        return render_template('cadastrar_face.html', usuario=u, total=biometria.fotos_cadastradas(uid),
                                minimo=biometria.FOTOS_MINIMAS_CADASTRO, modo_admin=modo_admin)

    imagem = request.form.get('imagem')
    if not imagem:
        return jsonify(ok=False, mensagem='Imagem não recebida.'), 400

    try:
        total = biometria.enroll_face(uid, imagem)
    except biometria.SemRostoDetectado:
        return jsonify(ok=False, mensagem='Nenhum rosto detectado. Tente novamente.')
    except Exception as e:
        return jsonify(ok=False, mensagem=f'Erro ao processar imagem: {e}')

    concluido = total >= biometria.FOTOS_MINIMAS_CADASTRO
    if concluido:
        biometria.treinar_modelo()
        db.marcar_face_cadastrada(uid)
        if modo_admin:
            session.pop('admin_enroll_target', None)
        db.registrar_log(u['username'], 'BIOMETRIA_CADASTRO', True,
                          f'Cadastro facial concluído com {total} fotos.', request.remote_addr)

    proxima_url = url_for('admin_usuarios') if (concluido and modo_admin) else url_for('verificar_face')
    return jsonify(ok=True, total=total, minimo=biometria.FOTOS_MINIMAS_CADASTRO,
                    concluido=concluido, proxima_url=proxima_url)


@app.route('/cadastrar-face/cancelar')
def cancelar_cadastro_face():
    if 'admin_enroll_target' in session:
        session.pop('admin_enroll_target', None)
        return redirect(url_for('admin_usuarios'))
    return redirect(url_for('logout'))


@app.route('/logout')
def logout():
    if session.get('username'):
        db.registrar_log(session.get('username'), 'LOGOUT', True, 'Sessão encerrada.', request.remote_addr)
    session.clear()
    flash('Sessão encerrada.', 'sucesso')
    return redirect(url_for('login'))


# ------------------------------------------------------------------- painéis
@app.route('/dashboard')
@nivel_requerido(2)
def dashboard():
    ind = db.indicadores()
    grafico_prioridade = [{'label': r['prioridade'], 'valor': r['qtd']} for r in ind['por_prioridade']]
    grafico_uf = [{'label': r['uf'], 'valor': r['qtd']} for r in ind['por_uf'][:8]]
    grafico_tipo = [{'label': r['tipo'] or 'Não informado', 'valor': r['qtd']} for r in ind['por_tipo'][:8]]
    return render_template('dashboard.html', indicadores=ind, nivel_label=NIVEL_LABEL[session['nivel_acesso']],
                            grafico_prioridade=grafico_prioridade, grafico_uf=grafico_uf, grafico_tipo=grafico_tipo)


@app.route('/consulta')
@login_requerido
def consulta():
    filtros = {k: (request.args.get(k) or '') for k in
               ['q', 'municipio', 'uf', 'tipo', 'situacao', 'prioridade', 'projeto']}
    pagina = parse_pagina()
    resultados, total = db.consultar_areas(filtros, pagina, POR_PAGINA)
    pagina, total_paginas = paginar(pagina, total)
    filtros_ativos = {k: v for k, v in filtros.items() if v}
    return render_template('consulta.html', resultados=resultados, filtros=filtros, filtros_ativos=filtros_ativos,
                            municipios=db.listar_opcoes('municipio'), ufs=db.listar_opcoes('uf'),
                            tipos=db.listar_opcoes('tipologia_normalizada'), situacoes=db.listar_opcoes('situacao'),
                            nivel=session['nivel_acesso'], pagina=pagina, total_paginas=total_paginas,
                            total=total, por_pagina=POR_PAGINA)


@app.route('/area/<int:area_id>')
@login_requerido
def area_detalhe(area_id):
    area = db.obter_area(area_id)
    if not area:
        flash('Área não encontrada.', 'erro')
        return redirect(url_for('consulta'))
    return render_template('area_detalhe.html', area=area, nivel=session['nivel_acesso'])


# --------------------------------------------------------------- administração
@app.route('/admin/usuarios')
@nivel_requerido(3)
def admin_usuarios():
    return render_template('admin_usuarios.html', usuarios=db.listar_usuarios())


@app.route('/admin/usuarios/<int:user_id>/excluir-face', methods=['POST'])
@nivel_requerido(3)
def excluir_face_usuario(user_id):
    u = db.get_usuario_por_id(user_id)
    if not u:
        flash('Usuário não encontrado.', 'erro')
        return redirect(url_for('admin_usuarios'))
    tinha = biometria.excluir_face(user_id)
    db.desmarcar_face_cadastrada(user_id)
    flash(f"Rosto de {u['nome']} {'excluído' if tinha else 'não estava cadastrado'}.",
          'sucesso' if tinha else 'erro')
    return redirect(url_for('admin_usuarios'))


@app.route('/admin/usuarios/<int:user_id>/cadastrar-face', methods=['GET', 'POST'])
@nivel_requerido(3)
def iniciar_cadastro_face(user_id):
    u = db.get_usuario_por_id(user_id)
    if not u or u['nivel_acesso'] != 3:
        flash('Só é possível cadastrar rosto para Nível 3.', 'erro')
        return redirect(url_for('admin_usuarios'))

    if request.method == 'GET':
        return render_template('enroll_gate.html', usuario=u)

    if request.form.get('senha_cadastro', '') != ENROLL_SENHA:
        flash('Senha de cadastro biométrico incorreta.', 'erro')
        return redirect(url_for('iniciar_cadastro_face', user_id=user_id))

    session['admin_enroll_target'] = user_id
    return redirect(url_for('cadastrar_face'))


@app.route('/admin/logs')
@nivel_requerido(3)
def admin_logs():
    pagina = parse_pagina()
    logs, total = db.listar_logs(pagina, POR_PAGINA)
    pagina, total_paginas = paginar(pagina, total)
    return render_template('admin_logs.html', logs=logs, pagina=pagina, total_paginas=total_paginas, total=total)


if __name__ == '__main__':
    garantir_base_pronta()
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)