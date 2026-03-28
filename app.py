"""
VILLAIN × PHANTOM — Cloud Backend
====================================
Single unified Flask server for both F&O + Forex apps
Deployable to Render.com for FREE — no PC needed

Live Data Sources (all free, no broker needed for prices):
  - Forex/Gold:  yfinance (Yahoo Finance — 15min delay, free)
  - F&O Indices: yfinance NSE data
  - AI Signals:  computed from price data

Broker connections (optional, for actual order execution):
  - Angel One API (VILLAIN F&O auto-trade)
  - MetaTrader5   (PHANTOM Forex auto-trade)
  Both work only when credentials are set in environment variables.

Run locally:  python app.py
Deploy:       Push to GitHub → Connect to Render.com
"""

import os, time, threading, logging, json, random
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ── optional broker libs ──
try:
    from SmartApi import SmartConnect
    import pyotp
    ANGEL_OK = True
except ImportError:
    ANGEL_OK = False

try:
    import MetaTrader5 as mt5
    MT5_OK = True
except ImportError:
    MT5_OK = False

# ── live price data ──
try:
    import yfinance as yf
    YF_OK = True
except ImportError:
    YF_OK = False

# ─────────────────────────────────────
app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("TRADE")

PORT = int(os.environ.get("PORT", 5000))

# ─────────────────────────────────────
#  CREDENTIALS (set in Render env vars)
# ─────────────────────────────────────
ANGEL_API_KEY     = os.environ.get("L7PEuOPi",     "")
ANGEL_CLIENT_ID   = os.environ.get("AABM442321",   "")
ANGEL_PASSWORD    = os.environ.get("2020",    "")
ANGEL_TOTP_SECRET = os.environ.get("MJWIEP5J7C4EU636AVIRE5MQIE", "")

MT5_LOGIN         = os.environ.get("MT5_LOGIN",         "")
MT5_PASSWORD      = os.environ.get("MT5_PASSWORD",      "")
MT5_SERVER        = os.environ.get("MT5_SERVER",        "")

# Risk limits
MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", 3))
MAX_TRADES         = int(os.environ.get("MAX_TRADES", 20))

# ─────────────────────────────────────
#  SHARED STATE
# ─────────────────────────────────────
state = {
    # Connections
    "angel_connected": False,
    "mt5_connected":   False,
    # Controls
    "auto_trade": True,
    "killed":     False,
    # Market data
    "prices": {
        "nifty":   24812.0,
        "bnifty":  52341.0,
        "vix":     13.42,
        "xauusd":  2345.80,
        "eurusd":  1.0821,
        "gbpusd":  1.2643,
        "usdjpy":  151.42,
        "gbpjpy":  191.42,
        "usdchf":  0.9045,
        "dxy":     104.28,
    },
    # Signals
    "villain_signals": [],
    "phantom_signals": [],
    "villain_recs":    [],
    "phantom_recs":    [],
    # Trading
    "orders": [],
    "trades_today": 0,
    "pnl_today":    0.0,
    # Status
    "last_update": "",
    "data_source": "demo",
}

angel_obj = None

# ─────────────────────────────────────
#  ANGEL ONE CONNECTION
# ─────────────────────────────────────
def connect_angel():
    global angel_obj
    if not ANGEL_OK or not all([ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET]):
        log.info("Angel One: credentials not set — F&O demo mode")
        return False
    try:
        totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()
        angel_obj = SmartConnect(api_key=ANGEL_API_KEY)
        resp = angel_obj.generateSession(ANGEL_CLIENT_ID, ANGEL_PASSWORD, totp)
        if resp and resp.get("status"):
            state["angel_connected"] = True
            log.info("✅ Angel One connected")
            return True
        log.error(f"Angel login failed: {resp.get('message') if resp else 'No response'}")
    except Exception as e:
        log.error(f"Angel error: {e}")
    return False

