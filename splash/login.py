"""
Ponto de entrada e "lançador" do sistema GreenId.

Roda com:
    python3 splash/login.py

Este módulo:
  1. Sobe o servidor Flask do sistema (pasta ../webapp/app.py) em
     segundo plano, numa porta livre da máquina;
  2. Espera o servidor responder;
  3. Abre a página inicial desse servidor no navegador padrão — a
     splash web com a logo animada em HTML/CSS, de onde o clique leva
     à tela de login;
  4. Mostra uma janelinha leve de "carregando" enquanto isso, para
     dar retorno visual ao usuário (evita a sensação de app travado).
"""

import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.normpath(os.path.join(HERE, "..", "webapp"))
WEBAPP_ENTRY = os.path.join(WEBAPP_DIR, "app.py")

HOST = "127.0.0.1"
PORT = 5000
# Aponta para a raiz do site (a splash web, com a logo animada em HTML/CSS),
# e não direto para /login — assim a logo também aparece "de verdade" no
# navegador, e o clique nela é que leva à tela de login.
URL_INICIAL = f"http://{HOST}:{PORT}/"

WIDTH, HEIGHT = 360, 150

_processo_servidor = None


def _servidor_ja_de_pe(host, port, timeout=0.3):
    """True se algo já está escutando em host:port (ex.: uma instância anterior)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _iniciar_servidor_flask():
    """Sobe o app.py do GreenId como um processo separado, sem abrir console extra."""
    global _processo_servidor

    if _servidor_ja_de_pe(HOST, PORT):
        return

    kwargs = {}
    if os.name == "nt":
        # Evita abrir uma janela de terminal extra no Windows.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    _processo_servidor = subprocess.Popen(
        [sys.executable, WEBAPP_ENTRY],
        cwd=WEBAPP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )


def _esperar_servidor(host, port, tentativas=60, intervalo=0.25):
    """Aguarda até a porta responder (ou desiste após 'tentativas' tentativas)."""
    for _ in range(tentativas):
        if _servidor_ja_de_pe(host, port):
            return True
        time.sleep(intervalo)
    return False


def abrir_login():
    """
    Ponto de entrada do sistema.

    Mostra uma janela curta de "Abrindo GreenId..." enquanto o servidor
    web sobe, depois abre o navegador na página inicial (splash web) do
    sistema.
    """
    janela = tk.Tk()
    janela.title("GreenID")
    janela.geometry(f"{WIDTH}x{HEIGHT}")
    janela.resizable(False, False)
    janela.configure(bg="#0F2924")

    try:
        janela.eval("tk::PlaceWindow . center")
    except tk.TclError:
        pass

    tk.Label(
        janela,
        text="GreenID",
        font=("Segoe UI", 15, "bold"),
        fg="#BFF070",
        bg="#0F2924",
    ).pack(pady=(22, 6))

    status = tk.Label(
        janela,
        text="Iniciando o sistema...",
        font=("Segoe UI", 10),
        fg="#E9FDF1",
        bg="#0F2924",
    )
    status.pack()

    barra = ttk.Progressbar(janela, mode="indeterminate", length=260)
    barra.pack(pady=18)
    barra.start(12)

    def worker():
        _iniciar_servidor_flask()
        ok = _esperar_servidor(HOST, PORT)

        def finalizar():
            barra.stop()
            if ok:
                status.config(text="Pronto! Abrindo no navegador...")
                webbrowser.open(URL_INICIAL)
                janela.after(700, janela.destroy)
            else:
                status.config(
                    text="Não foi possível iniciar o sistema.\nVerifique se a pasta 'webapp' está presente.",
                    fg="#F2A6A6",
                )

        janela.after(0, finalizar)

    threading.Thread(target=worker, daemon=True).start()

    janela.mainloop()


if __name__ == "__main__":
    abrir_login()