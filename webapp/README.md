# GreenId — Sistema de Consulta e Gestão de Áreas Verdes Urbanas

Protótipo funcional da APS (Processamento de Imagens e Visão Computacional).
Plataforma web em **Flask (Python)** para consulta de dados ambientais
(áreas verdes urbanas / GEOCAU) com **autenticação em 3 níveis de acesso**
e **reconhecimento facial biométrico no Nível 3 (administrador)**.

## 1. Como rodar

```bash
# 1. Crie um ambiente virtual (recomendado)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Gere o dataset de exemplo e trate os dados com Pandas
python3 data/gerar_dataset.py
python3 etl.py

# 4. Rode a aplicação
python3 app.py
```

Acesse **http://localhost:5000** no navegador (Chrome/Edge recomendados,
precisam de permissão de câmera para o login de Nível 3).

> A câmera só funciona em `localhost` ou HTTPS — é uma exigência do próprio
> navegador para APIs de mídia (`getUserMedia`), não uma limitação do código.

## 2. Usuários de demonstração

| Usuário     | Senha | Nível | Observação                              |
|-------------|-------|-------|------------------------------------------|
| `usuario1`  | 1234  | 1     | Acesso geral                              |
| `diretor1`  | 1234  | 2     | Acesso restrito (direção)                 |
| `admin`     | 1234  | 3     | Administrador — exige cadastro facial no primeiro acesso |

No primeiro login do `admin`, o sistema pede o **cadastro do rosto**
(mínimo de 5 fotos pela webcam) antes de liberar o acesso administrativo.
Nos logins seguintes, basta senha + verificação facial.

## 3. Sobre a base de dados

Este protótipo usa um **dataset sintético** (`data/gerar_dataset.py`) com a
mesma estrutura conceitual da base real *Áreas Verdes Urbanas (GEOCAU)* do
Portal de Dados Abertos do MMA, pois este ambiente de desenvolvimento não
tem acesso à internet para baixar o arquivo oficial.

**Para a entrega, troque pela base real:**
1. Baixe o CSV/GeoJSON oficial do portal do MMA.
2. Salve como `data/areas_verdes_raw.csv`, ajustando `etl.py` para as
   colunas reais do arquivo baixado (o pipeline de limpeza — duplicatas,
   valores faltantes, padronização de tipos — pode ser reaproveitado).
3. Rode `python3 etl.py` novamente.

## 4. Arquitetura

```
greenid/
├── app.py            # Rotas Flask, autenticação, autorização por nível
├── database.py        # Camada de acesso ao SQLite (usuários, logs, dados)
├── biometria.py        # Detecção (Haar Cascade) + reconhecimento facial (LBPH/OpenCV)
├── etl.py             # Pandas: limpeza e carga da base ambiental no banco
├── data/
│   ├── gerar_dataset.py   # Gera dataset sintético (substituir pelo real)
│   └── areas_verdes_raw.csv
├── faces/<user_id>/   # Fotos de rosto cadastradas (por usuário)
├── instance/
│   ├── greenid.db      # Banco SQLite (usuários, logs, áreas verdes)
│   └── lbph_model.yml   # Modelo de reconhecimento facial treinado
├── templates/          # Páginas HTML (Jinja2)
└── static/             # CSS e JS (captura de câmera)
```

### Camadas (mapeando para o que a Entrega Intermediária pede)

- **Interface**: templates Jinja2 + CSS/JS puro (captura de webcam via
  `getUserMedia`, envio da imagem em base64).
- **Regras de negócio / autorização**: decoradores `login_requerido` e
  `nivel_requerido(n)` em `app.py`; a rota `/consulta` também restringe
  quais **colunas** são retornadas conforme o nível do usuário.
- **Autenticação**: senha (hash com `werkzeug.security`) para todos os
  níveis; **Nível 3 exige uma segunda etapa** de biometria facial antes de
  a sessão ser efetivamente criada (`session['pendente_id']` fica "em
  espera" até a face ser confirmada).
- **Banco de dados**: SQLite (`database.py`), normalizado com chaves
  estrangeiras: `usuarios` ⟶ `logs_acesso`; e `estados` ⟶ `municipios`,
  `categorias`, `tipologias`, `situacoes` e `prioridades` ⟶ `areas_verdes`
  ⟶ `area_atributos` ⟵ `atributos` ⟵ `grupos_atributos` (as ~120 colunas
  Sim/Não do CSV original — bancos, vigilante, ciclovia, compostagem etc. —
  viraram um catálogo de atributos + uma tabela de ligação, em vez de
  colunas soltas repetidas). Tudo é carregado pelo `etl.py`; veja o
  cabeçalho de `database.py` para o diagrama completo.

### Segurança e tratamento de exceções

Tudo é registrado em `logs_acesso` (`database.registrar_log`):
- usuário não identificado;
- senha incorreta (erro de autenticação);
- falha no reconhecimento facial (rosto não encontrado / não corresponde /
  confiança insuficiente), com o valor de confiança do LBPH salvo no log;
- tentativa de acessar rota sem login;
- tentativa de acessar recurso de nível superior ao do usuário (ex.:
  Nível 1 tentando abrir `/admin/logs`).

Os logs ficam visíveis para o Nível 3 em **Administração → Logs de segurança**.

## 5. Limitações conhecidas (transparência para a banca)

- O reconhecimento facial usa **LBPH (OpenCV)**, uma técnica clássica de
  visão computacional — leve e sem dependências pesadas (dlib/deep
  learning), adequada para um protótipo educacional, mas menos robusta que
  soluções baseadas em embeddings profundos.
- O dataset ambiental usado no protótipo é sintético (ver seção 3).
- `app.secret_key` está fixa no código só para fins de demonstração; em
  produção deve vir de variável de ambiente.