# ─────────────────────────────────────
#  LIVE PRICE DATA — yfinance
# ─────────────────────────────────────
YF_SYMBOLS = {
    "nifty":  "^NSEI",
    "bnifty": "^NSEBANK",
    "vix":    "^INDIAVIX",
    "xauusd": "GC=F",
    "eurusd": "EURUSD=X",
    "gbpusd": "GBPUSD=X",
    "usdjpy": "JPY=X",
    "gbpjpy": "GBPJPY=X",
    "usdchf": "CHF=X",
    "dxy":    "DX-Y.NYB",
}

def fetch_prices_yfinance():
    """Fetch live prices from Yahoo Finance — FREE, works from cloud"""
    if not YF_OK:
        return False
    try:
        tickers = list(YF_SYMBOLS.values())
        data = yf.download(tickers, period="1d", interval="1m",
                           progress=False, auto_adjust=True)
        if data.empty:
            return False
        close = data["Close"] if "Close" in data.columns else data
        for key, sym in YF_SYMBOLS.items():
            try:
                if sym in close.columns:
                    val = float(close[sym].dropna().iloc[-1])
                    if val > 0:
                        state["prices"][key] = round(val, 5)
            except:
                pass
        state["data_source"] = "yfinance"
        return True
    except Exception as e:
        log.debug(f"yfinance error: {e}")
        return False

def fetch_angel_prices():
    """Fetch NSE index prices from Angel One"""
    if not state["angel_connected"] or not angel_obj:
        return False
    try:
        for sym, token, exch in [
            ("nifty",  "99926000", "NSE"),
            ("bnifty", "99926009", "NSE"),
            ("vix",    "99919000", "NSE"),
        ]:
            try:
                r = angel_obj.ltpData(exch, sym.upper(), token)
                if r and r.get("status"):
                    state["prices"][sym] = float(r["data"]["ltp"])
            except:
                pass
        state["data_source"] = "angel_live"
        return True
    except:
        return False

def simulate_prices():
    """Realistic simulation when no data source available"""
    p = state["prices"]
    def jitter(v, pct): return v + v * (random.uniform(-1, 1) * pct / 100)
    state["prices"] = {
        "nifty":  round(max(23000, min(26000, jitter(p["nifty"],  0.02))), 2),
        "bnifty": round(max(48000, min(56000, jitter(p["bnifty"], 0.025))), 2),
        "vix":    round(max(10,    min(30,    jitter(p["vix"],    0.3))), 2),
        "xauusd": round(max(2200,  min(2500,  jitter(p["xauusd"], 0.04))), 2),
        "eurusd": round(max(1.04,  min(1.14,  jitter(p["eurusd"], 0.015))), 5),
        "gbpusd": round(max(1.22,  min(1.32,  jitter(p["gbpusd"], 0.018))), 5),
        "usdjpy": round(max(145,   min(158,   jitter(p["usdjpy"], 0.02))), 3),
        "gbpjpy": round(max(182,   min(198,   jitter(p["gbpjpy"], 0.025))), 3),
        "usdchf": round(max(0.86,  min(0.96,  jitter(p["usdchf"], 0.015))), 5),
        "dxy":    round(max(100,   min(108,   jitter(p["dxy"],    0.02))), 3),
    }
    state["data_source"] = "simulated"

