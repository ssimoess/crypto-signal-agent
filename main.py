
import os
import time
import requests
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"[ERRO] Falha ao enviar mensagem: {e}")

def check_signals():
    """
    Aqui vais colocar no futuro a lógica de verificação de sinais.
    Para já vamos simular que achou um sinal válido.
    """
    return {
        "symbol": "BTCUSDT",
        "entry": 60000,
        "stop": 59500,
        "tp1": 60500,
        "tp2": 61000,
        "prob": 75,
        "lev": 10
    }

def main():
    # Mensagem de teste ao iniciar
    send_telegram_message("✅ Bot ativo - teste de envio")

    while True:
        signal = check_signals()
        if signal:
            message = (
                "📌 Alavancagem Curto\n\n"
                f"Ativo: {signal['symbol']}\n"
                f"Entrada: {signal['entry']}\n"
                f"Stop: {signal['stop']}\n"
                f"TP1: {signal['tp1']}\n"
                f"TP2: {signal['tp2']}\n"
                f"Probabilidade: {signal['prob']}%\n"
                f"Alavancagem: x{signal['lev']}\n"
                f"Hora: {datetime.now().strftime('%H:%M:%S')}"
            )
            send_telegram_message(message)

        time.sleep(60)  # Executa a cada 1 minuto

if __name__ == "__main__":
    main()
