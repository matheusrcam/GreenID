# GreenID — Recuperação de Áreas Verdes

Sistema web acadêmico para consulta, análise e priorização de recuperação de áreas verdes urbanas.

## Base utilizada

O projeto foi adaptado para o arquivo real `webapp/data/cadastros-no-cau-ate-jan-2026_pda.csv`, com registros do CAU de 21/09/2020 a 16/01/2026.

A base possui 12.437 registros após a remoção de duplicatas e 137 campos originais. O ETL preserva os campos da fonte e acrescenta indicadores derivados.

## O que mudou

- Dashboard voltado para recuperação de áreas verdes.
- Indicadores de área verde demarcada e área explicitamente indicada para recuperação.
- Triagem de áreas com filtros por UF, município, tipologia, situação, prioridade e projeto de melhoria.
- Ficha detalhada da área.
- Índice heurístico de prioridade de recuperação (0–100), explicado na ficha.
- Destaque para vegetação perturbada/ausente, vegetação exótica, fauna, erosão, ilhas de calor e permeabilidade.
- Mantidos login, níveis de acesso, biometria facial e logs de segurança.

## Índice de recuperação

O índice é uma **heurística acadêmica de triagem**, não um diagnóstico ambiental. Ele usa evidências existentes no cadastro para ordenar as áreas que podem merecer análise técnica primeiro.

Pesos principais:

- Área explicitamente indicada para recuperação: +30
- Vegetação perturbada/escassa/ausente > 50%: +20
- Sem vegetação: +15
- Vegetação predominantemente exótica: +8
- Ausência de fauna nativa: +7
- Controle de erosão indicado: +5
- Mitigação de ilhas de calor indicada: +5
- Regulação da permeabilidade indicada: +5
- Sem projeto de melhoria: +3
- Proposta de recuperação registrada: +2

O resultado é limitado a 100 e classificado em Baixa, Média ou Alta.

## Como executar

1. Instale Python 3.11+.
2. Crie o ambiente virtual.
3. Instale `requirements.txt`.
4. Entre em `webapp/`.
5. Execute `python etl.py` para reconstruir o SQLite com a base real.
6. Execute `python app.py`.
7. Acesse `http://localhost:5000`.

### Usuários de demonstração

- `usuario1` / `1234` — Nível 1
- `diretor1` / `1234` — Nível 2
- `admin` / `1234` — Nível 3 (biometria)

Em produção, troque as credenciais, `secret_key` e a senha extra de cadastro biométrico.

## Estrutura

- `webapp/etl.py` — limpeza, transformação, índice e carga SQLite.
- `webapp/database.py` — acesso ao banco e indicadores.
- `webapp/app.py` — autenticação e rotas.
- `webapp/templates/dashboard.html` — painel de recuperação.
- `webapp/templates/consulta.html` — triagem.
- `webapp/templates/area_detalhe.html` — ficha da área.
- `webapp/static/css/style.css` — identidade visual.
