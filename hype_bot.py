#!/usr/bin/env python3
"""
HYPE AI Trading Bot v8.1
Sistema 4 etapas + señales cada 4H + datos reales KuCoin
Niveles actualizados: 27 Jul 2026
"""

import os
import json
import time
import logging
import requests
from telegram import ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN    = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("CHAT_ID", "7384387442"))
GROUP_ID = int(os.getenv("GROUP_ID", "-1004385044274"))
DATA_FILE = "bot_trading.json"

NIVELES = {
    "entrada":           0,
    "stop_loss":         0,
    "soporte_clave":     59.500,
    "soporte2":          57.000,
    "target1":           64.788,
    "target2":           70.721,
    "target3":           75.539,
    "resistencia_h4":    64.788,
    "resistencia2":      70.721,
    "soporte_diario":    53.000,
    "objetivo_bajista":  53.000,
    "operacion_activa":  False,
    "tipo":              "LONG",
}

state = {
    "prices":      [],
    "ema_fast":    None,
    "ema_slow":    None,
    "swings_high": [],
    "swings_low":  [],
    "volumenes":   [],
}

def load_state():
    global state, NIVELES
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                state.update(data.get("state", {}))
                NIVELES.update(data.get("niveles", {}))
        except: pass

def save_state():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({"state": state, "niveles": NIVELES}, f)
    except: pass

# ══════════════════════════════════════════
#  DATOS REALES — KUCOIN
# ══════════════════════════════════════════

def get_stats(symbol):
    try:
        r = requests.get(f"https://api.kucoin.com/api/v1/market/stats?symbol={symbol}", timeout=10)
        return r.json().get("data")
    except: return None

def get_price(symbol):
    try:
        r = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={symbol}", timeout=10)
        return float(r.json()["data"]["price"])
    except: return None

def get_klines(symbol, intervalo="4hour", limit=60):
    end = int(time.time())
    segs = {"15min": 900, "1hour": 3600, "4hour": 14400, "1day": 86400}
    start = end - segs.get(intervalo, 14400) * limit
    try:
        r = requests.get("https://api.kucoin.com/api/v1/market/candles",
            params={"symbol": symbol, "type": intervalo, "startAt": start, "endAt": end}, timeout=10)
        data = r.json()["data"]
        return {
            "cierres":   [float(k[2]) for k in reversed(data)],
            "altos":     [float(k[3]) for k in reversed(data)],
            "bajos":     [float(k[4]) for k in reversed(data)],
            "volumenes": [float(k[5]) for k in reversed(data)],
        }
    except: return {"cierres": [], "altos": [], "bajos": [], "volumenes": []}

def get_rsi(cierres, periodo=14):
    try:
        if len(cierres) < periodo + 1: return None
        g, p = [], []
        for i in range(1, len(cierres)):
            d = cierres[i] - cierres[i-1]
            g.append(d if d > 0 else 0)
            p.append(abs(d) if d < 0 else 0)
        ag = sum(g[-periodo:]) / periodo
        ap = sum(p[-periodo:]) / periodo
        if ap == 0: return 100.0
        return round(100 - (100 / (1 + ag/ap)), 2)
    except: return None

def get_macd(cierres):
    try:
        if len(cierres) < 35: return None, None, None
        def ema(p, n):
            k = 2/(n+1); e = [p[0]]
            for x in p[1:]: e.append(x*k + e[-1]*(1-k))
            return e
        e12 = ema(cierres, 12); e26 = ema(cierres, 26)
        macd = [m-n for m,n in zip(e12, e26)]
        sig = ema(macd[25:], 9)
        return round(macd[-1],4), round(sig[-1],4), round(macd[-1]-sig[-1],4)
    except: return None, None, None

def update_indicators(price, volumenes=[]):
    state["prices"].append(price)
    if len(state["prices"]) > 200:
        state["prices"] = state["prices"][-200:]
    sma50 = sum(state["prices"][-50:]) / min(len(state["prices"]), 50)
    af = 0.2
    state["ema_fast"] = price if state["ema_fast"] is None else af*price + (1-af)*state["ema_fast"]
    as_ = 0.1
    state["ema_slow"] = price if state["ema_slow"] is None else as_*price + (1-as_)*state["ema_slow"]
    if volumenes:
        state["volumenes"] = volumenes[-20:]
    detect_swings(); save_state()
    return sma50, state["ema_fast"], state["ema_slow"]