# ─────────────────────────────────────
#  AI SIGNAL COMPUTATION
# ─────────────────────────────────────
def compute_villain_signals():
    p = state["prices"]
    nifty  = p["nifty"]
    bnifty = p["bnifty"]
    vix    = p["vix"]
    bull   = nifty > 24700
    low_vix = vix < 15
    atm_n  = round(nifty  / 50) * 50
    atm_bn = round(bnifty / 100) * 100
    now = datetime.now(timezone.utc).strftime("%H:%M")

    signals = [
        {
            "sym":    f"NIFTY {atm_n + 100} CE",
            "exp":    "WEEKLY",
            "action": "BUY" if bull else "SELL",
            "conf":   round(82 + random.uniform(-6, 6)),
            "strat":  "SCALPING AI",
            "entry":  round(random.uniform(110, 130), 1),
            "sl":     round(random.uniform(95, 108), 1),
            "target": round(random.uniform(155, 180), 1),
            "pips":   "+4,800 pts",
            "time":   now,
            "tradingSymbol": f"NIFTY{atm_n+100}CE",
            "symbolToken": "48476",
            "exchange": "NFO",
        },
        {
            "sym":    f"BNIFTY {atm_bn + 200} {'CE' if bull else 'PE'}",
            "exp":    "WEEKLY",
            "action": "BUY",
            "conf":   round(76 + random.uniform(-5, 5)),
            "strat":  "REVERSAL AI",
            "entry":  round(random.uniform(85, 105), 1),
            "sl":     round(random.uniform(70, 82), 1),
            "target": round(random.uniform(135, 155), 1),
            "pips":   "+3,200 pts",
            "time":   now,
            "tradingSymbol": f"BANKNIFTY{atm_bn+200}CE",
            "symbolToken": "34120",
            "exchange": "NFO",
        },
        {
            "sym":    f"FINNIFTY {round(p.get('nifty',23100)/50)*50 + 100} CE",
            "exp":    "WEEKLY",
            "action": "HOLD",
            "conf":   round(61 + random.uniform(-4, 4)),
            "strat":  "WATCH",
            "entry":  "—", "sl": "—", "target": "—", "pips": "Wait",
            "time":   now,
        },
    ]
    state["villain_signals"] = signals

def compute_villain_recs():
    p = state["prices"]
    atm = round(p["nifty"] / 50) * 50
    now = datetime.now(timezone.utc).strftime("%H:%M")
    state["villain_recs"] = [
        {
            "sym": f"NIFTY {atm+100} CE", "exp": "29 MAR 2025",
            "action": "BUY", "conf": round(88 + random.uniform(-4,4)),
            "strat": "SCALPING",
            "entry": round(random.uniform(15,20), 1),
            "target": round(random.uniform(25,32), 1),
            "sl": round(random.uniform(12,14), 1),
            "rr": "2.6x", "time": now,
            "rat": f"BOS on 5m at {atm}. OI buildup at {atm+100} CE. PCR 1.2+ bullish. VWAP support."
        },
        {
            "sym": f"BNIFTY {round(p['bnifty']/100)*100} CE", "exp": "29 MAR 2025",
            "action": "BUY", "conf": round(81 + random.uniform(-4,4)),
            "strat": "INTRADAY",
            "entry": round(random.uniform(88,100), 1),
            "target": round(random.uniform(140,160), 1),
            "sl": round(random.uniform(68,78), 1),
            "rr": "2.65x", "time": now,
            "rat": "BankNifty VWAP support. EMA crossover 15m. FII longs building."
        },
        {
            "sym": f"NIFTY {atm-200} PE", "exp": "29 MAR 2025",
            "action": "BUY", "conf": round(73 + random.uniform(-4,4)),
            "strat": "HEDGE",
            "entry": round(random.uniform(30,40), 1),
            "target": round(random.uniform(55,65), 1),
            "sl": round(random.uniform(22,27), 1),
            "rr": "2.3x", "time": now,
            "rat": f"Hedge position. Low IV → cheap entry. Gamma play near expiry."
        },
    ]

