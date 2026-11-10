"""
Modulo de identificacao biometrica facial.

Usa OpenCV puro (sem dependencias pesadas como dlib):
  - Deteccao de rosto: Haar Cascade (cv2.CascadeClassifier)
  - Reconhecimento: LBPH - Local Binary Patterns Histograms
    (cv2.face.LBPHFaceRecognizer), treinado por usuario a partir
    de algumas fotos de cadastro.

Fluxo:
  1. Cadastro (enroll_face): usuario nivel 3 tira algumas fotos pela
     webcam (via navegador). As faces sao recortadas e salvas em
     faces/<user_id>/.
  2. Apos o cadastro, treinar_modelo() (re)treina o reconhecedor global
     com todas as fotos de todos os usuarios cadastrados.
  3. Login (reconhecer_face): a foto capturada no login passa por DUAS
     camadas de verificacao antes de ser aprovada:
       a) confianca absoluta: a distancia LBPH entre o rosto capturado
          e o modelo do usuario esperado precisa ficar abaixo de
          LIMIAR_CONFIANCA;
       b) margem de seguranca: o rosto capturado precisa estar
          claramente mais proximo do usuario esperado do que de
          QUALQUER outro usuario cadastrado (evita que um rosto
          parecido, mas de outra pessoa, seja aceito só porque a
          confianca absoluta ficou "boa o suficiente").
  4. Exclusao (excluir_face): o admin pode apagar as fotos cadastradas
     de um usuario a qualquer momento; o modelo global e retreinado
     (ou removido, se ninguem mais tiver cadastro) para que o rosto
     excluido deixe de ser reconhecido imediatamente.

LIMIAR_CONFIANCA: quanto MENOR o valor de confianca retornado pelo LBPH,
melhor o match (e uma distancia, nao uma probabilidade).

Ajuste fino (para deixar mais ou menos rigoroso):
  - Veja os valores reais de confianca em Administração → Logs de
    segurança (coluna Detalhes) após alguns logins de teste.
  - Se pessoas diferentes ainda estiverem sendo aceitas, DIMINUA
    LIMIAR_CONFIANCA e/ou AUMENTE MARGEM_MINIMA.
  - Se o próprio usuário cadastrado estiver sendo rejeitado com
    frequência, aumente um pouco o LIMIAR_CONFIANCA, ou recadastre o
    rosto com fotos mais variadas (ângulos/iluminação).
  - A segunda camada (margem de segurança) só entra em ação quando há
    pelo menos DOIS usuários com rosto cadastrado no sistema — com
    apenas um cadastro, o sistema não tem "outro rosto" para comparar,
    então depende só do limite de confiança absoluto. Para máxima
    segurança, cadastre o rosto de mais de um usuário de Nível 3.
"""
import base64
import shutil
from pathlib import Path

import cv2
import numpy as np

FACES_DIR = Path(__file__).parent / "faces"
MODEL_PATH = Path(__file__).parent / "instance" / "lbph_model.yml"
CASCADE_PATH = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")

# --- Parâmetros de segurança (ajustáveis) ---------------------------------
LIMIAR_CONFIANCA = 48.0   # quanto menor, mais rigoroso (era 75.0)
MARGEM_MINIMA = 12.0      # diferença mínima exigida entre o 1º e o 2º colocado
FOTOS_MINIMAS_CADASTRO = 8  # fotos por cadastro (era 5) — mais amostras, mais robustez

# Parâmetros do próprio algoritmo LBPH (mantidos fixos e explícitos para que
# o histograma calculado na verificação seja comparável ao do treino).
LBPH_RADIUS = 1
LBPH_NEIGHBORS = 8
LBPH_GRID_X = 8
LBPH_GRID_Y = 8

_face_cascade = cv2.CascadeClassifier(CASCADE_PATH)