def detect_swings():
    prices = state["prices"]
    if len(prices) < 3: return
    i = len(prices) - 2
    p0, p1, p2 = prices[i-1], prices[i], prices[i+1] if i+1 < len(prices) else prices[i]
    if p0 < p1 > p2:
        state["swings_high"].append(p1); state["swings_high"] = state["swings_high"][-5:]
    if p0 > p1 < p2:
        state["swings_low"].append(p1); state["swings_low"] = state["swings_low"][-5:]

def barra(pct, largo=10):
    llenos = round(max(0, min(100, pct)) / 100 * largo)
    return "█" * llenos + "░" * (largo - llenos)

def emoji_score(score):
    if score >= 65: return "🟢"
    if score >= 45: return "🟡"
    return "🔴"

# ══════════════════════════════════════════
#  SISTEMA 4 ETAPAS
# ══════════════════════════════════════════

def etapa1_contexto(btc_s, eth_s, hype_4h):
    score = 50; razones = []
    btc_c = float(btc_s["changeRate"]) if btc_s else 0
    eth_c = float(eth_s["changeRate"]) if eth_s else 0

    if btc_c > 1:    score += 20; razones.append("BTC fuerte ✅")
    elif btc_c > 0:  score += 10; razones.append("BTC positivo ✅")
    elif btc_c < -1: score -= 20; razones.append("BTC bajista ❌")
    else:            razones.append("BTC neutral ⚠️")

    if eth_c > 1:    score += 15; razones.append("ETH fuerte ✅")
    elif eth_c > 0:  score += 8;  razones.append("ETH positivo ✅")
    elif eth_c < -1: score -= 15; razones.append("ETH bajista ❌")
    else:            razones.append("ETH neutral ⚠️")

    cierres = hype_4h.get("cierres", [])
    if len(cierres) >= 5:
        if cierres[-1] > cierres[-5]:
            score += 15; razones.append("Tendencia 4H alcista ✅")
        else:
            score -= 15; razones.append("Tendencia 4H bajista ❌")

    return max(10, min(90, score)), razones

def etapa2_estructura(price, hype_4h):
    score = 50; razones = []
    altos = hype_4h.get("altos", [])
    bajos = hype_4h.get("bajos", [])

    if len(bajos) >= 5:
        if bajos[-1] > bajos[-3]:
            score += 20; razones.append("Mínimos crecientes ✅")
        else:
            score -= 20; razones.append("Mínimos decrecientes ❌")

    if len(altos) >= 4:
        if altos[-1] > altos[-3]:
            score += 15; razones.append("Máximos crecientes ✅")
        else:
            score -= 10; razones.append("Máximos decrecientes ❌")

    if price > NIVELES["soporte_clave"]:
        score += 10; razones.append(f"Sobre soporte ${NIVELES['soporte_clave']} ✅")
    else:
        score -= 15; razones.append(f"Bajo soporte ${NIVELES['soporte_clave']} ❌")

    if price > NIVELES["soporte2"]:
        score += 5; razones.append(f"Sobre soporte $57.00 ✅")
    else:
        score -= 20; razones.append(f"Bajo soporte $57.00 ❌")

    if price < NIVELES["resistencia_h4"]:
        razones.append(f"Bajo resistencia ${NIVELES['resistencia_h4']} ⚠️")
    else:
        score += 15; razones.append(f"Ruptura resistencia ${NIVELES['resistencia_h4']} ✅")

    return max(10, min(90, score)), razones

