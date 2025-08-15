import os
import time
import math
import json
import requests
from datetime import datetime, timezone

# ==== Config via variáveis do Railway ====
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
CHAT_ID     = os.getenv("CHAT_ID", "")
SCAN_SECS   = int(os.getenv("SCAN_SECS", "60"))       # frequência do scan (segundos)
MIN_PROB    = float(os.getenv("MIN_PROB", "0.65"))    # prob. mínima (0.65 = 65%)
USE_FUTURES = os.getenv("USE_FUTURES_PRICES", "false").lower() in ("1","true","yes","y","on")

# Lista de símbolos (podes também passar por env SYMBOLS="BTCUSDT,ETHUSDT,...")
SYMBOLS_ENV = os.getenv("SYMBOLS", "")
DEFAULT_SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","SUIUSDT","ENAUSDT","BNBUSDT",
    "ADAUSDT","DOGEUSDT","LINKUSDT","HBARUSDT","XLMUSDT","LTCUSDT","AVAXUSDT",
    "PENDLEUSDT","NEARUSDT","AAVEUSDT","ALGOUSDT","RNDRUSDT","LDOUSDT",
    "BCHUSDT","TONUSDT","UNIUSDT","DOTUSDT","XMRUSDT","TRXUSDT"
]
SYMBOLS = [s.strip().upper() for s in SYMBOLS_ENV.split(",") if s.strip()] or DEFAULT_SYMBOLS

ENTRY_TFS   = ["5m","15m","30m","1h"]  # timeframes de entrada
CONTEXT_TF  = "4h"                     # apenas contexto (trend/gate BTC)
LOOKBACK    = 200                      # candles puxados por TF

# ==== Endpoints Binance (públicos) ====
SPOT_BASE    = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"

def binance_klines(symbol: str, interval: str, limit: int = 500, futures: bool = False):
    base = FUTURES_BASE if futures else SPOT_BASE
    path = "/fapi/v1/klines" if futures else "/api/v3/klines"
    url = base + path
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}, timeout=20)
    r.raise_for_status()
    raw = r.json()
    # columns: [open_time, open, high, low, close, volume, close_time, ...]
    candles = []
    for row in raw:
        candles.append({
            "open_time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": int(row[6]),
        })
    return candles

# ==== Indicadores (sem pandas) ====
def ema(values, period):
    if not values or len(values) < period:
        return [None]*len(values)
    k = 2/(period+1)
    out = [None]*(period-1)
    # seed = SMA period
    seed = sum(values[:period]) / period
    out.append(seed)
    for i in range(period, len(values)):
        prev = out[-1]
        out.append(values[i]*k + prev*(1-k))
    return out

def sma(values, period):
    out = []
    acc = 0.0
    for i,v in enumerate(values):
        acc += v
        if i >= period:
            acc -= values[i-period]
        out.append(None if i+1<period else acc/period)
    return out

def rsi(values, period=14):
    if len(values) < period+1:
        return [None]*len(values)
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    # EMA dos ganhos/perdas
    def ema_seq(seq, p):
        k = 2/(p+1)
        out = [None]*(p-1)
        seed = sum(seq[:p]) / p
        out.append(seed)
        for i in range(p, len(seq)):
            out.append(seq[i]*k + out[-1]*(1-k))
        return out
    avg_gain = ema_seq(gains, period)
    avg_loss = ema_seq(losses, period)
    rsiv = [None]
    for i in range(1, len(values)):
        g = avg_gain[i-1] if i-1 < len(avg_gain) else None
        l = avg_loss[i-1] if i-1 < len(avg_loss) else None
        if g is None or l is None or l == 0:
            rsiv.append(None if l is None else 100.0)
        else:
            rs = g / (l if l != 0 else 1e-12)
            rsiv.append(100 - 100/(1+rs))
    return rsiv

def atr(high, low, close, period=14):
    if len(close) < period+1:
        return [None]*len(close)
    trs = [None]
    for i in range(1, len(close)):
        tr = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
        trs.append(tr)
    # EMA do TR
    return ema(trs[1:], period) + [None]  # alinhamento simples

