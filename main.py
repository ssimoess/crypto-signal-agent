import os
import requests
import time

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"Erro ao enviar mensagem: {response.text}")
        else:
            print("Mensagem enviada com sucesso!")
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    send_telegram_message("🚀 Bot iniciado com sucesso e pronto para enviar sinais!")

    # Exemplo de loop contínuo (podes trocar pela lógica real de sinais)
    while True:
        # Aqui podes colocar a função que verifica sinais
        # Por agora só para teste:
        print("Bot ativo e a monitorizar sinais...")
        time.sleep(60)  # espera 1 minuto