def etapa3_confirmacion(cierres_4h, cierres_1h, volumenes):
    score = 30; razones = []

    rsi_4h = get_rsi(cierres_4h)
    rsi_1h = get_rsi(cierres_1h)
    _, _, macd_hist = get_macd(cierres_1h)

    if rsi_4h:
        if rsi_4h < 30:   score += 30; razones.append(f"RSI 4H sobrevendido ({rsi_4h}) ✅")
        elif rsi_4h < 40: score += 20; razones.append(f"RSI 4H bajo ({rsi_4h}) ✅")
        elif rsi_4h < 50: score += 10; razones.append(f"RSI 4H neutral-bajo ({rsi_4h}) ⚠️")
        elif rsi_4h > 70: score -= 20; razones.append(f"RSI 4H sobrecomprado ({rsi_4h}) ❌")
        else:             razones.append(f"RSI 4H neutral ({rsi_4h}) ⚠️")

    if rsi_1h:
        if rsi_1h < 35:   score += 15; razones.append(f"RSI 1H sobrevendido ({rsi_1h}) ✅")
        elif rsi_1h < 45: score += 8;  razones.append(f"RSI 1H bajo ({rsi_1h}) ✅")
        elif rsi_1h > 65: score -= 10; razones.append(f"RSI 1H alto ({rsi_1h}) ❌")
        else:             razones.append(f"RSI 1H neutral ({rsi_1h}) ⚠️")

    if macd_hist is not None:
        if macd_hist > 0:   score += 20; razones.append("MACD 1H alcista ✅")
        elif macd_hist < 0: score -= 10; razones.append("MACD 1H bajista ❌")

    if len(volumenes) >= 5:
        vol_avg = sum(volumenes[-5:]) / 5
        vol_actual = volumenes[-1] if volumenes else 0
        if vol_actual > vol_avg * 1.3:
            score += 10; razones.append("Volumen elevado ✅")
        elif vol_actual < vol_avg * 0.7:
            razones.append("Volumen bajo ⚠️")

    return max(10, min(90, score)), razones, rsi_4h, rsi_1h, macd_hist

def etapa4_gestion(price):
    score = 0; razones = []; rr = 0

    if not NIVELES["operacion_activa"] or NIVELES["entrada"] == 0:
        razones.append("Sin operación activa ⚪")
        razones.append("Usa /setnivel para configurar")
        return 0, razones, 0

    entrada = NIVELES["entrada"]
    sl = NIVELES["stop_loss"]
    tp1 = NIVELES["target1"]

    if sl > 0: score += 30; razones.append(f"SL configurado: ${sl} ✅")
    if tp1 > 0: score += 30; razones.append(f"TP1 configurado: ${tp1} ✅")

    if sl > 0 and tp1 > 0 and entrada > 0:
        riesgo = abs(entrada - sl)
        beneficio = abs(tp1 - entrada)
        if riesgo > 0:
            rr = round(beneficio / riesgo, 2)
            if rr >= 2:     score += 40; razones.append(f"R/B excelente 1:{rr} ✅")
            elif rr >= 1.5: score += 20; razones.append(f"R/B aceptable 1:{rr} ⚠️")
            else:           razones.append(f"R/B bajo 1:{rr} ❌")

    return max(0, min(100, score)), razones, rr

# ══════════════════════════════════════════
#  ANÁLISIS PRINCIPAL
# ══════════════════════════════════════════

