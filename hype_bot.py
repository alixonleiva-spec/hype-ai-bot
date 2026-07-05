#!/usr/bin/env python3
"""
HYPE AI Trading Bot v7.0
Compatible con python-telegram-bot v20+
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
    "entrada":        62.852,
    "stop_loss":      63.50,
    "soporte_clave":  62.872,
    "target1":        65.75,
    "target2":        70.439,
    "target3":        72.722,
    "resistencia_h4": 74.240,
    "soporte_diario": 54.990,
}

state = {
    "prices":      [],
    "ema_fast":    None,
    "ema_slow":    None,
    "swings_high": [],
    "swings_low":  []
}

def load_state():
    global state
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                state.update(json.load(f))
        except: pass

def save_state():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(state, f)
    except: pass

# ══════════════════════════════════════════
#  DATOS KUCOIN
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
    segs = {"1hour": 3600, "4hour": 14400, "1day": 86400}
    start = end - segs.get(intervalo, 3600) * limit
    try:
        r = requests.get("https://api.kucoin.com/api/v1/market/candles",
            params={"symbol": symbol, "type": intervalo, "startAt": start, "endAt": end}, timeout=10)
        return [float(k[2]) for k in reversed(r.json()["data"])]
    except: return []

def get_rsi(symbol, intervalo="4hour", periodo=14):
    try:
        cierres = get_klines(symbol, intervalo, periodo + 5)
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

def get_macd(symbol, intervalo="1hour"):
    try:
        cierres = get_klines(symbol, intervalo, 60)
        if not cierres: return None, None, None
        def ema(p, n):
            k = 2/(n+1); e = [p[0]]
            for x in p[1:]: e.append(x*k + e[-1]*(1-k))
            return e
        e12 = ema(cierres, 12); e26 = ema(cierres, 26)
        macd = [m-n for m,n in zip(e12, e26)]
        sig = ema(macd[25:], 9)
        return round(macd[-1],4), round(sig[-1],4), round(macd[-1]-sig[-1],4)
    except: return None, None, None

def update_indicators(price):
    state["prices"].append(price)
    if len(state["prices"]) > 200:
        state["prices"] = state["prices"][-200:]
    sma50 = sum(state["prices"][-50:]) / min(len(state["prices"]), 50)
    af = 0.2
    state["ema_fast"] = price if state["ema_fast"] is None else af*price + (1-af)*state["ema_fast"]
    as_ = 0.1
    state["ema_slow"] = price if state["ema_slow"] is None else as_*price + (1-as_)*state["ema_slow"]
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
    llenos = round(pct / 100 * largo)
    return "█" * llenos + "░" * (largo - llenos)

# ══════════════════════════════════════════
#  ANÁLISIS Y FORMATO
# ══════════════════════════════════════════

def formato_señal(version="completa"):
    price  = get_price("HYPE-USDT")
    rsi_4h = get_rsi("HYPE-USDT", "4hour")
    rsi_1h = get_rsi("HYPE-USDT", "1hour")
    _, _, macd_hist = get_macd("HYPE-USDT", "1hour")
    hype_s = get_stats("HYPE-USDT")
    btc_s  = get_stats("BTC-USDT")
    eth_s  = get_stats("ETH-USDT")

    if not price:
        return "🤖 HYPE AI BOT v7.0\n━━━━━━━━━━━━━━━━━━\n⚪ SIN DATOS DE MERCADO\n━━━━━━━━━━━━━━━━━━"

    sma50, ema_fast, ema_slow = update_indicators(price)
    avg_combo = (sma50 + ema_fast + ema_slow) / 3

    score = 50
    if rsi_4h:
        if rsi_4h < 30: score += 25
        elif rsi_4h < 40: score += 15
        elif rsi_4h < 45: score += 8
        elif rsi_4h > 75: score -= 25
        elif rsi_4h > 65: score -= 12
    if rsi_1h:
        if rsi_1h < 35: score += 12
        elif rsi_1h < 45: score += 6
        elif rsi_1h > 70: score -= 12
    if macd_hist:
        score += 15 if macd_hist > 0 else -15
    if price > avg_combo * 1.01: score += 10
    elif price < avg_combo * 0.99: score -= 10
    if price > NIVELES["soporte_clave"]: score += 8
    if price < NIVELES["stop_loss"]: score -= 20
    btc_c = float(btc_s["changeRate"]) if btc_s else 0
    eth_c = float(eth_s["changeRate"]) if eth_s else 0
    if btc_c > 0 and eth_c > 0: score += 8
    elif btc_c < 0 and eth_c < 0: score -= 8
    score = max(10, min(90, score))

    if score >= 65:
        señal = "🟢 LONG"; accion = "ENTRAR LONG"
        riesgo = "Bajo" if score >= 75 else "Medio"
        sl = round(price * 0.975, 3); tp1 = NIVELES["target1"]; tp2 = NIVELES["target2"]
        ratio = round((tp1 - price) / (price - sl), 2) if price > sl else 0
    elif score <= 35:
        señal = "🔴 SHORT"; accion = "CONSIDERAR SHORT"; riesgo = "Alto"
        sl = round(price * 1.025, 3); tp1 = round(price * 0.95, 3); tp2 = round(price * 0.90, 3)
        ratio = round((price - tp1) / (sl - price), 2) if sl > price else 0
    else:
        señal = "🟡 NEUTRAL"; accion = "ESPERAR"; riesgo = "Medio"
        sl = NIVELES["stop_loss"]; tp1 = NIVELES["target1"]; tp2 = NIVELES["target2"]; ratio = 0

    hype_c = float(hype_s["changeRate"]) if hype_s else 0
    ganancia = ((price - NIVELES["entrada"]) / NIVELES["entrada"]) * 100 * 20
    sh = state.get("swings_high", []); sl_ = state.get("swings_low", [])

    if version == "grupo":
        return (
            f"🤖 HYPE AI BOT v7.0\n━━━━━━━━━━━━━━━━━━\n"
            f"📊 Estado del mercado HYPE\n"
            f"💰 HYPE Precio: ${price:.4f}\n"
            f"📈 Cambio 24h: {hype_c}%\n━━━━━━━━━━━━━━━━━━\n"
            f"📈 Probabilidad del setup\n{barra(score)} {score}%\n━━━━━━━━━━━━━━━━━━\n"
            f"💡 Acción: {accion}\n⚠ Riesgo: {riesgo}\n━━━━━━━━━━━━━━━━━━\n"
            f"📊 RSI 1H: {rsi_1h} | RSI 4H: {rsi_4h}\n"
            f"📈 MACD 1H: {macd_hist}\n"
            f"⭐ Score técnico: {score}/100\n━━━━━━━━━━━━━━━━━━\n"
            f"🌍 BTC: {btc_c}% | ETH: {eth_c}%\n⚠ Solo informativo"
        )

    msg = (
        f"🤖 HYPE AI BOT v7.0\n━━━━━━━━━━━━━━━━━━\n"
        f"📊 Estado del mercado HYPE\n"
        f"💰 HYPE Precio: ${price:.4f}\n"
        f"📈 Cambio 24h: {hype_c}%\n"
        f"📈 P&L estimado (20x): {ganancia:+.1f}%\n━━━━━━━━━━━━━━━━━━\n"
        f"📈 Probabilidad del setup\n{barra(score)} {score}%\n━━━━━━━━━━━━━━━━━━\n"
        f"{señal}\n💡 Acción sugerida: {accion}\n⚠ Riesgo: {riesgo}\n"
        f"🛑 SL: ${sl} | ⚡ R/B: 1:{ratio}\n"
        f"🎯 TP1: ${tp1} | TP2: ${tp2}\n━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI 1H: {rsi_1h} | RSI 4H: {rsi_4h}\n"
        f"📈 MACD 1H hist: {macd_hist}\n"
        f"📊 SMA50: {sma50:.3f} | EMA: {ema_fast:.3f}\n"
        f"⭐ Score técnico: {score}/100\n━━━━━━━━━━━━━━━━━━\n"
        f"🌍 BTC 24h: {btc_c}% | ETH 24h: {eth_c}%\n"
    )
    if sh: msg += f"🔴 Resistencias: {' / '.join(f'${v:.3f}' for v in sh[-3:])}\n"
    if sl_: msg += f"🟢 Soportes: {' / '.join(f'${v:.3f}' for v in sl_[-3:])}\n"
    msg += (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛑 Mis niveles:\n"
        f"Entrada: ${NIVELES['entrada']} | SL: ${NIVELES['stop_loss']}\n"
        f"T1: ${NIVELES['target1']} | T2: ${NIVELES['target2']} | T3: ${NIVELES['target3']}\n"
        f"━━━━━━━━━━━━━━━━━━\n⚠ Informativo. Usa tu criterio."
    )
    return msg

# ══════════════════════════════════════════
#  BOTONES
# ══════════════════════════════════════════

def private_keyboard():
    return ReplyKeyboardMarkup([
        ["📊 Panel", "🔍 HYPE Full"],
        ["₿ BTC", "Ξ ETH"],
        ["🟢 Señal LONG/SHORT", "📍 Niveles"],
        ["▶ Activar alerta", "⏹ Detener alerta"]
    ], resize_keyboard=True)

def group_keyboard():
    return ReplyKeyboardMarkup([
        ["📊 Precio HYPE", "🔍 HYPE Full"],
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
            "🤖 HYPE AI Bot v7.0\n━━━━━━━━━━━━━━━━━━\n"
            "✅ Panel privado activo\n\n"
            "/senal — Señal LONG/SHORT\n"
            "/status — Estado HYPE\n"
            "/niveles — Niveles activos\n"
            "/btc — BTC | /eth — ETH\n"
            "/hypefull — HYPE completo\n"
            "/alertamercado — Activar alertas\n"
            "/stopalerta — Detener alertas\n"
            "/ping — Test conexión",
            reply_markup=private_keyboard()
        )
    elif cid == GROUP_ID:
        await update.message.reply_text("🤖 HYPE AI Bot v7.0 activo", reply_markup=group_keyboard())

async def cmd_ping(update, context):
    await update.message.reply_text("🟢 Pong — Bot funcionando correctamente")

async def cmd_senal(update, context):
    if not is_owner(update): return
    await update.message.reply_text(formato_señal("completa"))

async def cmd_status(update, context):
    if not is_owner(update): return
    await update.message.reply_text(formato_señal("completa"))

async def cmd_niveles(update, context):
    if not is_owner(update): return
    await update.message.reply_text(
        f"🤖 HYPE AI BOT v7.0\n━━━━━━━━━━━━━━━━━━\n📍 Niveles activos\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Entrada: ${NIVELES['entrada']}\n🛑 SL: ${NIVELES['stop_loss']}\n"
        f"🟡 Soporte: ${NIVELES['soporte_clave']}\n"
        f"🎯 T1: ${NIVELES['target1']}\n🎯 T2: ${NIVELES['target2']}\n🎯 T3: ${NIVELES['target3']}\n"
        f"🔴 Resist H4: ${NIVELES['resistencia_h4']}\n🟢 Soporte D: ${NIVELES['soporte_diario']}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

async def cmd_btc(update, context):
    if not is_owner(update): return
    d = get_stats("BTC-USDT")
    if not d: await update.message.reply_text("⚪ SIN DATOS BTC"); return
    await update.message.reply_text(
        f"🤖 HYPE AI BOT v7.0\n━━━━━━━━━━━━━━━━━━\n₿ BTC / USDT\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio: ${float(d['last']):,.2f}\n📈 Cambio 24h: {d['changeRate']}%\n"
        f"🔼 Máx: ${float(d['high']):,.2f} | 🔽 Mín: ${float(d['low']):,.2f}\n"
        f"📊 RSI 4H: {get_rsi('BTC-USDT','4hour')}\n━━━━━━━━━━━━━━━━━━"
    )

async def cmd_eth(update, context):
    if not is_owner(update): return
    d = get_stats("ETH-USDT")
    if not d: await update.message.reply_text("⚪ SIN DATOS ETH"); return
    await update.message.reply_text(
        f"🤖 HYPE AI BOT v7.0\n━━━━━━━━━━━━━━━━━━\nΞ ETH / USDT\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio: ${float(d['last']):,.2f}\n📈 Cambio 24h: {d['changeRate']}%\n"
        f"🔼 Máx: ${float(d['high']):,.2f} | 🔽 Mín: ${float(d['low']):,.2f}\n"
        f"📊 RSI 4H: {get_rsi('ETH-USDT','4hour')}\n━━━━━━━━━━━━━━━━━━"
    )

async def cmd_hypefull(update, context):
    if not is_owner(update): return
    d = get_stats("HYPE-USDT")
    if not d: await update.message.reply_text("⚪ SIN DATOS HYPE"); return
    await update.message.reply_text(
        f"🤖 HYPE AI BOT v7.0\n━━━━━━━━━━━━━━━━━━\n📊 HYPE / USDT\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Precio: ${float(d['last']):.4f}\n📈 Cambio 24h: {d['changeRate']}%\n"
        f"🔼 Máx: ${float(d['high']):.4f} | 🔽 Mín: ${float(d['low']):.4f}\n"
        f"📊 Volumen 24h: {d['vol']}\n"
        f"📊 RSI 4H: {get_rsi('HYPE-USDT','4hour')} | RSI 1H: {get_rsi('HYPE-USDT','1hour')}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

# ══════════════════════════════════════════
#  ALERTAS
# ══════════════════════════════════════════

alert_active = False

async def send_alerts(context):
    try:
        await context.bot.send_message(chat_id=GROUP_ID, text=formato_señal("grupo"))
    except Exception as e:
        print(f"[ERROR grupo] {e}")
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=formato_señal("completa"))
    except Exception as e:
        print(f"[ERROR privado] {e}")

async def cmd_alerta(update, context):
    global alert_active
    uid = update.effective_user.id
    cid = update.effective_chat.id
    if cid == GROUP_ID:
        admins = [m.user.id for m in await context.bot.get_chat_administrators(GROUP_ID)]
        if uid not in admins:
            await update.message.reply_text("Solo administradores pueden activar alertas."); return
    elif uid != OWNER_ID: return
    alert_active = True
    context.job_queue.run_repeating(send_alerts, interval=120, first=5, name="alertas")
    await update.message.reply_text(
        "🤖 HYPE AI BOT v7.0\n━━━━━━━━━━━━━━━━━━\n✅ Alertas activadas\n⏱ Cada 2 minutos\n━━━━━━━━━━━━━━━━━━"
    )

async def cmd_stopalerta(update, context):
    jobs = context.job_queue.get_jobs_by_name("alertas")
    for job in jobs:
        job.schedule_removal()
    await update.message.reply_text("⏹ Alertas detenidas.")

# ══════════════════════════════════════════
#  MENSAJES DE TEXTO
# ══════════════════════════════════════════

async def handle_message(update, context):
    uid  = update.effective_user.id
    cid  = update.effective_chat.id
    text = update.message.text.strip().lower()

    if uid == OWNER_ID:
        if any(x in text for x in ["señal", "senal", "long", "short", "panel"]):
            await cmd_senal(update, context)
        elif "btc" in text: await cmd_btc(update, context)
        elif "eth" in text: await cmd_eth(update, context)
        elif "hype" in text: await cmd_hypefull(update, context)
        elif "nivel" in text: await cmd_niveles(update, context)
        elif "activar" in text: await cmd_alerta(update, context)
        elif "detener" in text: await cmd_stopalerta(update, context)
        else:
            await update.message.reply_text("Usa los botones o un comando.", reply_markup=private_keyboard())
    elif cid == GROUP_ID:
        if "precio hype" in text or "hype full" in text: await cmd_hypefull(update, context)
        elif "activar" in text: await cmd_alerta(update, context)
        elif "detener" in text: await cmd_stopalerta(update, context)

# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

def main():
    load_state()

    if not TOKEN:
        raise Exception("TELEGRAM_TOKEN no está definido")

    print("TOKEN CARGADO:", TOKEN[:20] + "...")
    print("🤖 HYPE AI Bot v7.0 iniciado...")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("ping",          cmd_ping))
    app.add_handler(CommandHandler("senal",         cmd_senal))
    app.add_handler(CommandHandler("status",        cmd_status))
    app.add_handler(CommandHandler("niveles",       cmd_niveles))
    app.add_handler(CommandHandler("btc",           cmd_btc))
    app.add_handler(CommandHandler("eth",           cmd_eth))
    app.add_handler(CommandHandler("hypefull",      cmd_hypefull))
    app.add_handler(CommandHandler("mostrar",       cmd_senal))
    app.add_handler(CommandHandler("alertamercado", cmd_alerta))
    app.add_handler(CommandHandler("stopalerta",    cmd_stopalerta))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
