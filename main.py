import os
import time
import math
import requests
from datetime import datetime
from collections import deque, defaultdict

# ===================== Config =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID   = os.getenv("CHAT_ID", "")
SCAN_SECS = int(os.getenv("SCAN_SECS", "60"))
MIN_PROB  = float(os.getenv("MIN_PROB", "0.65"))  # 0.65 = 65%
BATCH_SIZE = int(os.getenv("SCAN_BATCH", "20"))   # nº de moedas por ciclo (para respeitar limites CG)

CG_BASE = "https://api.coingecko.com/api/v3"

# ===== Lista base do João (CoinGecko IDs) =====
BASE_IDS = [
    "bitcoin","ethereum","solana","ripple","sui","ethena","binancecoin","cardano","dogecoin",
    "chainlink","hedera-hashgraph","stellar","litecoin","avalanche-2","pendle","near","aave",
    "algorand","render-token","lido-dao"
]

# ===== Stablecoins a excluir nos tops =====
STABLE_SYMBOLS = {
    "usdt","usdc","dai","tusd","usde","fdusd","usdd","gusd","lusd","busd","usdp","pyusd","susd","pai","mai","eurs","eurt"
}

# ===== Mapeamento de ID -> “símbolo/USDT” para mostrar de forma familiar =====
# (para o título/alerta usamos o símbolo em maiúsculas + USDT)
FALLBACK_SYMBOL = {}
# (vamos preencher dynamicamente a partir de /coins/markets para os ids que formos usar)

# ===================== Telegram =====================
def tg_send(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("[ERRO] BOT_TOKEN/CHAT_ID não definidos")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True}, timeout=25)
        if r.status_code != 200:
            print("[ERRO TG]", r.text)
            return False
        return True
    except Exception as e:
        print("[ERRO TG]", e)
        return False

# ===================== CoinGecko helpers =====================
def cg_get(path, params=None, tries=3, sleep_sec=1.0):
    url = CG_BASE + path
    for k in range(tries):
        try:
            r = requests.get(url, params=params or {}, timeout=25)
            if r.status_code == 429:
                # rate limit – espera e tenta de novo
                time.sleep(1.5 + k)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if k == tries - 1:
                raise
            time.sleep(sleep_sec + k*0.5)

def fetch_markets_top_nonstable(limit=60):
    """Top por market cap (exclui stablecoins conhecidos). Devolve lista de (id, symbol)."""
    data = cg_get("/coins/markets", {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h"
    })
    out = []
    for it in data:
        sym = it.get("symbol","").lower()
        if sym in STABLE_SYMBOLS:
            continue
        out.append((it["id"], it.get("symbol","").upper()))
    return out

def merge_ids():
    """Une a lista base + top20 non-stable sem duplicar, e atualiza FALLBACK_SYMBOL."""
    markets = fetch_markets_top_nonstable(70)  # folga
    # enche mapping de símbolos
    for cid, sym in markets:
        FALLBACK_SYMBOL[cid] = sym
    # filtra top, tirando os que já estão na base
    base_set = set(BASE_IDS)
    top_only = [cid for (cid, _sym) in markets if cid not in base_set]
    # apanha os primeiros 20
    top_20 = top_only[:20]
    ids = BASE_IDS + top_20
    return ids

def id_to_display_pair(cid: str) -> str:
    sym = FALLBACK_SYMBOL.get(cid, cid.upper()[:5])
    return f"{sym}/USDT"

# ===================== OHLC e indicadores =====================
def cg_ohlc_1d_5m(coin_id: str):
    """
    CoinGecko OHLC (5m) para 1 dia: /coins/{id}/ohlc?vs_currency=usd&days=1
    Retorna lista de dicts: [{open,high,low,close,ts}]
    """
    arr = cg_get(f"/coins/{coin_id}/ohlc", {"vs_currency":"usd","days":"1"})
    out = []
    for row in arr:
        # [timestamp, open, high, low, close]
        out.append({"ts": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4])})
    return out