def analisis_completo(version="completa"):
    price = get_price("HYPE-USDT")
    if not price:
        return "🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\n⚪ SIN DATOS DE MERCADO\n━━━━━━━━━━━━━━━━━━"

    hype_4h = get_klines("HYPE-USDT", "4hour", 60)
    hype_1h = get_klines("HYPE-USDT", "1hour", 30)
    btc_s   = get_stats("BTC-USDT")
    eth_s   = get_stats("ETH-USDT")
    hype_s  = get_stats("HYPE-USDT")

    cierres_4h = hype_4h.get("cierres", [])
    cierres_1h = hype_1h.get("cierres", [])
    volumenes  = hype_4h.get("volumenes", [])

    sma50, ema_fast, ema_slow = update_indicators(price, volumenes)

    e1_score, e1_r = etapa1_contexto(btc_s, eth_s, hype_4h)
    e2_score, e2_r = etapa2_estructura(price, hype_4h)
    e3_score, e3_r, rsi_4h, rsi_1h, macd_hist = etapa3_confirmacion(cierres_4h, cierres_1h, volumenes)
    e4_score, e4_r, rr = etapa4_gestion(price)

    if NIVELES["operacion_activa"]:
        score_final = round(e1_score*0.40 + e2_score*0.30 + e3_score*0.20 + e4_score*0.10)
    else:
        score_final = round(e1_score*0.40 + e2_score*0.35 + e3_score*0.25)

    if score_final >= 68:   decision = "🟢 ENTRAR LONG"
    elif score_final >= 60: decision = "🟡 PREPARAR LONG"
    elif score_final <= 32: decision = "🔴 CONSIDERAR SHORT"
    elif score_final <= 40: decision = "🟡 PREPARAR SHORT"
    else:                   decision = "⏳ ESPERAR"

    hype_c = float(hype_s["changeRate"]) if hype_s else 0
    btc_c  = float(btc_s["changeRate"]) if btc_s else 0
    eth_c  = float(eth_s["changeRate"]) if eth_s else 0

    if version == "grupo":
        return (
            f"🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\n"
            f"💰 HYPE: ${price:.3f} ({hype_c:+.2f}%)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🌍 Contexto     {barra(e1_score)} {e1_score}%\n"
            f"🏗️ Estructura   {barra(e2_score)} {e2_score}%\n"
            f"✅ Confirmación {barra(e3_score)} {e3_score}%\n"
            f"🛡️ Gestión      {barra(e4_score)} {e4_score}%\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Setup: {barra(score_final)} {score_final}%\n"
            f"{decision}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 RSI 4H: {rsi_4h} | RSI 1H: {rsi_1h}\n"
            f"📈 MACD hist: {macd_hist}\n"
            f"🌍 BTC: {btc_c:+.2f}% | ETH: {eth_c:+.2f}%\n"
            f"⚠️ Solo informativo"
        )

    msg = (
        f"🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 HYPE: ${price:.3f} ({hype_c:+.2f}%)\n"
        f"📊 Datos en tiempo real — KuCoin\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌍 CONTEXTO {emoji_score(e1_score)} {e1_score}%\n{barra(e1_score)}\n"
    )
    for r in e1_r: msg += f"• {r}\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n🏗️ ESTRUCTURA {emoji_score(e2_score)} {e2_score}%\n{barra(e2_score)}\n"
    for r in e2_r: msg += f"• {r}\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n✅ CONFIRMACIÓN {emoji_score(e3_score)} {e3_score}%\n{barra(e3_score)}\n"
    for r in e3_r: msg += f"• {r}\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n🛡️ GESTIÓN {emoji_score(e4_score)} {e4_score}%\n{barra(e4_score)}\n"
    for r in e4_r: msg += f"• {r}\n"
    msg += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 PROBABILIDAD DEL SETUP\n"
        f"{barra(score_final, 12)} {score_final}%\n\n"
        f"{decision}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI 4H: {rsi_4h} | RSI 1H: {rsi_1h}\n"
        f"📈 MACD 1H hist: {macd_hist}\n"
        f"📊 SMA50: {sma50:.3f} | EMA: {ema_fast:.3f}\n"
        f"🌍 BTC: {btc_c:+.2f}% | ETH: {eth_c:+.2f}%\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 Niveles clave:\n"
        f"🟢 Soporte 1: ${NIVELES['soporte_clave']}\n"
        f"🟢 Soporte 2: ${NIVELES['soporte2']}\n"
        f"🔴 Resistencia: ${NIVELES['resistencia_h4']}\n"
        f"🔴 Resistencia 2: ${NIVELES['resistencia2']}\n"
        f"🎯 Objetivo bajista: ${NIVELES['objetivo_bajista']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Datos reales KuCoin. Usa tu criterio."
    )
    return msg

# ══════════════════════════════════════════
#  BOTONES
# ══════════════════════════════════════════

def private_keyboard():
    return ReplyKeyboardMarkup([
        ["📊 Análisis completo", "🎯 Setup ahora"],
        ["₿ BTC", "Ξ ETH"],
        ["📍 Niveles", "⚙️ Mi operación"],
        ["▶ Activar alerta 4H", "⏹ Detener alerta"]
    ], resize_keyboard=True)