def bollinger_width(values, period=20, std=2.0):
    # devolve width normalizada ( (up-low)/MA ), útil para ver expansão/contração
    if len(values) < period:
        return [None]*len(values)
    ma = sma(values, period)
    out = []
    for i in range(len(values)):
        if i+1 < period:
            out.append(None)
        else:
            m = ma[i]
            # std manual
            window = values[i-period+1:i+1]
            mean = m
            var = sum((x-mean)**2 for x in window)/period
            sd  = math.sqrt(var)
            up, lo = m + std*sd, m - std*sd
            width = (up - lo) / (m if m != 0 else 1e-12)
            out.append(width)
    return out

# ==== Scoring e Price Action ====
def recent_high(values, lookback=30):
    if len(values) < lookback+1: return None
    return max(values[-(lookback+1):-1])

def recent_low(values, lookback=30):
    if len(values) < lookback+1: return None
    return min(values[-(lookback+1):-1])

def confluence_score(c, ema8v, ema21v, ema50v, rsiv, bbw, vol, lookback=30):
    i = len(c)-1
    score_long = 0.0
    score_short = 0.0
    reasons_long, reasons_short = [], []

    # EMAs alinhadas
    if ema8v[i] and ema21v[i] and ema50v[i]:
        if ema8v[i] > ema21v[i] > ema50v[i]:
            score_long += 20; reasons_long.append("EMAs 8>21>50")
        if ema8v[i] < ema21v[i] < ema50v[i]:
            score_short += 20; reasons_short.append("EMAs 8<21<50")

    # Preço vs EMA50
    if ema50v[i]:
        if c[i] > ema50v[i]: score_long += 10
        if c[i] < ema50v[i]: score_short += 10

    # RSI
    if rsiv[i] is not None:
        if rsiv[i] > 55: score_long += 5
        if rsiv[i] < 45: score_short += 5

    # Candle de força
    # (close > open para long; close < open para short)
    # isto entra na verificação de PA

    # Bollinger expansão recente
    if i >= 5 and bbww := bbwpct(bbw, i):
        # se houve expansão, favorece setups de momentum
        score_long += 5; score_short += 5

    # Volume relativo (aproximação: último vs média dos 20 anteriores)
    if len(vol) >= 21:
        vmean = sum(vol[-21:-1])/20
        if vmean > 0:
            if vol[i] > 1.5*vmean and c[i] > c[i-1]:
                score_long += 10
            if vol[i] > 1.5*vmean and c[i] < c[i-1]:
                score_short += 10

    # Lado dominante
    side = "long" if score_long >= score_short else "short"
    raw  = max(score_long, score_short)
    # prob entre 0.5 e 0.95
    prob = max(0.5, min(0.95, 0.5 + raw/200.0))
    reasons = reasons_long if side == "long" else reasons_short
    return side, prob, reasons

def bbwpct(bbw, i):
    if i < 5 or bbw[i] is None or bbw[i-5] is None: return None
    return (bbw[i] / (bbw[i-5] if bbw[i-5]!=0 else 1e-12)) - 1.0

def ema_pullback_ok(c, o, h, l, ema21v, side):
    i = len(c)-1
    if ema21v[i] is None: return False
    if side == "long":
        return (c[i] > o[i]) and (c[i] > ema21v[i]) and (l[i] <= ema21v[i])
    else:
        return (c[i] < o[i]) and (c[i] < ema21v[i]) and (h[i] >= ema21v[i])

def breakout_ok(c, hvals, lvals, side, lookback=30):
    i = len(c)-1
    if side == "long":
        rh = recent_high(hvals, lookback)
        return (rh is not None) and (c[i] > rh) and (c[i] > c[i-1])
    else:
        rl = recent_low(lvals, lookback)
        return (rl is not None) and (c[i] < rl) and (c[i] < c[i-1])

def btc_gate_allows(side):
    """Gatilho BTC 15m: EMA8 vs EMA21 + candle da última barra."""
    try:
        btc = binance_klines("BTCUSDT", "15m", limit=LOOKBACK, futures=False)
        c = [x["close"] for x in btc]
        o = [x["open"] for x in btc]
        e8  = ema(c, 8)
        e21 = ema(c, 21)
        i = len(c)-1
        if e8[i] is None or e21[i] is None: return True
        up = (e8[i] > e21[i]) and (c[i] > o[i])
        dn = (e8[i] < e21[i]) and (c[i] < o[i])
        return (side == "long" and up) or (side == "short" and dn)
    except Exception:
        return True  # se falhar, não bloqueia

def true_range_series(h, l, c):
    trs = [0.0]
    for i in range(1, len(c)):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        trs.append(tr)
    return trs

