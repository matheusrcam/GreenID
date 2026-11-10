"""ETL da base real do CAU para o GreenID.

Importa os dados do Cadastro Ambiental Urbano (CAU) para o banco
normalizado utilizado pelo GreenID.

Mantém:
- dados completos do CAU em dados_cau;
- áreas verdes em areas_verdes;
- estados e municípios normalizados;
- categorias, tipologias, situações e prioridades;
- atributos ambientais em area_atributos;
- índice de recuperação e prioridade calculados pelo projeto.
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd

import database as db

BASE_DIR = Path(__file__).parent
RAW_CSV = BASE_DIR / 'data' / 'cadastros-no-cau-ate-jan-2026_pda.csv'
DB_PATH = BASE_DIR / 'instance' / 'greenid.db'

# Colunas originais do CSV que também funcionam como catálogo de atributos
# Sim/Não (usado por inserir_atributos e inserir_area_atributos).
N_COLUNAS_ORIGINAIS = 137


# ---------------------------------------------------------------------
# Tratamento de valores
# ---------------------------------------------------------------------
def numero_br(valor):
    if pd.isna(valor):
        return None

    s = str(valor).strip().lower().replace('m2', '').replace('m²', '').replace(' ', '')
    if s in {'', 'n/d', 'n/a', '-', 'na', 'nan', 'none'}:
        return None

    s = re.sub(r'[^0-9,.-]', '', s)
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')

    try:
        return float(s)
    except ValueError:
        return None


def sim(valor):
    return str(valor).strip().lower() == 'sim'


def normalizar_texto(valor):
    if pd.isna(valor):
        return None
    s = str(valor).strip()
    return None if s.lower() in {'', 'none', 'nan', 'n/d', 'n/a'} else s


def nome_coluna(col, i):
    s = str(col).strip().lower()
    mapa = str.maketrans('áàãâäéèêëíìîïóòõôöúùûüçñ', 'aaaaaeeeeiiiiooooouuuucn')
    s = s.translate(mapa)
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return (s or f'campo_{i}')[:80]


# ---------------------------------------------------------------------
# Leitura da fonte
# ---------------------------------------------------------------------
def ler_fonte():
    return pd.read_csv(RAW_CSV, encoding='latin1', sep=';', skiprows=1, dtype=str, keep_default_na=False)


# ---------------------------------------------------------------------
# Tratamento e cálculos
# ---------------------------------------------------------------------
def tratar_dados(df):
    df = df.copy()
    df = df.replace({'': None, 'n/d': None, 'N/D': None, 'n/a': None, 'N/A': None})
    df = df.drop_duplicates().reset_index(drop=True)

    # Normaliza nomes das colunas sem perder nenhuma coluna (nem duplicar nomes).
    novas, usados = [], set()
    for i, c in enumerate(df.columns):
        n = base = nome_coluna(c, i)
        k = 2
        while n in usados:
            n = f'{base}_{k}'
            k += 1
        usados.add(n)
        novas.append(n)
    df.columns = novas

    df['id_area'] = range(1, len(df) + 1)

    # -------------------------------------------------------------
    # Campos principais
    # -------------------------------------------------------------
    df['data_criacao'] = pd.to_datetime(df['data_de_criacao'], dayfirst=True, errors='coerce')
    df['area_m2_num'] = df['area_verde_demarcada_m'].map(numero_br)
    df['area_recuperar_m2'] = df['somatorio_de_area_a_ser_recuperada_poligonias_vermelhas_m'].map(numero_br)
    df['area_lago_m2'] = df['somatorio_de_area_de_lago_lagoa_represa_poligonais_azuis_m'].map(numero_br)
    df['nascentes_num'] = pd.to_numeric(df['quantidade_de_nascentes'], errors='coerce')
    df['avaliacao_num'] = pd.to_numeric(df['media_de_avaliacoes_cadastrador_e_cau_cidadao_1_a_5'], errors='coerce')

    # -------------------------------------------------------------
    # Índice de recuperação
    # -------------------------------------------------------------
    def score(r):
        pontos = 0.0
        area = r['area_m2_num'] or 0
        rec = r['area_recuperar_m2'] or 0
        perturbada = sim(r.get('area_com_vegetacao_perturbada_escassa_ou_ausente_50', ''))

        if rec > 0:
            pontos += 30
        elif area > 0 and perturbada:
            pontos += 18

        if perturbada:
            pontos += 20
        if sim(r.get('sem_vegetacao', '')):
            pontos += 15
        if sim(r.get('vegetacao_predominantemente_exotica', '')):
            pontos += 8
        if sim(r.get('ausencia_de_fauna_nativa', '')) or sim(r.get('ausencia_de_fauna_nativa_1', '')):
            pontos += 7
        if sim(r.get('controle_de_erosao', '')):
            pontos += 5
        if sim(r.get('mitigacao_de_ilhas_de_calor', '')):
            pontos += 5
        if sim(r.get('regulacao_da_permeabilidade_do_solo', '')):
            pontos += 5
        if str(r.get('tem_projeto_de_melhoria_para_a_area', '')).strip().lower() == 'não':
            pontos += 3
        if r.get('recuperacao_proposta'):
            pontos += 2

        return round(min(pontos, 100), 1)

    df['indice_recuperacao'] = df.apply(score, axis=1)
    df['prioridade'] = pd.cut(df['indice_recuperacao'], bins=[-1, 29.9, 59.9, 100],
                               labels=['Baixa', 'Média', 'Alta']).astype(str)

    # -------------------------------------------------------------
    # Campos normalizados
    # -------------------------------------------------------------
    df['uf'] = df['uf_do_registro'].map(normalizar_texto)
    df['municipio'] = df['municipio_do_registro'].map(normalizar_texto)
    df['nome_area'] = df['nome_da_area'].map(normalizar_texto)
    df['tipologia_normalizada'] = df['tipologia'].map(normalizar_texto)
    df['situacao'] = df['situacao_do_registro'].map(normalizar_texto)
    df['categoria_normalizada'] = df['categoria'].map(normalizar_texto)
    df['recuperacao_proposta_texto'] = df['recuperacao_proposta'].fillna('').astype(str).str.strip()
    df['projeto_melhoria'] = (df['tem_projeto_de_melhoria_para_a_area']
                               .fillna('Não').astype(str).str.strip().str.lower().eq('sim').astype(int))
    return df


# ---------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------
# Tabelas de versões anteriores do ETL que não fazem mais parte do modelo
# atual (ver database.py) e precisam sair antes de recriar a estrutura.
TABELAS_OBSOLETAS = [
    'area_atributos', 'atributos', 'grupos_atributos', 'areas_avaliacao', 'areas_indicadores',
    'areas_recuperacao', 'areas_beneficios', 'areas_producao', 'areas_agua', 'areas_gestao',
    'areas_infraestrutura', 'areas_seguranca', 'areas_lazer', 'areas_ambientais', 'areas_contexto',
    'areas_demarcacao', 'areas_cadastro', 'areas', 'dados_cau',
]


def preparar_banco(con):
    """Remove somente estruturas ambientais antigas. Usuários e logs permanecem intactos."""
    obj = con.execute("SELECT type FROM sqlite_master WHERE name='areas_verdes'").fetchone()
    if obj:
        con.execute(f'DROP {obj[0].upper()} areas_verdes')

    for tabela in TABELAS_OBSOLETAS:
        con.execute(f'DROP TABLE IF EXISTS "{tabela}"')
    con.commit()
    # O db.init_db(), chamado em seguida por carregar(), recria a estrutura correta.


# ---------------------------------------------------------------------
# Inserção das tabelas auxiliares
# ---------------------------------------------------------------------
def _valores_unicos(serie):
    return sorted({v for v in serie.dropna() if str(v).strip()})


def inserir_valores_unicos(con, tabela, serie):
    """INSERT OR IGNORE de todo valor distinto e não vazio de `serie` em `tabela(nome)`."""
    for valor in _valores_unicos(serie):
        con.execute(f'INSERT OR IGNORE INTO {tabela}(nome) VALUES (?)', (valor,))


def inserir_lookups(con, df):
    inserir_valores_unicos(con, 'estados', df['uf'])
    inserir_valores_unicos(con, 'categorias', df['categoria_normalizada'])
    inserir_valores_unicos(con, 'tipologias', df['tipologia_normalizada'])
    inserir_valores_unicos(con, 'situacoes', df['situacao'])

    # Municípios dependem do estado (FK), então são tratados à parte.
    for _, row in df[['municipio', 'uf']].dropna(subset=['municipio', 'uf']).drop_duplicates().iterrows():
        estado = con.execute('SELECT id FROM estados WHERE nome = ?', (row['uf'],)).fetchone()
        if estado:
            con.execute('INSERT OR IGNORE INTO municipios(nome, estado_id) VALUES (?, ?)',
                        (row['municipio'], estado['id']))
    con.commit()


# ---------------------------------------------------------------------
# Dados completos do CAU
# ---------------------------------------------------------------------
def inserir_dados_cau(con, df):
    out = df.copy()
    out['data_criacao'] = out['data_criacao'].dt.strftime('%Y-%m-%d')
    out = out.where(pd.notna(out), None)
    out.to_sql('dados_cau', con, if_exists='replace', index=False)


# ---------------------------------------------------------------------
# Área principal normalizada
# ---------------------------------------------------------------------
def buscar_id(con, tabela, nome):
    if not nome:
        return None
    r = con.execute(f'SELECT id FROM {tabela} WHERE nome = ?', (nome,)).fetchone()
    return r['id'] if r else None


def buscar_municipio_id(con, municipio, uf):
    if not municipio or not uf:
        return None
    r = con.execute('''SELECT m.id FROM municipios m JOIN estados e ON e.id = m.estado_id
                        WHERE m.nome = ? AND e.nome = ?''', (municipio, uf)).fetchone()
    return r['id'] if r else None


def inserir_areas_verdes(con, df):
    sql = '''INSERT INTO areas_verdes (
        id_area, nome_area, nome_demarcacao, descricao, categoria_id, tipologia_id, situacao_id,
        municipio_id, data_criacao, area_m2, area_lago_m2, area_recuperar_m2, nascentes_num,
        avaliacao_num, indice_recuperacao, prioridade_id, projeto_melhoria,
        recuperacao_proposta_texto, usos, palavras_chave
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''

    for _, r in df.iterrows():
        data = r['data_criacao'].strftime('%Y-%m-%d') if pd.notna(r['data_criacao']) else None
        con.execute(sql, (
            int(r['id_area']),
            r['nome_area'],
            normalizar_texto(r.get('nome_da_demarcacao')),
            normalizar_texto(r.get('descricao')),
            buscar_id(con, 'categorias', r['categoria_normalizada']),
            buscar_id(con, 'tipologias', r['tipologia_normalizada']),
            buscar_id(con, 'situacoes', r['situacao']),
            buscar_municipio_id(con, r['municipio'], r['uf']),
            data,
            r['area_m2_num'],
            r['area_lago_m2'],
            r['area_recuperar_m2'],
            int(r['nascentes_num']) if pd.notna(r['nascentes_num']) else None,
            r['avaliacao_num'],
            float(r['indice_recuperacao']),
            buscar_id(con, 'prioridades', r['prioridade']),
            int(r['projeto_melhoria']),
            r['recuperacao_proposta_texto'],
            normalizar_texto(r.get('usos')),
            normalizar_texto(r.get('palavras_chave')),
        ))
    con.commit()


# ---------------------------------------------------------------------
# Atributos ambientais
# ---------------------------------------------------------------------
# Grupos temáticos do CAU e as pistas (substrings do nome da coluna) usadas
# para classificar cada atributo binário automaticamente. A ordem importa:
# a primeira pista que bater define o grupo.
GRUPOS_ATRIBUTOS = {
    'Cadastro': 'Informações gerais da área',
    'Demarcação': 'Características da demarcação',
    'Recuperação': 'Informações relacionadas à recuperação',
    'Contexto': 'Contexto da área',
    'Ambientais': 'Características ambientais',
    'Lazer': 'Estruturas e usos de lazer',
    'Segurança': 'Estruturas de segurança',
    'Infraestrutura': 'Infraestrutura disponível',
    'Gestão': 'Informações de gestão',
    'Água': 'Características relacionadas à água',
    'Produção': 'Atividades produtivas',
    'Benefícios': 'Benefícios ambientais e sociais',
}
PISTAS_GRUPO = [
    ('Recuperação', ('recuper', 'projeto')),
    ('Lazer', ('lazer', 'recrea')),
    ('Segurança', ('segur', 'vigil')),
    ('Infraestrutura', ('infra', 'ciclovia', 'ilumin')),
    ('Gestão', ('gest', 'administr')),
    ('Água', ('nascente', 'lago', 'agua')),
    ('Produção', ('produ', 'horta')),
    ('Benefícios', ('benef', 'fauna')),
]


def _classificar_grupo(coluna):
    for grupo, pistas in PISTAS_GRUPO:
        if any(pista in coluna for pista in pistas):
            return grupo
    return 'Ambientais'


def colunas_binarias(df):
    """Colunas originais (entre as N_COLUNAS_ORIGINAIS primeiras) cujos
    valores são exclusivamente Sim/Não — usadas como catálogo de atributos."""
    binarias = []
    for coluna in df.columns[:N_COLUNAS_ORIGINAIS]:
        valores = df[coluna].dropna().astype(str).str.strip().str.lower()
        if valores.isin(['sim', 'não']).any():
            binarias.append(coluna)
    return binarias


def inserir_atributos(con, df):
    for nome, descricao in GRUPOS_ATRIBUTOS.items():
        con.execute('INSERT OR IGNORE INTO grupos_atributos(nome, descricao) VALUES (?, ?)', (nome, descricao))
    con.commit()

    for coluna in colunas_binarias(df):
        grupo = con.execute('SELECT id FROM grupos_atributos WHERE nome = ?',
                             (_classificar_grupo(coluna),)).fetchone()
        con.execute('INSERT OR IGNORE INTO atributos(chave, rotulo, grupo_id) VALUES (?, ?, ?)',
                    (coluna[:80], coluna.replace('_', ' ').strip().capitalize(), grupo['id'] if grupo else None))
    con.commit()


def inserir_area_atributos(con, df):
    atributo_id_por_coluna = {}
    for coluna in colunas_binarias(df):
        r = con.execute('SELECT id FROM atributos WHERE chave = ?', (coluna[:80],)).fetchone()
        if r:
            atributo_id_por_coluna[coluna] = r['id']

    for _, row in df.iterrows():
        for coluna, atributo_id in atributo_id_por_coluna.items():
            valor = str(row.get(coluna, '')).strip().lower()
            if valor in {'sim', 'não'}:
                con.execute('INSERT OR REPLACE INTO area_atributos(area_id, atributo_id, valor) VALUES (?, ?, ?)',
                            (int(row['id_area']), atributo_id, 1 if valor == 'sim' else 0))
    con.commit()


# ---------------------------------------------------------------------
# Execução principal
# ---------------------------------------------------------------------
def carregar(df):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA foreign_keys = ON')
        preparar_banco(con)          # remove a estrutura ambiental antiga
        con.close()

        db.init_db()                 # recria as tabelas esperadas pelo database.py

        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys = ON')

        inserir_dados_cau(con, df)       # 1. guarda os dados completos do CAU
        inserir_lookups(con, df)         # 2. cria estados, municípios, categorias etc.
        inserir_areas_verdes(con, df)    # 3. alimenta a tabela principal
        inserir_atributos(con, df)       # 4. cria catálogo de atributos
        inserir_area_atributos(con, df)  # 5. relaciona os atributos às áreas
        con.commit()

        # ---------------------------------------------------------
        # Conferência final
        # ---------------------------------------------------------
        contagens = {
            'Áreas verdes': con.execute('SELECT COUNT(*) c FROM areas_verdes').fetchone()['c'],
            'Registros CAU': con.execute('SELECT COUNT(*) c FROM dados_cau').fetchone()['c'],
            'Estados': con.execute('SELECT COUNT(*) c FROM estados').fetchone()['c'],
            'Municípios': con.execute('SELECT COUNT(*) c FROM municipios').fetchone()['c'],
            'Atributos': con.execute('SELECT COUNT(*) c FROM atributos').fetchone()['c'],
        }
        print()
        print('==============================================')
        print('       GREENID - ETL CONCLUÍDO')
        print('==============================================')
        for rotulo, valor in contagens.items():
            print(f'{rotulo + ":":<20}{valor}')
        print('Banco normalizado:  OK')
        print('Índice recuperação: OK')
        print('==============================================')
    finally:
        con.close()


if __name__ == '__main__':
    if not RAW_CSV.exists():
        raise SystemExit(f'Fonte não encontrada: {RAW_CSV}')
    carregar(tratar_dados(ler_fonte()))