def group_keyboard():
    return ReplyKeyboardMarkup([
        ["📊 Análisis HYPE", "💰 Precio HYPE"],
        ["▶ Activar alerta", "⏹ Detener alerta"]
    ], resize_keyboard=True)

# ══════════════════════════════════════════
#  COMANDOS
# ══════════════════════════════════════════

def is_owner(update):
    return update.effective_user.id == OWNER_ID

async def cmd_start(update, context):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if uid == OWNER_ID:
        await update.message.reply_text(
            "🤖 HYPE AI Bot v8.1\n━━━━━━━━━━━━━━━━━━\n"
            "Sistema 4 etapas activo ✅\n"
            "Datos reales KuCoin ✅\n"
            "Alertas cada 4H ✅\n\n"
            "📋 COMANDOS:\n"
            "/senal — Análisis completo\n"
            "/niveles — Ver niveles\n"
            "/setnivel — Actualizar nivel\n"
            "/operacion — Ver mi operación\n"
            "/btc — Análisis BTC\n"
            "/eth — Análisis ETH\n"
            "/alertamercado — Alertas 4H\n"
            "/stopalerta — Detener alertas\n"
            "/ping — Test conexión\n"
            "━━━━━━━━━━━━━━━━━━",
            reply_markup=private_keyboard()
        )
    elif cid == GROUP_ID:
        await update.message.reply_text(
            "🤖 HYPE AI Bot v8.1 activo\nDatos reales KuCoin ✅",
            reply_markup=group_keyboard()
        )

async def cmd_ping(update, context):
    price = get_price("HYPE-USDT")
    await update.message.reply_text(
        f"🟢 Bot v8.1 funcionando\n💰 HYPE: ${price:.3f}" if price else "🟢 Bot activo"
    )

async def cmd_senal(update, context):
    if not is_owner(update): return
    await update.message.reply_text("🔍 Analizando 4 etapas con datos reales...")
    await update.message.reply_text(analisis_completo("completa"))

async def cmd_niveles(update, context):
    if not is_owner(update): return
    op = "✅ Activa" if NIVELES["operacion_activa"] else "⚪ Sin operación"
    await update.message.reply_text(
        f"🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\n"
        f"📍 Niveles activos\n"
        f"Estado: {op} ({NIVELES['tipo']})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Entrada: ${NIVELES['entrada']}\n"
        f"🛑 SL: ${NIVELES['stop_loss']}\n"
        f"🟢 Soporte 1: ${NIVELES['soporte_clave']}\n"
        f"🟢 Soporte 2: ${NIVELES['soporte2']}\n"
        f"🎯 T1: ${NIVELES['target1']}\n"
        f"🎯 T2: ${NIVELES['target2']}\n"
        f"🎯 T3: ${NIVELES['target3']}\n"
        f"🔴 Resistencia H4: ${NIVELES['resistencia_h4']}\n"
        f"🔴 Resistencia 2: ${NIVELES['resistencia2']}\n"
        f"🎯 Objetivo bajista: ${NIVELES['objetivo_bajista']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Para actualizar:\n"
        f"/setnivel entrada 60.50\n"
        f"/setnivel stop_loss 58.00\n"
        f"/setnivel target1 64.79\n"
        f"/setnivel activa si"
    )

async def cmd_setnivel(update, context):
    if not is_owner(update): return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📋 Uso: /setnivel [campo] [valor]\n\n"
            "Campos:\n"
            "• entrada\n• stop_loss\n"
            "• soporte_clave\n• soporte2\n"
            "• target1\n• target2\n• target3\n"
            "• resistencia_h4\n• resistencia2\n"
            "• objetivo_bajista\n• soporte_diario\n"
            "• tipo → LONG o SHORT\n"
            "• activa → si o no\n\n"
            "Ejemplos:\n"
            "/setnivel entrada 60.50\n"
            "/setnivel stop_loss 58.00\n"
            "/setnivel activa si\n"
            "/setnivel tipo LONG"
        )
        return

    campo = args[0].lower()
    valor = args[1]

    if campo == "tipo":
        NIVELES["tipo"] = "LONG" if "long" in valor.lower() else "SHORT"
        save_state()
        await update.message.reply_text(f"✅ Tipo: {NIVELES['tipo']}")
    elif campo == "activa":
        NIVELES["operacion_activa"] = valor.lower() in ["si", "sí", "yes", "true", "1"]
        save_state()
        estado = "activada ✅" if NIVELES["operacion_activa"] else "desactivada ⚪"
        await update.message.reply_text(f"Operación {estado}")
    elif campo in NIVELES:
        try:
            NIVELES[campo] = float(valor)
            save_state()
            await update.message.reply_text(f"✅ {campo}: ${NIVELES[campo]}")
        except:
            await update.message.reply_text("❌ Valor inválido — debe ser número")
    else:
        await update.message.reply_text(f"❌ Campo '{campo}' no reconocido")

