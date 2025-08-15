import os
import requests
import time
import ccxt
import numpy as np

# ==========================
# CONFIGURAÇÕES
# ==========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SCAN_SECS = int(os.getenv("SCAN_SECS", 60))  # segundos entre scans
MIN_PROB = 65  # Probabilidade mínima para enviar sinal

# Lista de moedas para varrimento (par USDT)
PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "SUI/USDT", "ENA/USDT", "BNB/USDT", "ADA/USDT", "DOGE/USDT",
    "LINK/USDT", "HBAR/USDT", "XLM/USDT", "LTC/USDT", "AVAX/USDT", "PENDLE/USDT", "NEAR/USDT", "AAVE/USDT",
    "ALGO/USDT", "RNDR/USDT", "LDO/USDT"
]

# Inicializar Binance API via CCXT
exchange = ccxt.binance()

# ==========================
# FUNÇÕES
# ==========================
def send_telegram_message(message):
    """Envia mensagem formatada para o Telegram"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=payload)
        if r.status_code != 200:
            print(f"Erro ao enviar para Telegram: {r.text}")
    except Exception as e:
        print(f"Erro Telegram: {e}")

def get_rsi(prices, period=14):
    """Calcula o RSI"""
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        upval, downval = (delta, 0) if delta > 0 else (0, -delta)
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)
    return rsi

def analyze_pair(symbol):
    """Analisa uma moeda e retorna sinal se cumprir critérios"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="15m", limit=100)
        closes = [x[4] for x in ohlcv]

        # RSI
        rsi = get_rsi(np.array(closes))[-1]

        # EMA21 e EMA50
        ema21 = np.mean(closes[-21:])
        ema50 = np.mean(closes[-50:])

        # Bollinger Bands
        sma20 = np.mean(closes[-20:])
        stddev = np.std(closes[-20:])
        upper_band = sma20 + (2 * stddev)
        lower_band = sma20 - (2 * stddev)

        # Volume médio
        volumes = [x[5] for x in ohlcv]
        avg_volume = np.mean(volumes[-20:])
        last_volume = volumes[-1]

        # Condições de sinal
        probabilidade = 0
        direcao = None
        preco_atual = closes[-1]

        if rsi < 30 and preco_atual <= lower_band and ema21 > ema50 and last_volume > avg_volume * 1.5:
            probabilidade = 75
            direcao = "LONG"
        elif rsi > 70 and preco_atual >= upper_band and ema21 < ema50 and last_volume > avg_volume * 1.5:
            probabilidade = 75
            direcao = "SHORT"

        if probabilidade >= MIN_PROB:
            stop = preco_atual * (0.98 if direcao == "LONG" else 1.02)
            tp1 = preco_atual * (1.02 if direcao == "LONG" else 0.98)
            tp2 = preco_atual * (1.04 if direcao == "LONG" else 0.96)
            alavancagem = "x5"
            return {
                "par": symbol,
                "direcao": direcao,
                "entrada": round(preco_atual, 4),
                "stop": round(stop, 4),
                "tp1": round(tp1, 4),
                "tp2": round(tp2, 4),
                "probabilidade": probabilidade,
                "alavancagem": alavancagem
            }
        return None
    except Exception as e:
        print(f"Erro a analisar {symbol}: {e}")
        return None

# ==========================
# LOOP PRINCIPAL
# ==========================
if __name__ == "__main__":
    send_telegram_message("🚀 Bot iniciado - 📌 Alavancagem Curto")
    while True:
        for pair in PAIRS:
            sinal = analyze_pair(pair)
            if sinal:
                msg = (
                    f"📌 <b>Alavancagem Curto</b>\n"
                    f"Par: {sinal['par']}\n"
                    f"Direção: {sinal['direcao']}\n"
                    f"Entrada: {sinal['entrada']}\n"
                    f"Stop: {sinal['stop']}\n"
                    f"TP1: {sinal['tp1']}\n"
                    f"TP2: {sinal['tp2']}\n"
                    f"Probabilidade: {sinal['probabilidade']}%\n"
                    f"Alavancagem: {sinal['alavancagem']}"
                )
                send_telegram_message(msg)
        time.sleep(SCAN_SECS)