def ema_list(values, period):
    if not values: return []
    k = 2/(period+1)
    out = []
    prev = values[0]
    out.append(prev)
    for i in range(1, len(values)):
        prev = values[i]*k + prev*(1-k)
        out.append(prev)
    return out

def derive_levels(c, h, l, side):
    """STOP/TP via ATR(14) ~ 1R e 2R a partir do preço atual."""
    i = len(c)-1
    price = c[i]
    trs = true_range_series(h, l, c)
    atr14 = ema_list(trs, 14)[i]
    if side == "long":
        stop = min(l[i-1], price - atr14)
        tp1  = price + atr14
        tp2  = price + 2*atr14
    else:
        stop = max(h[i-1], price + atr14)
        tp1  = price - atr14
        tp2  = price - 2*atr14
    return round(price,6), round(stop,6), round(tp1,6), round(tp2,6), atr14

def suggest_leverage(atr_rel):
    # atr_rel ~ ATR / preço: se baixo -> mais alavancagem
    if atr_rel < 0.01: return 3
    if atr_rel < 0.02: return 2
    return 1

# ==== Telegram ====
def tg_send(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("[ERRO] BOT_TOKEN/CHAT_ID não definidos.")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=20)
        ok = (r.status_code == 200)
        if not ok:
            print("[ERRO TG]", r.text)
        return ok
    except Exception as e:
        print("[ERRO TG]", e)
        return False

def format_signal(symbol, tf, side, entry, stop, tp1, tp2, prob_pct, lev):
    return (
        "📌 Alavancagem Curto\n\n"
        f"• Par: {symbol}  |  Lado: {side.upper()}  |  TF: {tf}\n"
        f"• Entrada: {entry}\n"
        f"• Stop: {stop}\n"
        f"• TP1 / TP2: {tp1}  /  {tp2}\n"
        f"• % de acerto (estimada): {prob_pct:.2f}%\n"
        f"• Alavancagem sugerida: {lev}x\n"
    )

# ==== Loop principal ====
def scan_once():
    # Mensagem de arranque na 1ª execução é enviada no main()
    for symbol in SYMBOLS:
        for tf in ENTRY_TFS:
            try:
                kl = binance_klines(symbol, tf, limit=LOOKBACK, futures=USE_FUTURES)
            except Exception as e:
                print(f"[{symbol} {tf}] ERRO download: {e}")
                continue
            if len(kl) < 60:
                continue

            o = [x["open"] for x in kl]
            h = [x["high"] for x in kl]
            l = [x["low"]  for x in kl]
            c = [x["close"] for x in kl]
            v = [x["volume"] for x in kl]
            i = len(c)-1

            e8  = ema(c, 8)
            e21 = ema(c, 21)
            e50 = ema(c, 50)
            rsiv = rsi(c, 14)
            bbw  = bollinger_width(c, 20, 2.0)

            side, prob, reasons = confluence_score(c, e8, e21, e50, rsiv, bbw, v, lookback=30)

            # Price Action: breakout/breakdown OU pullback à EMA21 no lado escolhido
            pa_ok = breakout_ok(c, h, l, side, 30) or ema_pullback_ok(c, o, h, l, e21, side)
            if not pa_ok:
                continue

            # Gate do BTC (micro-tendência 15m)
            if symbol != "BTCUSDT" and not btc_gate_allows(side):
                continue

            if prob < MIN_PROB:
                continue

            # Níveis
            entry, stop, tp1, tp2, atr_now = derive_levels(c, h, l, side)
            atr_rel = atr_now / (entry if entry != 0 else 1e-12)
            lev = suggest_leverage(atr_rel)
            prob_pct = prob * 100.0

            msg = format_signal(symbol, tf, side, entry, stop, tp1, tp2, prob_pct, lev)
            ok = tg_send(msg)
            print(f"[ALERT] {symbol} {side} {tf} prob={prob_pct:.2f}% -> {'sent' if ok else 'fail'}")

def main():
    # Teste de arranque
    tg_send("✅ Bot ativo - teste de envio")

    print(f"[INFO] Símbolos monitorizados: {len(SYMBOLS)} | TFs: {','.join(ENTRY_TFS)} | Scan cada {SCAN_SECS}s")
    while True:
        try:
            scan_once()
        except Exception as e:
            print("[ERROR loop]", e)
        time.sleep(SCAN_SECS)

if __name__ == "__main__":
    main()