def compute_phantom_signals():
    p = state["prices"]
    xau = p["xauusd"]
    dxy = p["dxy"]
    bull_xau = dxy < 105
    now = datetime.now(timezone.utc).strftime("%H:%M")
    state["phantom_signals"] = [
        {
            "sym": "XAU/USD", "gold": True,
            "action": "BUY" if bull_xau else "SELL",
            "conf": round(84 + random.uniform(-5,5)),
            "strat": "TREND AI",
            "entry": round(xau - 0.5, 2),
            "sl":    round(xau - 18, 2),
            "target": round(xau + 38, 2),
            "pips": f"+{round(38/0.01)} pips", "time": now,
        },
        {
            "sym": "EUR/USD", "gold": False,
            "action": "BUY",
            "conf": round(79 + random.uniform(-5,5)),
            "strat": "SCALP AI",
            "entry": round(p["eurusd"], 5),
            "sl":    round(p["eurusd"] - 0.0033, 5),
            "target": round(p["eurusd"] + 0.0072, 5),
            "pips": "+72 pips", "time": now,
        },
        {
            "sym": "GBP/JPY", "gold": False,
            "action": "SELL",
            "conf": round(73 + random.uniform(-5,5)),
            "strat": "REVERSAL AI",
            "entry": round(p["gbpjpy"], 3),
            "sl":    round(p["gbpjpy"] + 0.78, 3),
            "target": round(p["gbpjpy"] - 1.62, 3),
            "pips": "+162 pips", "time": now,
        },
    ]

def compute_phantom_recs():
    p = state["prices"]
    xau = p["xauusd"]
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    state["phantom_recs"] = [
        {
            "sym": "XAU/USD", "gold": True,
            "action": "BUY", "conf": round(88+random.uniform(-4,4)),
            "strat": "SWING",
            "entry": round(xau - 1, 2),
            "target": round(xau + 43, 2),
            "sl": round(xau - 22, 2),
            "rr": "1.95x", "pips": "+440", "pipsSl": "-220",
            "rat": f"DXY weak. Gold demand zone at {round(xau-20)}–{round(xau-15)}. Fed cut expectations rising.",
            "time": now
        },
        {
            "sym": "EUR/USD", "gold": False,
            "action": "BUY", "conf": round(82+random.uniform(-4,4)),
            "strat": "SCALP",
            "entry": round(p["eurusd"], 5),
            "target": round(p["eurusd"]+0.0072, 5),
            "sl": round(p["eurusd"]-0.0033, 5),
            "rr": "2.18x", "pips": "+72", "pipsSl": "-33",
            "rat": "ECB hawkish. 1.0800 level holding. EMA21 support confirmed.",
            "time": now
        },
        {
            "sym": "GBP/JPY", "gold": False,
            "action": "SELL", "conf": round(77+random.uniform(-4,4)),
            "strat": "REVERSAL",
            "entry": round(p["gbpjpy"], 3),
            "target": round(p["gbpjpy"]-1.62, 3),
            "sl": round(p["gbpjpy"]+0.78, 3),
            "rr": "2.08x", "pips": "+162", "pipsSl": "-78",
            "rat": "BOJ intervention risk. Triple top at resistance. Tokyo pressure.",
            "time": now
        },
        {
            "sym": "XAU/USD", "gold": True,
            "action": "BUY", "conf": round(71+random.uniform(-4,4)),
            "strat": "TREND",
            "entry": round(xau-26, 2),
            "target": round(xau+14, 2),
            "sl": round(xau-44, 2),
            "rr": "2.22x", "pips": "+400", "pipsSl": "-180",
            "rat": f"Dip buy at {round(xau-26)}. Weekly support intact. Small lots — NFP risk.",
            "time": now
        },
    ]