async def cmd_operacion(update, context):
    if not is_owner(update): return
    price = get_price("HYPE-USDT")

    if not NIVELES["operacion_activa"] or NIVELES["entrada"] == 0:
        await update.message.reply_text(
            "🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\n"
            "⚪ Sin operación activa\n\n"
            "Para configurar:\n"
            "/setnivel activa si\n"
            "/setnivel entrada 60.50\n"
            "/setnivel stop_loss 58.00\n"
            "/setnivel target1 64.79\n"
            "/setnivel tipo LONG"
        )
        return

    entrada = NIVELES["entrada"]
    sl = NIVELES["stop_loss"]
    tp1 = NIVELES["target1"]
    tp2 = NIVELES["target2"]
    tipo = NIVELES["tipo"]

    if price and entrada > 0:
        pnl = ((price - entrada) / entrada * 100 * 20) if tipo == "LONG" else ((entrada - price) / entrada * 100 * 20)
        emoji_pnl = "📈" if pnl > 0 else "📉"
        dist_sl  = round(abs(entrada - sl) / entrada * 100, 2) if sl > 0 else 0
        dist_tp1 = round(abs(tp1 - price) / price * 100, 2) if tp1 > 0 else 0

        await update.message.reply_text(
            f"🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ Mi operación — {tipo}\n━━━━━━━━━━━━━━━━━━\n"
            f"💰 Entrada: ${entrada}\n"
            f"📍 Precio actual: ${price:.3f}\n"
            f"{emoji_pnl} P&L estimado (20x): {pnl:+.1f}%\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛑 SL: ${sl} ({dist_sl}% riesgo)\n"
            f"🎯 T1: ${tp1} ({dist_tp1}% al objetivo)\n"
            f"🎯 T2: ${tp2}\n"
            f"🎯 T3: ${NIVELES['target3']}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

async def cmd_btc(update, context):
    if not is_owner(update): return
    d = get_stats("BTC-USDT")
    if not d: await update.message.reply_text("⚪ SIN DATOS BTC"); return
    klines = get_klines("BTC-USDT", "4hour", 40)
    rsi = get_rsi(klines.get("cierres", []))
    _, _, macd = get_macd(klines.get("cierres", []))
    await update.message.reply_text(
        f"🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\n₿ BTC / USDT\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio: ${float(d['last']):,.2f}\n"
        f"📈 Cambio 24h: {float(d['changeRate']):+.4f}%\n"
        f"🔼 Máx: ${float(d['high']):,.2f}\n"
        f"🔽 Mín: ${float(d['low']):,.2f}\n"
        f"📊 RSI 4H: {rsi}\n"
        f"📈 MACD hist: {macd}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

async def cmd_eth(update, context):
    if not is_owner(update): return
    d = get_stats("ETH-USDT")
    if not d: await update.message.reply_text("⚪ SIN DATOS ETH"); return
    klines = get_klines("ETH-USDT", "4hour", 40)
    rsi = get_rsi(klines.get("cierres", []))
    _, _, macd = get_macd(klines.get("cierres", []))
    await update.message.reply_text(
        f"🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\nΞ ETH / USDT\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio: ${float(d['last']):,.2f}\n"
        f"📈 Cambio 24h: {float(d['changeRate']):+.4f}%\n"
        f"🔼 Máx: ${float(d['high']):,.2f}\n"
        f"🔽 Mín: ${float(d['low']):,.2f}\n"
        f"📊 RSI 4H: {rsi}\n"
        f"📈 MACD hist: {macd}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

# ══════════════════════════════════════════
#  ALERTAS CADA 4 HORAS
# ══════════════════════════════════════════

async def send_alerts(context):
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=analisis_completo("completa"))
    except Exception as e:
        print(f"[ERROR privado] {e}")
    try:
        await context.bot.send_message(chat_id=GROUP_ID, text=analisis_completo("grupo"))
    except Exception as e:
        print(f"[ERROR grupo] {e}")

async def cmd_alerta(update, context):
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if cid == GROUP_ID:
        admins = [m.user.id for m in await context.bot.get_chat_administrators(GROUP_ID)]
        if uid not in admins:
            await update.message.reply_text("Solo administradores pueden activar alertas.")
            return
    elif uid != OWNER_ID:
        return

    jobs = context.job_queue.get_jobs_by_name("alertas_4h")
    for job in jobs: job.schedule_removal()
    context.job_queue.run_repeating(send_alerts, interval=14400, first=10, name="alertas_4h")
    await update.message.reply_text(
        "🤖 HYPE AI BOT v8.1\n━━━━━━━━━━━━━━━━━━\n"
        "✅ Alertas 4H activadas\n"
        "⏱ Análisis al cierre de cada vela 4H\n"
        "📊 Datos reales KuCoin\n"
        "━━━━━━━━━━━━━━━━━━"
    )

async def cmd_stopalerta(update, context):
    jobs = context.job_queue.get_jobs_by_name("alertas_4h")
    for job in jobs: job.schedule_removal()
    await update.message.reply_text("⏹ Alertas detenidas.")

# ══════════════════════════════════════════
#  MENSAJES DE TEXTO
# ══════════════════════════════════════════

async def handle_message(update, context):
    uid  = update.effective_user.id
    cid  = update.effective_chat.id
    text = update.message.text.strip().lower()

    if uid == OWNER_ID:
        if any(x in text for x in ["análisis", "senal", "setup"]):
            await cmd_senal(update, context)
        elif "operación" in text or "operacion" in text:
            await cmd_operacion(update, context)
        elif "btc" in text:
            await cmd_btc(update, context)
        elif "eth" in text:
            await cmd_eth(update, context)
        elif "nivel" in text:
            await cmd_niveles(update, context)
        elif "activar" in text:
            await cmd_alerta(update, context)
        elif "detener" in text:
            await cmd_stopalerta(update, context)
        else:
            await update.message.reply_text(
                "Usa los botones o escribe un comando.\n/start para ver todos los comandos.",
                reply_markup=private_keyboard()
            )
    elif cid == GROUP_ID:
        if "análisis" in text or "hype" in text:
            await update.message.reply_text(analisis_completo("grupo"))
        elif "precio" in text:
            p = get_price("HYPE-USDT")
            await update.message.reply_text(f"💰 HYPE: ${p:.3f}" if p else "⚪ Sin datos")
        elif "activar" in text:
            await cmd_alerta(update, context)
        elif "detener" in text:
            await cmd_stopalerta(update, context)

# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

def main():
    load_state()
    if not TOKEN:
        raise Exception("TELEGRAM_TOKEN no definido en Railway")

    print("TOKEN CARGADO:", TOKEN[:20] + "...")
    print("🤖 HYPE AI Bot v8.1 iniciado...")
    print("📊 Datos en tiempo real desde KuCoin")
    print("⏱ Alertas cada 4H configuradas")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("ping",          cmd_ping))
    app.add_handler(CommandHandler("senal",         cmd_senal))
    app.add_handler(CommandHandler("niveles",       cmd_niveles))
    app.add_handler(CommandHandler("setnivel",      cmd_setnivel))
    app.add_handler(CommandHandler("operacion",     cmd_operacion))
    app.add_handler(CommandHandler("btc",           cmd_btc))
    app.add_handler(CommandHandler("eth",           cmd_eth))
    app.add_handler(CommandHandler("alertamercado", cmd_alerta))
    app.add_handler(CommandHandler("stopalerta",    cmd_stopalerta))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