def resample_to_15m(ohlc5):
    """Agrega 5m -> 15m (3 candles)."""
    out = []
    buf = []
    for k, c in enumerate(ohlc5):
        buf.append(c)
        if len(buf) == 3:
            open_ = buf[0]["open"]
            high_ = max(x["high"] for x in buf)
            low_  = min(x["low"]  for x in buf)
            close_= buf[-1]["close"]
            ts    = buf[-1]["ts"]
            out.append({"ts":ts,"open":open_,"high":high_,"low":low_,"close":close_})
            buf = []
    return out

def ema(vals, p):
    if len(vals) < p: return [None]*len(vals)
    k = 2/(p+1)
    out = [None]*(p-1)
    seed = sum(vals[:p])/p
    out.append(seed)
    for i in range(p, len(vals)):
        out.append(vals[i]k + out[-1](1-k))
    return out

def sma(vals,p):
    out=[]; acc=0.0
    for i,v in enumerate(vals):
        acc += v
        if i >= p: acc -= vals[i-p]
        out.append(None if i+1<p else acc/p)
    return out

def rsi(closes, period=14):
    if len(closes) < period+1: return [None]*len(closes)
    gains=[]; losses=[]
    for i in range(1,len(closes)):
        d = closes[i]-closes[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    def ema_seq(seq,p):
        k=2/(p+1); out=[None]*(p-1); seed=sum(seq[:p])/p; out.append(seed)
        for i in range(p,len(seq)): out.append(seq[i]k + out[-1](1-k))
        return out
    ag=ema_seq(gains,period); al=ema_seq(losses,period)
    out=[None]
    for i in range(1,len(closes)):
        g=ag[i-1] if i-1<len(ag) else None
        l=al[i-1] if i-1<len(al) else None
        if g is None or l is None: out.append(None); continue
        if l==0: out.append(100.0); continue
        rs=g/l; out.append(100 - 100/(1+rs))
    return out

def boll_width(closes, p=20, std=2.0):
    if len(closes)<p: return [None]*len(closes)
    ma=sma(closes,p); out=[]
    for i in range(len(closes)):
        if i+1<p: out.append(None); continue
        m=ma[i]; win=closes[i-p+1:i+1]
        mean=m; var=sum((x-mean)**2 for x in win)/p
        sd=math.sqrt(var)
        up=m+std*sd; lo=m-std*sd
        out.append((up-lo)/(m if m!=0 else 1e-12))
    return out

def recent_high(vals, lb=30):
    return None if len(vals)<lb+1 else max(vals[-(lb+1):-1])

def recent_low(vals, lb=30):
    return None if len(vals)<lb+1 else min(vals[-(lb+1):-1])

def breakout_ok(c,h,l,side,lb=30):
    i=len(c)-1
    if side=="long":
        rh=recent_high(h,lb); return rh is not None and c[i]>rh and c[i]>c[i-1]
    else:
        rl=recent_low(l,lb); return rl is not None and c[i]<rl and c[i]<c[i-1]

def ema_pullback_ok(c,o,h,l,e21,side):
    i=len(c)-1
    if e21[i] is None: return False
    if side=="long":  return (c[i]>o[i]) and (c[i]>e21[i]) and (l[i]<=e21[i])
    else:             return (c[i]<o[i]) and (c[i]<e21[i]) and (h[i]>=e21[i])

def confluence(c,e8,e21,e50,rsiv,bbw):
    i=len(c)-1; sl=0; ss=0
    if e8[i] and e21[i] and e50[i]:
        if e8[i]>e21[i]>e50[i]: sl+=20
        if e8[i]<e21[i]<e50[i]: ss+=20
    if e50[i]:
        if c[i]>e50[i]: sl+=10
        if c[i]<e50[i]: ss+=10
    if rsiv[i] is not None:
        if rsiv[i]>55: sl+=5
        if rsiv[i]<45: ss+=5
    # Bollinger expansão recente (leve)
    if i>=5 and bbw[i] and bbw[i-5]:
        if bbw[i] > bbw[i-5]*1.1:
            sl+=5; ss+=5
    side="long" if sl>=ss else "short"
    raw=max(sl,ss)
    prob=max(0.5, min(0.95, 0.5 + raw/200.0))
    return side, prob

def derive_levels(c,h,l,side):
    i=len(c)-1; price=c[i]
    # ATR simples ~ EMA do TR(14)
    trs=[0.0]
    for k in range(1,len(c)):
        tr=max(h[k]-l[k], abs(h[k]-c[k-1]), abs(l[k]-c[k-1]))
        trs.append(tr)
    k=2/(14+1); atr=trs[1]
    for k2 in range(2,len(trs)):
        atr = trs[k2]k + atr(1-k)
    if side=="long":
        stop=min(l[i-1], price-atr)
        tp1=price+atr; tp2=price+2*atr
    else:
        stop=max(h[i-1], price+atr)
        tp1=price-atr; tp2=price-2*atr
    return round(price,6), round(stop,6), round(tp1,6), round(tp2,6), atr

def suggest_leverage(atr_rel):
    if atr_rel < 0.01: return "x3"
    if atr_rel < 0.02: return "x2"
    return "x1"

def format_signal(display_pair, side, entry, stop, tp1, tp2, prob):
    ts=datetime.now().strftime("%d/%m %H:%M")
    return (
        "📌 <b>Alavancagem Curto</b>\n"
        f"⏱ {ts}\n"
        f"Par: {display_pair}  |  Lado: {side.upper()}  |  TF: 15m\n"
        f"Entrada: {entry}\n"
        f"Stop: {stop}\n"
        f"TP1 / TP2: {tp1} / {tp2}\n"
        f"Probabilidade: {prob*100:.2f}%\n"
        f"Alavancagem: {suggest_leverage((abs(tp1-entry)) / (entry if entry!=0 else 1e-12))}"
    )

# ===================== Scan =====================
class SymbolRotator:
    def _init_(self, ids, batch):
        self.ids = list(ids)
        self.batch = max(1, batch)
        self.q = deque(self.ids)

    def next_batch(self):
        out=[]
        for _ in range(min(self.batch, len(self.q))):
            x=self.q.popleft(); out.append(x); self.q.append(x)
        return out

def analyze_coin_id(coin_id: str):
    try:
        ohlc5 = cg_ohlc_1d_5m(coin_id)
        if len(ohlc5) < 60:  # ~5h de dados 5m
            return None
        ohlc15 = resample_to_15m(ohlc5)
        if len(ohlc15) < 60:
            return None

        o = [x["open"] for x in ohlc15]
        h = [x["high"] for x in ohlc15]
        l = [x["low"]  for x in ohlc15]
        c = [x["close"] for x in ohlc15]

        e8  = ema(c,8); e21 = ema(c,21); e50 = ema(c,50)
        rsiv = rsi(c,14)
        bbw  = boll_width(c,20,2.0)

        side, prob = confluence(c,e8,e21,e50,rsiv,bbw)
        pa_ok = breakout_ok(c,h,l,side,30) or ema_pullback_ok(c,o,h,l,e21,side)
        if not pa_ok or prob < MIN_PROB:
            return None

        entry, stop, tp1, tp2, atr = derive_levels(c,h,l,side)
        display_pair = id_to_display_pair(coin_id)
        return format_signal(display_pair, side, entry, stop, tp1, tp2, prob)

    except Exception as e:
        print(f"[{coin_id}] ERRO", e)
        return None

def main_loop():
    # Mensagem de teste (uma vez)
    ts = datetime.now().strftime("%d/%m %H:%M")
    tg_send(f"🚀 Bot iniciado - 📌 Alavancagem Curto\n⏱ {ts}")

    print("[INFO] A obter lista (base + top20 sem stable)...")
    all_ids = merge_ids()
    print(f"[INFO] Total de moedas monitorizadas: {len(all_ids)}")
    rot = SymbolRotator(all_ids, BATCH_SIZE)

    while True:
        batch = rot.next_batch()
        for cid in batch:
            msg = analyze_coin_id(cid)
            if msg:
                tg_send(msg)
            time.sleep(0.3)  # pequena pausa entre chamadas
        time.sleep(SCAN_SECS)

# ===================== Entry =====================
if _name_ == "_main_":
    try:
        print("[INFO] Usando CoinGecko (sem Binance).")
        main_loop()
    except Exception as e:
        print("[FATAL]", e)