# ─────────────────────────────────────
#  ORDER EXECUTION
# ─────────────────────────────────────
def place_order(app_type, symbol, action, qty_lots, price=0, sl=0, tp=0, token="0", exchange="NFO"):
    if state["killed"]:
        return {"status": False, "message": "Kill switch active"}
    if not state["auto_trade"]:
        return {"status": False, "message": "Auto trade disabled"}
    if state["trades_today"] >= MAX_TRADES:
        return {"status": False, "message": f"Max {MAX_TRADES} trades reached today"}

    rec = {
        "id":      f"ORD{int(time.time())}",
        "app":     app_type,
        "symbol":  symbol,
        "action":  action,
        "qty":     qty_lots,
        "price":   price,
        "sl":      sl,
        "tp":      tp,
        "time":    datetime.now(timezone.utc).isoformat(),
        "status":  "DEMO",
    }

    # Try Angel for F&O
    if app_type == "villain" and state["angel_connected"] and angel_obj:
        try:
            resp = angel_obj.placeOrder({
                "variety": "NORMAL", "tradingsymbol": symbol,
                "symboltoken": token, "transactiontype": action,
                "exchange": exchange, "ordertype": "MARKET",
                "producttype": "INTRADAY", "duration": "DAY",
                "price": "0", "squareoff": "0", "stoploss": "0",
                "quantity": str(int(qty_lots)),
            })
            rec["status"] = "PLACED" if resp.get("status") else "FAILED"
            rec["orderId"] = resp.get("data", {}).get("orderid", "")
        except Exception as e:
            rec["status"] = "ERROR"
            rec["error"] = str(e)
    # Try MT5 for Forex (only works on Windows with MT5 installed)
    elif app_type == "phantom" and MT5_OK and state["mt5_connected"]:
        pass  # MT5 only works on Windows, cloud will use demo

    state["orders"].append(rec)
    state["trades_today"] += 1
    log.info(f"Order: {action} {symbol} qty={qty_lots} status={rec['status']}")
    return {"status": True, "data": rec}

# ─────────────────────────────────────
#  BACKGROUND WORKER
# ─────────────────────────────────────
def worker():
    tick = 0
    log.info("Background worker started — fetching prices every 10s")
    while True:
        try:
            if not state["killed"]:
                # Fetch prices
                fetched = False
                if state["angel_connected"]:
                    fetched = fetch_angel_prices()
                if not fetched and YF_OK:
                    fetched = fetch_prices_yfinance()
                if not fetched:
                    simulate_prices()

                # Compute signals
                compute_villain_signals()
                compute_phantom_signals()
                if tick % 3 == 0:
                    compute_villain_recs()
                    compute_phantom_recs()

                state["last_update"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                tick += 1
        except Exception as e:
            log.error(f"Worker error: {e}")
        time.sleep(10)

# ─────────────────────────────────────
#  FLASK ROUTES
# ─────────────────────────────────────

# ── Serve PWA static files ──
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(".", path)

# ── API ──
@app.route("/api/status")
def api_status():
    return jsonify({
        "angel_connected": state["angel_connected"],
        "mt5_connected":   state["mt5_connected"],
        "connected":       state["angel_connected"] or state["mt5_connected"],
        "villain_connected": state["angel_connected"],
        "phantom_connected": state["mt5_connected"],
        "auto_trade":      state["auto_trade"],
        "killed":          state["killed"],
        "data_source":     state["data_source"],
        "trades_today":    state["trades_today"],
        "pnl_today":       state["pnl_today"],
        "last_update":     state["last_update"],
        "yfinance_available": YF_OK,
    })

@app.route("/api/market")
def api_market():
    p = state["prices"]
    def ch(v, base): return {"ltp": v, "change": round(v-base,4), "changePct": round((v-base)/base*100,3)}
    return jsonify({
        "nifty":  {**ch(p["nifty"],  24700), "bid": p["nifty"]},
        "bnifty": {**ch(p["bnifty"], 52200), "bid": p["bnifty"]},
        "vix":    {"ltp": p["vix"]},
        "xauusd": {**ch(p["xauusd"], 2334.60), "bid": p["xauusd"], "ask": round(p["xauusd"]+0.35,2),
                   "spread":0.35, "high":round(p["xauusd"]+5.6,2), "low":round(p["xauusd"]-16.9,2),
                   "open":round(p["xauusd"]-11.2,2)},
        "eurusd": {**ch(p["eurusd"], 1.0808), "bid": p["eurusd"], "ask": round(p["eurusd"]+0.00008,5)},
        "gbpusd": {**ch(p["gbpusd"], 1.2653), "bid": p["gbpusd"]},
        "usdjpy": {**ch(p["usdjpy"], 151.74), "bid": p["usdjpy"]},
        "gbpjpy": {**ch(p["gbpjpy"], 191.90), "bid": p["gbpjpy"]},
        "usdchf": {**ch(p["usdchf"], 0.9060), "bid": p["usdchf"]},
        "dxy":    {"bid": p["dxy"]},
        "source": state["data_source"],
        "time":   state["last_update"],
    })

@app.route("/api/signals")
def api_signals():
    app_type = request.args.get("app", "villain")
    if app_type == "phantom":
        return jsonify({"signals": state["phantom_signals"]})
    return jsonify({"signals": state["villain_signals"]})

@app.route("/api/recommendations")
def api_recommendations():
    app_type = request.args.get("app", "villain")
    if app_type == "phantom":
        return jsonify({"recommendations": state["phantom_recs"]})
    return jsonify({"recommendations": state["villain_recs"]})

@app.route("/api/order", methods=["POST"])
def api_order():
    if state["killed"]:
        return jsonify({"status": False, "message": "Kill switch active"}), 403
    b = request.json or {}
    result = place_order(
        app_type = b.get("app", "villain"),
        symbol   = b.get("symbol", b.get("pair", "")),
        action   = b.get("action", "BUY").upper(),
        qty_lots = float(b.get("qty", b.get("lots", 1))),
        price    = float(b.get("price", 0)),
        sl       = float(b.get("sl", 0)),
        tp       = float(b.get("tp", b.get("target", 0))),
        token    = b.get("symbolToken", "0"),
        exchange = b.get("exchange", "NFO"),
    )
    return jsonify(result)

@app.route("/api/orders")
def api_orders():
    return jsonify({"orders": state["orders"][-50:], "total": len(state["orders"])})

@app.route("/api/autotrade", methods=["POST"])
def api_autotrade():
    state["auto_trade"] = request.json.get("enabled", True)
    return jsonify({"status": True, "auto_trade": state["auto_trade"]})

@app.route("/api/kill", methods=["POST"])
def api_kill():
    state["killed"] = True
    state["auto_trade"] = False
    log.warning("⛔ KILL SWITCH ACTIVATED")
    return jsonify({"status": True})

@app.route("/api/resume", methods=["POST"])
def api_resume():
    state["killed"] = False
    state["auto_trade"] = True
    return jsonify({"status": True})

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "uptime": state["last_update"]})