if _face_cascade.empty():
    raise RuntimeError(
        "Não foi possível carregar o classificador de detecção de rosto "
        f"(Haar Cascade) em '{CASCADE_PATH}'. Isso costuma acontecer com "
        "Verifique se o pacote opencv-contrib-python 4.x está instalado e "
        "se o arquivo Haar Cascade está disponível em cv2.data.haarcascades. "
        "Para este projeto, use: "
        "pip uninstall opencv-contrib-python opencv-python opencv-python-headless "
        "&& pip install opencv-contrib-python==4.13.0.92"
    )


class SemRostoDetectado(Exception):
    pass


def _novo_recognizer():
    """Cria um LBPHFaceRecognizer sempre com os mesmos parâmetros, para que
    os histogramas gerados no treino e na verificação sejam comparáveis."""
    return cv2.face.LBPHFaceRecognizer_create(
        radius=LBPH_RADIUS,
        neighbors=LBPH_NEIGHBORS,
        grid_x=LBPH_GRID_X,
        grid_y=LBPH_GRID_Y,
    )


def _decode_base64_imagem(imagem_base64: str) -> np.ndarray:
    """Recebe uma string base64 (data URL da webcam) e devolve uma imagem BGR (OpenCV)."""
    if "," in imagem_base64:
        imagem_base64 = imagem_base64.split(",", 1)[1]
    dados = base64.b64decode(imagem_base64)
    arr = np.frombuffer(dados, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Não foi possível decodificar a imagem enviada.")
    return img


def _extrair_rosto(img_bgr: np.ndarray) -> np.ndarray:
    """Detecta o maior rosto na imagem e devolve um recorte em escala de cinza 200x200."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    rostos = _face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
    if len(rostos) == 0:
        raise SemRostoDetectado("Nenhum rosto detectado na imagem.")
    # pega o maior rosto encontrado
    x, y, w, h = max(rostos, key=lambda r: r[2] * r[3])
    recorte = gray[y:y + h, x:x + w]
    recorte = cv2.resize(recorte, (200, 200))
    return recorte


def enroll_face(user_id: int, imagem_base64: str) -> int:
    """Salva mais uma foto de rosto para o usuario. Retorna o total de fotos salvas."""
    pasta = FACES_DIR / str(user_id)
    pasta.mkdir(parents=True, exist_ok=True)
    img = _decode_base64_imagem(imagem_base64)
    rosto = _extrair_rosto(img)
    n_existentes = len(list(pasta.glob("*.png")))
    caminho = pasta / f"{n_existentes + 1}.png"
    cv2.imwrite(str(caminho), rosto)
    return n_existentes + 1


def fotos_cadastradas(user_id: int) -> int:
    pasta = FACES_DIR / str(user_id)
    if not pasta.exists():
        return 0
    return len(list(pasta.glob("*.png")))


def excluir_face(user_id: int) -> bool:
    """
    Remove TODAS as fotos de rosto cadastradas de um usuário e retreina o
    modelo global sem elas. Se ninguém mais restar com rosto cadastrado,
    o modelo antigo é apagado por completo — garantindo que o rosto
    excluído não continue sendo reconhecido pelo modelo salvo em disco.

    Retorna True se havia algum cadastro para remover.
    """
    pasta = FACES_DIR / str(user_id)
    tinha_cadastro = pasta.exists() and any(pasta.glob("*.png"))

    if pasta.exists():
        shutil.rmtree(pasta)

    modelo_ok = treinar_modelo()
    if not modelo_ok and MODEL_PATH.exists():
        # Não sobraram fotos suficientes de ninguém: remove o modelo
        # antigo para não deixar nenhum rosto "reconhecível" para trás.
        MODEL_PATH.unlink()

    return tinha_cadastro


def treinar_modelo() -> bool:
    """Retreina o reconhecedor LBPH com as fotos de todos os usuarios cadastrados."""
    faces, labels = [], []
    if not FACES_DIR.exists():
        return False
    for pasta_usuario in FACES_DIR.iterdir():
        if not pasta_usuario.is_dir():
            continue
        try:
            user_id = int(pasta_usuario.name)
        except ValueError:
            continue
        for foto in pasta_usuario.glob("*.png"):
            img = cv2.imread(str(foto), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                faces.append(img)
                labels.append(user_id)

    if len(faces) < FOTOS_MINIMAS_CADASTRO:
        return False

    recognizer = _novo_recognizer()
    recognizer.train(faces, np.array(labels))
    MODEL_PATH.parent.mkdir(exist_ok=True)
    recognizer.write(str(MODEL_PATH))
    return True


def _checar_margem_seguranca(rosto_gray, recognizer_treinado, user_id_esperado):
    """
    Segunda camada de verificação: compara o rosto capturado com os
    histogramas de TODOS os usuários cadastrados (não só o esperado) e
    exige que ele esteja claramente mais próximo do usuário esperado do
    que de qualquer outro. Isso evita aceitar um rosto parecido, mas de
    outra pessoa, quando o limite de confiança absoluto sozinho deixaria
    passar.

    Retorna (ok: bool, motivo: str).
    """
    labels = recognizer_treinado.getLabels().flatten()
    outros_labels = {int(l) for l in labels if int(l) != user_id_esperado}

    if not outros_labels:
        # Só há um usuário com rosto cadastrado no sistema: não existe
        # "outro rosto" para comparar, então esta camada extra é pulada
        # (a segurança depende apenas do limite de confiança absoluto).
        return True, ""

    histogramas = recognizer_treinado.getHistograms()

    # Histograma do rosto capturado, calculado com os MESMOS parâmetros
    # usados no treino do modelo, para que a comparação seja válida.
    temp = _novo_recognizer()
    temp.train([rosto_gray], np.array([0]))
    hist_capturado = temp.getHistograms()[0]

    melhor_por_label = {}
    for lbl, hist in zip(labels, histogramas):
        lbl = int(lbl)
        dist = cv2.compareHist(hist_capturado, hist, cv2.HISTCMP_CHISQR)
        if lbl not in melhor_por_label or dist < melhor_por_label[lbl]:
            melhor_por_label[lbl] = dist

    dist_esperado = melhor_por_label.get(user_id_esperado)
    if dist_esperado is None:
        return False, "Usuário informado não possui rosto cadastrado."

    dist_outro_mais_proximo = min(
        dist for lbl, dist in melhor_por_label.items() if lbl != user_id_esperado
    )

    margem = dist_outro_mais_proximo - dist_esperado
    if margem < MARGEM_MINIMA:
        return False, "Rosto muito parecido com o de outro usuário cadastrado; verificação recusada por segurança."

    return True, ""


def reconhecer_face(imagem_base64: str, user_id_esperado: int):
    """
    Tenta reconhecer o rosto na imagem enviada no login.
    Retorna (sucesso: bool, mensagem: str, confianca: float|None)
    """
    if not MODEL_PATH.exists():
        return False, "Nenhum modelo biométrico treinado ainda.", None

    img = _decode_base64_imagem(imagem_base64)
    try:
        rosto = _extrair_rosto(img)
    except SemRostoDetectado:
        return False, "Nenhum rosto detectado na imagem. Posicione-se em frente à câmera.", None

    recognizer = _novo_recognizer()
    recognizer.read(str(MODEL_PATH))
    label_previsto, confianca = recognizer.predict(rosto)

    if label_previsto != user_id_esperado:
        return False, "Rosto não corresponde ao usuário informado.", confianca
    if confianca > LIMIAR_CONFIANCA:
        return False, "Rosto não reconhecido com confiança suficiente.", confianca

    ok_margem, motivo = _checar_margem_seguranca(rosto, recognizer, user_id_esperado)
    if not ok_margem:
        return False, motivo, confianca

    return True, "Face reconhecida com sucesso.", confianca