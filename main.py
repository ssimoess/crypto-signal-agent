import os
import time
import requests
import ccxt
import numpy as np
from datetime import datetime

# ==========================
# CONFIGURAÇÕES
# ==========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
SCAN_SECS = int(os.getenv("SCAN_SECS", "60"))  # segundos entre scans
MIN_PROB = 65  # Probabilidade mínima para enviar sinal (em %)

# Lista de moedas (pares USDT) a monitorizar
PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "SUI/USDT", "ENA/USDT",
    "BNB/USDT", "ADA/USDT", "DOGE/USDT", "LINK/USDT", "HBAR/USDT", "XLM/USDT",
    "LTC/USDT", "AVAX/USDT", "PENDLE/USDT", "NEAR/USDT", "AAVE/USDT",
    "ALGO/USDT", "RNDR/USDT", "LDO/USDT"
]

# Inicializar Binance via CCXT
exchange = ccxt.binance()


# ==========================
# AUXILIARES
# ==========================
def send_telegram_message(text: str) -> None:
    """Envia mensagem para o Telegram."""
    if not BOT_TOKEN or not CHAT_ID:
        print("[ERRO] BOT_TOKEN/CHAT_ID não definidos nas variáveis do Railway.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code != 200:
            print(f"[ERRO TG] {r.text}")
    except Exception as e:
        print(f"[ERRO TG] {e}")


def get_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI clássico (vectorizado simples)."""
    if prices.size < period + 1:
        return np.zeros_like(prices)

    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0.0

    rsi = np.zeros_like(prices)
    rsi[:period] = 100.0 - 100.0 / (1.0 + rs)

    up_avg, down_avg = up, down
    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        up_val = delta if delta > 0 else 0.0
        down_val = -delta if delta < 0 else 0.0
        up_avg = (up_avg * (period - 1) + up_val) / period
        down_avg = (down_avg * (period - 1) + down_val) / period
        rs = up_avg / down_avg if down_avg != 0 else 0.0
        rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def analyze_pair(symbol: str):
    """Analisa o par e devolve dict de sinal ou None."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="15m", limit=100)
        closes = np.array([x[4] for x in ohlcv], dtype=float)
        volumes = np.array([x[5] for x in ohlcv], dtype=float)

        if closes.size < 50:
            return None

        # Indicadores
        rsi_val = float(get_rsi(closes)[-1])
        ema21 = float(np.mean(closes[-21:]))
        ema50 = float(np.mean(closes[-50:]))

        sma20 = float(np.mean(closes[-20:]))
        std20 = float(np.std(closes[-20:]))
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20

        avg_vol = float(np.mean(volumes[-20:]))
        last_vol = float(volumes[-1])
        price = float(closes[-1])

        # Regras simples e objetivas
        prob = 0
        side = None

        # LONG: sobrevenda + toque banda baixa + tendência curta positiva + volume acima média
        if (rsi_val < 30) and (price <= lower) and (ema21 > ema50) and (last_vol > 1.5 * avg_vol):
            prob = 75
            side = "LONG"

        # SHORT: sobrecompra + toque banda alta + tendência curta negativa + volume acima média
        elif (rsi_val > 70) and (price >= upper) and (ema21 < ema50) and (last_vol > 1.5 * avg_vol):
            prob = 75
            side = "SHORT"

        if side and prob >= MIN_PROB:
            # Gestão simples de níveis
            if side == "LONG":
                stop = price * 0.98
                tp1 = price * 1.02
                tp2 = price * 1.04
            else:
                stop = price * 1.02
                tp1 = price * 0.98
                tp2 = price * 0.96

            return {
                "par": symbol,
                "direcao": side,
                "entrada": round(price, 6),
                "stop": round(stop, 6),
                "tp1": round(tp1, 6),
                "tp2": round(tp2, 6),
                "prob": prob,
                "lev": "x5"
            }

        return None

    except Exception as e:
        print(f"[ERRO] {symbol}: {e}")
        return None


# ==========================
# LOOP PRINCIPAL
# ==========================
if __name__ == "__main__":
    # Mensagem de teste no ARRANQUE apenas
    hora = datetime.now().strftime("%d/%m %H:%M")
    send_telegram_message(f"🚀 Bot iniciado - 📌 Alavancagem Curto\n⏱ {hora}")

    while True:
        for pair in PAIRS:
            sinal = analyze_pair(pair)
            if sinal:
                ts = datetime.now().strftime("%d/%m %H:%M")
                msg = (
                    "📌 <b>Alavancagem Curto</b>\n"
                    f"⏱ {ts}\n"
                    f"Par: {sinal['par']}\n"
                    f"Direção: {sinal['direcao']}\n"
                    f"Entrada: {sinal['entrada']}\n"
                    f"Stop: {sinal['stop']}\n"
                    f"TP1: {sinal['tp1']}\n"
                    f"TP2: {sinal['tp2']}\n"
                    f"Probabilidade: {sinal['prob']}%\n"
                    f"Alavancagem: {sinal['lev']}"
                )
                send_telegram_message(msg)

            # pequena pausa entre pares para evitar bursts
            time.sleep(0.2)

        # aguarda próximo ciclo
        time.sleep(SCAN_SECS)