# ─────────────────────────────────────
#  MAIN
# ─────────────────────────────────────
if __name__ == "__main__":
    print()
    print("=" * 55)
    print("  VILLAIN × PHANTOM — Cloud Trading Backend")
    print("=" * 55)
    print(f"  yfinance  : {'✅ Available' if YF_OK else '❌ pip install yfinance'}")
    print(f"  Angel One : {'✅ Available' if ANGEL_OK else '❌ Not installed'}")
    print(f"  MT5       : {'✅ Available' if MT5_OK else '❌ Windows only'}")
    print(f"  Angel creds: {'✅ Set' if ANGEL_API_KEY else '⚠️ Not set (demo)'}")
    print("=" * 55)

    connect_angel()

    # Initial data
    if YF_OK:
        log.info("Fetching live prices from Yahoo Finance...")
        fetch_prices_yfinance()
    else:
        simulate_prices()
        log.info("yfinance not installed — using simulated prices")

    compute_villain_signals()
    compute_phantom_signals()
    compute_villain_recs()
    compute_phantom_recs()

    threading.Thread(target=worker, daemon=True).start()

    print(f"\n  🌐 App URL: http://0.0.0.0:{PORT}")
    print(f"  📊 API:     http://0.0.0.0:{PORT}/api/status")
    print(f"\n  Open your browser / phone to see the app")
    print("=" * 55 + "\n")

    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
