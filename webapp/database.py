"""Camada de acesso ao banco do GreenID.

Modelo relacional (normalizado, com chaves estrangeiras):

  usuarios ──< logs_acesso

  estados ──< municipios ──┐
  categorias ───────────────┤
  tipologias ────────────────┼──< areas_verdes ──< area_atributos >── atributos ──> grupos_atributos
  situacoes ─────────────────┤
  prioridades ───────────────┘

`areas_verdes` guarda os campos "de valor único" de cada área (nome, medidas,
score etc.), sempre referenciando as tabelas de apoio por id em vez de repetir
texto (município/UF, tipologia, situação, categoria, prioridade).

`area_atributos` substitui as ~120 colunas Sim/Não que existiam soltas na
tabela original (bancos, vigilante, ciclovia, compostagem...). Cada uma virou
uma linha no catálogo `atributos` (agrupada em `grupos_atributos`), e o valor
Sim/Não de cada área para cada atributo fica em `area_atributos`.

As funções abaixo devolvem as MESMAS chaves que o app.py e os templates já
esperavam antes (nome_area, municipio, uf, tipo, prioridade, etc.), então o
front-end não precisa mudar nada — só o jeito como o dado é guardado mudou.
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from werkzeug.security import generate_password_hash

DB_PATH = Path(__file__).parent / 'instance' / 'greenid.db'


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def init_db():
    """Cria (se ainda não existirem) todas as tabelas do banco."""
    con = get_conn()
    cur = con.cursor()

    # ---- controle de acesso -------------------------------------------------
    cur.execute('''CREATE TABLE IF NOT EXISTS usuarios (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL,
      username TEXT UNIQUE NOT NULL,
      senha_hash TEXT NOT NULL,
      nivel_acesso INTEGER NOT NULL CHECK(nivel_acesso IN (1,2,3)),
      face_cadastrada INTEGER NOT NULL DEFAULT 0,
      criado_em TEXT NOT NULL)''')

    cur.execute('''CREATE TABLE IF NOT EXISTS logs_acesso (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
      usuario TEXT,
      tipo_evento TEXT NOT NULL,
      sucesso INTEGER NOT NULL,
      detalhes TEXT,
      ip_origem TEXT,
      timestamp TEXT NOT NULL)''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_logs_usuario_id ON logs_acesso(usuario_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs_acesso(timestamp)')

    # ---- tabelas de apoio (lookups) usadas como FK em areas_verdes ---------
    cur.execute('''CREATE TABLE IF NOT EXISTS estados (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL UNIQUE)''')

    cur.execute('''CREATE TABLE IF NOT EXISTS municipios (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL,
      estado_id INTEGER REFERENCES estados(id) ON DELETE SET NULL,
      UNIQUE(nome, estado_id))''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_municipios_estado ON municipios(estado_id)')

    cur.execute('''CREATE TABLE IF NOT EXISTS categorias (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL UNIQUE)''')

    cur.execute('''CREATE TABLE IF NOT EXISTS tipologias (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL UNIQUE)''')

    cur.execute('''CREATE TABLE IF NOT EXISTS situacoes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL UNIQUE)''')

    cur.execute('''CREATE TABLE IF NOT EXISTS prioridades (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL UNIQUE,
      ordem INTEGER NOT NULL)''')

    # ---- catálogo dos atributos ambientais (ex-colunas soltas do CSV) ------
    cur.execute('''CREATE TABLE IF NOT EXISTS grupos_atributos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL UNIQUE,
      descricao TEXT)''')

    cur.execute('''CREATE TABLE IF NOT EXISTS atributos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      chave TEXT NOT NULL UNIQUE,
      rotulo TEXT NOT NULL,
      grupo_id INTEGER REFERENCES grupos_atributos(id) ON DELETE SET NULL)''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_atributos_grupo ON atributos(grupo_id)')

    # ---- área verde (fato principal) ----------------------------------------
    cur.execute('''CREATE TABLE IF NOT EXISTS areas_verdes (
      id_area INTEGER PRIMARY KEY,
      nome_area TEXT,
      nome_demarcacao TEXT,
      descricao TEXT,
      categoria_id INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
      tipologia_id INTEGER REFERENCES tipologias(id) ON DELETE SET NULL,
      situacao_id INTEGER REFERENCES situacoes(id) ON DELETE SET NULL,
      municipio_id INTEGER REFERENCES municipios(id) ON DELETE SET NULL,
      data_criacao TEXT,
      area_m2 REAL,
      area_lago_m2 REAL,
      area_recuperar_m2 REAL,
      nascentes_num INTEGER,
      avaliacao_num REAL,
      indice_recuperacao REAL NOT NULL DEFAULT 0,
      prioridade_id INTEGER REFERENCES prioridades(id) ON DELETE SET NULL,
      projeto_melhoria INTEGER NOT NULL DEFAULT 0,
      recuperacao_proposta_texto TEXT,
      comentario_gestor TEXT,
      usos TEXT,
      palavras_chave TEXT)''')
    for idx, col in [('idx_area_municipio', 'municipio_id'), ('idx_area_tipologia', 'tipologia_id'),
                      ('idx_area_situacao', 'situacao_id'), ('idx_area_categoria', 'categoria_id'),
                      ('idx_area_prioridade', 'prioridade_id'), ('idx_area_indice', 'indice_recuperacao')]:
        cur.execute(f'CREATE INDEX IF NOT EXISTS {idx} ON areas_verdes({col})')

    # ---- atributos Sim/Não de cada área -------------------------------------
    cur.execute('''CREATE TABLE IF NOT EXISTS area_atributos (
      area_id INTEGER NOT NULL REFERENCES areas_verdes(id_area) ON DELETE CASCADE,
      atributo_id INTEGER NOT NULL REFERENCES atributos(id) ON DELETE CASCADE,
      valor INTEGER NOT NULL,
      PRIMARY KEY(area_id, atributo_id))''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_area_atributos_atributo ON area_atributos(atributo_id)')

    # ---- seed de prioridades (ordem fixa p/ ordenação) ----------------------
    for nome, ordem in [('Alta', 1), ('Média', 2), ('Baixa', 3)]:
        cur.execute('INSERT OR IGNORE INTO prioridades(nome,ordem) VALUES(?,?)', (nome, ordem))

    # ---- usuários padrão ------------------------------------------------------
    seeds = [('Usuário Geral', 'usuario1', '1234', 1), ('Diretoria Ambiental', 'diretor1', '1234', 2),
             ('Administrador do Sistema', 'admin', '1234', 3)]
    for nome, user, pwd, nivel in seeds:
        if not cur.execute('SELECT 1 FROM usuarios WHERE username=?', (user,)).fetchone():
            cur.execute('INSERT INTO usuarios(nome,username,senha_hash,nivel_acesso,criado_em) VALUES(?,?,?,?,?)',
                        (nome, user, generate_password_hash(pwd), nivel, datetime.now().isoformat()))
    con.commit()
    con.close()


# ------------------------------------------------------------------ usuários
def get_usuario_por_username(username):
    con = get_conn()
    r = con.execute('SELECT * FROM usuarios WHERE username=?', (username,)).fetchone()
    con.close()
    return r


def get_usuario_por_id(uid):
    con = get_conn()
    r = con.execute('SELECT * FROM usuarios WHERE id=?', (uid,)).fetchone()
    con.close()
    return r


def marcar_face_cadastrada(uid):
    con = get_conn()
    con.execute('UPDATE usuarios SET face_cadastrada=1 WHERE id=?', (uid,))
    con.commit()
    con.close()


def desmarcar_face_cadastrada(uid):
    con = get_conn()
    con.execute('UPDATE usuarios SET face_cadastrada=0 WHERE id=?', (uid,))
    con.commit()
    con.close()


def registrar_log(usuario, tipo_evento, sucesso, detalhes='', ip_origem=''):
    con = get_conn()
    usuario_id = None
    if usuario:
        r = con.execute('SELECT id FROM usuarios WHERE username=?', (usuario,)).fetchone()
        if r:
            usuario_id = r['id']
    con.execute('''INSERT INTO logs_acesso(usuario_id,usuario,tipo_evento,sucesso,detalhes,ip_origem,timestamp)
                    VALUES(?,?,?,?,?,?,?)''',
                (usuario_id, usuario, tipo_evento, int(sucesso), detalhes, ip_origem, datetime.now().isoformat()))
    con.commit()
    con.close()


def listar_logs(pagina=1, por_pagina=50):
    con = get_conn()
    total = con.execute('SELECT COUNT(*) c FROM logs_acesso').fetchone()['c']
    offset = (max(pagina, 1) - 1) * por_pagina
    r = con.execute('SELECT * FROM logs_acesso ORDER BY id DESC LIMIT ? OFFSET ?', (por_pagina, offset)).fetchall()
    con.close()
    return r, total


def listar_usuarios():
    con = get_conn()
    r = con.execute('SELECT id,nome,username,nivel_acesso,face_cadastrada,criado_em FROM usuarios ORDER BY id').fetchall()
    con.close()
    return r


# --------------------------------------------------------------- áreas verdes
_JOIN_AREAS = '''FROM areas_verdes a
    LEFT JOIN municipios m ON m.id = a.municipio_id
    LEFT JOIN estados e ON e.id = m.estado_id
    LEFT JOIN tipologias t ON t.id = a.tipologia_id
    LEFT JOIN situacoes s ON s.id = a.situacao_id
    LEFT JOIN categorias c ON c.id = a.categoria_id
    LEFT JOIN prioridades pr ON pr.id = a.prioridade_id'''

# Mapa das opções de filtro/dropdown para a coluna de apoio correta,
# já resolvida via join nas tabelas normalizadas (municipio/uf/tipologia/situação).
_OPCOES_CAMPO = {
    'municipio': 'm.nome',
    'uf': 'e.nome',
    'tipologia_normalizada': 't.nome',
    'situacao': 's.nome',
}


def listar_opcoes(col):
    """Lista os valores distintos (já usados em alguma área) de uma coluna
    'lógica' antiga (municipio/uf/tipologia_normalizada/situacao), agora
    resolvida via join nas tabelas de apoio."""
    campo = _OPCOES_CAMPO.get(col)
    if not campo:
        return []
    con = get_conn()
    sql = f'SELECT DISTINCT {campo} v {_JOIN_AREAS} WHERE {campo} IS NOT NULL ORDER BY v'
    r = con.execute(sql).fetchall()
    con.close()
    return [x['v'] for x in r]


def consultar_areas(filtros, pagina=1, por_pagina=50):
    con = get_conn()
    where = ['1=1']
    p = []
    if filtros.get('q'):
        where.append('a.nome_area LIKE ?'); p.append(f"%{filtros['q']}%")
    if filtros.get('municipio'):
        where.append('m.nome = ?'); p.append(filtros['municipio'])
    if filtros.get('uf'):
        where.append('e.nome = ?'); p.append(filtros['uf'])
    if filtros.get('tipo'):
        where.append('t.nome = ?'); p.append(filtros['tipo'])
    if filtros.get('situacao'):
        where.append('s.nome = ?'); p.append(filtros['situacao'])
    if filtros.get('prioridade'):
        where.append('pr.nome = ?'); p.append(filtros['prioridade'])
    if filtros.get('projeto'):
        where.append('a.projeto_melhoria = ?'); p.append(1 if filtros['projeto'] == 'Sim' else 0)
    where_sql = ' AND '.join(where)

    total = con.execute(f'SELECT COUNT(*) c {_JOIN_AREAS} WHERE {where_sql}', p).fetchone()['c']
    offset = (max(pagina, 1) - 1) * por_pagina
    sql = f'''SELECT a.id_area, a.nome_area, m.nome AS municipio, e.nome AS uf, t.nome AS tipo,
                     a.area_m2 AS area_m2_num, a.area_recuperar_m2, a.indice_recuperacao,
                     pr.nome AS prioridade,
                     CASE a.projeto_melhoria WHEN 1 THEN 'Sim' ELSE 'Não' END AS projeto_melhoria
              {_JOIN_AREAS}
              WHERE {where_sql}
              ORDER BY a.indice_recuperacao DESC, a.nome_area
              LIMIT ? OFFSET ?'''
    r = con.execute(sql, p + [por_pagina, offset]).fetchall()
    con.close()
    return r, total


# Atributos Sim/Não exibidos na ficha da área (área_detalhe.html).
_ATRIBUTOS_FICHA = [
    'area_com_vegetacao_perturbada_escassa_ou_ausente_50', 'sem_vegetacao',
    'vegetacao_predominantemente_nativa', 'vegetacao_predominantemente_exotica',
    'presenca_de_fauna_nativa', 'controle_de_erosao', 'mitigacao_de_ilhas_de_calor',
    'regulacao_da_permeabilidade_do_solo',
]


def obter_area(area_id):
    con = get_conn()
    base = con.execute(f'''
        SELECT a.id_area, a.nome_area, a.descricao, a.data_criacao,
               a.area_m2 AS area_m2_num, a.area_lago_m2, a.area_recuperar_m2,
               a.nascentes_num, a.avaliacao_num, a.indice_recuperacao,
               a.recuperacao_proposta_texto, a.usos,
               a.palavras_chave AS palavras_chaves_relacionadas_ao_registro,
               CASE a.projeto_melhoria WHEN 1 THEN 'Sim' ELSE 'Não' END AS projeto_melhoria,
               m.nome AS municipio, e.nome AS uf, t.nome AS tipologia_normalizada,
               s.nome AS situacao, c.nome AS categoria, pr.nome AS prioridade
        {_JOIN_AREAS}
        WHERE a.id_area = ?''', (area_id,)).fetchone()
    if not base:
        con.close()
        return None
    area = {k: base[k] for k in base.keys()}

    marcados = {r['chave']: r['valor'] for r in con.execute(f'''
        SELECT at.chave, aa.valor FROM area_atributos aa
        JOIN atributos at ON at.id = aa.atributo_id
        WHERE aa.area_id = ? AND at.chave IN ({','.join('?' * len(_ATRIBUTOS_FICHA))})''',
        [area_id] + _ATRIBUTOS_FICHA).fetchall()}
    for chave in _ATRIBUTOS_FICHA:
        v = marcados.get(chave)
        area[chave] = ('Sim' if v else 'Não') if v is not None else None
    con.close()
    return area


def indicadores():
    con = get_conn()
    total = con.execute('SELECT COUNT(*) c FROM areas_verdes').fetchone()['c']
    area_total = con.execute('SELECT COALESCE(SUM(area_m2),0) s FROM areas_verdes').fetchone()['s']
    recuperar = con.execute('SELECT COALESCE(SUM(area_recuperar_m2),0) s FROM areas_verdes').fetchone()['s']
    localizadas = con.execute('SELECT COUNT(*) c FROM areas_verdes WHERE municipio_id IS NOT NULL').fetchone()['c']
    projetos = con.execute('SELECT COUNT(*) c FROM areas_verdes WHERE projeto_melhoria=1').fetchone()['c']
    altas = con.execute('''SELECT COUNT(*) c FROM areas_verdes a
                            JOIN prioridades pr ON pr.id = a.prioridade_id
                            WHERE pr.nome='Alta' ''').fetchone()['c']

    def contagem_atributo(chave):
        r = con.execute('''SELECT COUNT(*) c FROM area_atributos aa
                            JOIN atributos at ON at.id = aa.atributo_id
                            WHERE at.chave = ? AND aa.valor = 1''', (chave,)).fetchone()
        return r['c']

    vegetacao = contagem_atributo('area_com_vegetacao_perturbada_escassa_ou_ausente_50')
    semveg = contagem_atributo('sem_vegetacao')
    erosao = contagem_atributo('controle_de_erosao')
    heat = contagem_atributo('mitigacao_de_ilhas_de_calor')

    por_uf = con.execute('''SELECT e.nome uf, COUNT(*) qtd, COALESCE(SUM(a.area_recuperar_m2),0) recuperar
                             FROM areas_verdes a
                             JOIN municipios m ON m.id = a.municipio_id
                             JOIN estados e ON e.id = m.estado_id
                             GROUP BY e.nome ORDER BY qtd DESC''').fetchall()
    por_prioridade = con.execute('''SELECT pr.nome prioridade, COUNT(*) qtd
                                     FROM areas_verdes a JOIN prioridades pr ON pr.id = a.prioridade_id
                                     GROUP BY pr.nome ORDER BY pr.ordem''').fetchall()
    por_tipo = con.execute('''SELECT t.nome tipo, COUNT(*) qtd, COALESCE(SUM(a.area_recuperar_m2),0) recuperar
                               FROM areas_verdes a LEFT JOIN tipologias t ON t.id = a.tipologia_id
                               GROUP BY t.nome ORDER BY qtd DESC LIMIT 10''').fetchall()
    top = con.execute(f'''SELECT a.id_area, a.nome_area, m.nome municipio, e.nome uf,
                                 a.area_recuperar_m2, a.indice_recuperacao, pr.nome prioridade
                          {_JOIN_AREAS}
                          WHERE a.indice_recuperacao > 0
                          ORDER BY a.indice_recuperacao DESC, a.area_recuperar_m2 DESC LIMIT 8''').fetchall()
    con.close()
    return dict(total=total, area_total=area_total, area_recuperar=recuperar, localizadas=localizadas,
                projetos=projetos, percent_projetos=(projetos / total * 100 if total else 0), altas=altas,
                vegetacao=vegetacao, sem_vegetacao=semveg, erosao=erosao, heat=heat,
                por_uf=por_uf, por_prioridade=por_prioridade, por_tipo=por_tipo, top=top)