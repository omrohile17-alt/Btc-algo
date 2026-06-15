import sys
sys.stdout.reconfigure(line_buffering=True)
import requests, time, datetime, hmac, hashlib, json

BASE = 'https://cdn-ind.testnet.deltaex.org'
API_KEY = 'Ag6qMLKDsgFU8B1tlVEeJIBKxUveeV'
API_SECRET = 'PpifqTPhZHb2CdeawQgDCAwaXU21PoPuC4ZQA4DKekf1JCYoj769tjDbammi'

TELEGRAM_TOKEN = '8926593994:AAGmrgTBfjw93DG3reg1QEj_Q0P6Hi-PBUo'
TELEGRAM_CHAT_ID = '2133720588'

# ──────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────
def send_telegram(msg):
    try:
        requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            params={'chat_id': TELEGRAM_CHAT_ID, 'text': msg},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram error: {e}")

# ──────────────────────────────────────────
# REQUEST SIGNING
# ──────────────────────────────────────────
def sign_request(method, path, body=''):
    ts = str(int(time.time()))
    msg = method + ts + path + body
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        'api-key': API_KEY,
        'timestamp': ts,
        'signature': sig,
        'Content-Type': 'application/json'
    }

# ──────────────────────────────────────────
# POSITION CHECK
# ──────────────────────────────────────────
def get_position():
    headers = sign_request('GET', '/v2/positions/margined')
    r = requests.get(BASE + '/v2/positions/margined', headers=headers, timeout=10)
    for p in r.json().get('result', []):
        if p.get('product_id') == 84 and float(p.get('size', 0)) > 0:
            return p
    return None

# ──────────────────────────────────────────
# CANCEL ALL OPEN ORDERS (cleanup)
# ──────────────────────────────────────────
def cancel_all_orders():
    body = json.dumps({'product_id': 84, 'cancel_limit_orders': True, 'cancel_stop_orders': True})
    headers = sign_request('DELETE', '/v2/orders/all', body)
    r = requests.delete(BASE + '/v2/orders/all', headers=headers, data=body, timeout=10)
    result = r.json()
    if result.get('success'):
        print("🧹 Purane orders cancel ho gaye")
    else:
        print(f"⚠️ Cancel failed: {result}")

# ──────────────────────────────────────────
# CANDLES
# ──────────────────────────────────────────
def get_candles():
    end = int(time.time())
    start = end - (200 * 15 * 60)
    r = requests.get(BASE + '/v2/history/candles', params={
        'symbol': 'BTCUSD',
        'resolution': '15m',
        'start': start,
        'end': end
    }, timeout=10)
    candles = r.json().get('result', [])
    return list(reversed(candles))

# ──────────────────────────────────────────
# SIGNAL LOGIC
# ──────────────────────────────────────────
def get_signal(candles):
    if len(candles) < 200:
        return None, None, None

    closes = [float(c['close']) for c in candles]
    highs  = [float(c['high'])  for c in candles]
    lows   = [float(c['low'])   for c in candles]

    def ema(data, period):
        k = 2 / (period + 1)
        e = sum(data[:period]) / period
        for v in data[period:]:
            e = v * k + e * (1 - k)
        return e

    ema10  = ema(closes, 10)
    ema50  = ema(closes, 50)
    ema200 = ema(closes, 200)
    price  = closes[-1]

    atr = sum([highs[i] - lows[i] for i in range(-14, 0)]) / 14

    gains  = [max(0, closes[i] - closes[i-1]) for i in range(-14, 0)]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(-14, 0)]
    rs  = (sum(gains) / 14) / (sum(losses) / 14 + 0.0001)
    rsi = 100 - 100 / (1 + rs)

    print(f"Price:{price} | EMA10:{round(ema10,1)} | EMA50:{round(ema50,1)} | EMA200:{round(ema200,1)} | RSI:{round(rsi,1)} | ATR:{round(atr,1)}")

    if ema10 > ema50 and price > ema200 and rsi > 55:
        return 'buy', price, atr
    if ema10 < ema50 and price < ema200 and rsi < 45:
        return 'sell', price, atr

    return None, None, None

# ──────────────────────────────────────────
# STOP LOSS - Stop Market Order
# (Price touch hote hi market me execute hoga)
# ──────────────────────────────────────────
def place_sl(side, sl_price):
    sl_side = 'buy' if side == 'sell' else 'sell'
    body = json.dumps({
        'product_id': 84,
        'size': 1,
        'side': sl_side,
        'order_type': 'market_order',         # Market order - guaranteed fill
        'stop_order_type': 'stop_loss_order', # Stop trigger lagega
        'stop_price': str(int(sl_price)),     # Is price pe trigger hoga
        'stop_trigger_method': 'mark_price',  # Mark price pe trigger (safer)
        # reduce_only nahi - SL/TP dono saath hone par conflict hota hai
    })
    headers = sign_request('POST', '/v2/orders', body)
    r = requests.post(BASE + '/v2/orders', headers=headers, data=body, timeout=10)
    result = r.json()
    if result.get('success'):
        print(f"✅ SL (Stop Market) placed @ {int(sl_price)}")
        return result['result'].get('id')
    else:
        print(f"❌ SL failed: {result}")
        send_telegram(f"⚠️ SL place nahi hua! Manual lagao @ {int(sl_price)}")
        return None

# ──────────────────────────────────────────
# TAKE PROFIT - Limit Order
# (Limit order TP ke liye theek hai)
# ──────────────────────────────────────────
def place_tp(side, tp_price):
    tp_side = 'buy' if side == 'sell' else 'sell'
    body = json.dumps({
        'product_id': 84,
        'size': 1,
        'side': tp_side,
        'order_type': 'limit_order',        # Limit order - better price milti hai
        'limit_price': str(int(tp_price)),
        'time_in_force': 'gtc'              # Good Till Cancelled
        # reduce_only nahi - SL ke saath conflict hota hai
    })
    headers = sign_request('POST', '/v2/orders', body)
    r = requests.post(BASE + '/v2/orders', headers=headers, data=body, timeout=10)
    result = r.json()
    if result.get('success'):
        print(f"✅ TP (Limit) placed @ {int(tp_price)}")
        return result['result'].get('id')
    else:
        print(f"❌ TP failed: {result}")
        send_telegram(f"⚠️ TP place nahi hua! Manual lagao @ {int(tp_price)}")
        return None

# ──────────────────────────────────────────
# MAIN ORDER + AUTO SL/TP
# ──────────────────────────────────────────
def place_order(signal, price, atr):
    if signal == 'buy':
        sl = round(price - (atr * 1.5), 0)
        tp = round(price + (atr * 3.0), 0)
    else:
        sl = round(price + (atr * 1.5), 0)
        tp = round(price - (atr * 3.0), 0)

    rr = round((abs(tp - price)) / (abs(sl - price)), 2)
    print(f"\nSIGNAL: {signal.upper()} | Price:{price} | SL:{int(sl)} | TP:{int(tp)} | R:R = 1:{rr}")

    # Pehle purane orders cancel karo
    cancel_all_orders()

    # Main Market Order
    body = json.dumps({
        'product_id': 84,
        'size': 1,
        'side': signal,
        'order_type': 'market_order'
    })
    headers = sign_request('POST', '/v2/orders', body)
    r = requests.post(BASE + '/v2/orders', headers=headers, data=body, timeout=10)
    result = r.json()

    if result.get('success'):
        print(f"✅ Main order placed!")

        # Position settle hone do (7 sec)
        print("⏳ 7 sec wait - position settle ho rahi hai...")
        time.sleep(7)

        # Stop Loss lagao (Stop Market Order)
        sl_id = place_sl(signal, sl)

        # SL aur TP ke beech gap
        time.sleep(2)

        # Take Profit lagao (Limit Order)
        tp_id = place_tp(signal, tp)

        # Telegram notification
        sl_status = "✅" if sl_id else "❌ FAILED"
        tp_status = "✅" if tp_id else "❌ FAILED"

        send_telegram(
            f"🚨 BTC TRADE OPEN\n"
            f"{'🟢 BUY' if signal == 'buy' else '🔴 SELL'} @ {int(price)}\n"
            f"📍 SL: {int(sl)} (Stop Market) {sl_status}\n"
            f"🎯 TP: {int(tp)} (Limit) {tp_status}\n"
            f"📊 R:R = 1:{rr}\n"
            f"📐 ATR: {int(atr)}"
        )
    else:
        print(f"❌ Main order failed: {result}")
        send_telegram(f"❌ Order FAILED: {signal.upper()} @ {int(price)}\n{result.get('error', {})}")

# ──────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────
print("=" * 45)
print("  BTCUSD ALGO BOT - Delta Testnet")
print("  MODE : Auto SL (Stop Market) + TP (Limit)")
print("  SL   : 1.5x ATR | TP : 3.0x ATR")
print("  R:R  : 1:2")
print("=" * 45)

send_telegram("🤖 Bot V3 Start!\n✅ Stop Market SL\n✅ Limit TP\n⏰ 15m BTCUSD")

last_candle = None

while True:
    try:
        now = datetime.datetime.now()
        print(f"\n[{now.strftime('%H:%M:%S')}] Checking...")

        pos = get_position()
        if pos:
            entry = pos.get('entry_price', '?')
            side  = pos.get('side', '?')
            size  = pos.get('size', '?')
            pnl   = pos.get('unrealized_pnl', '?')
            print(f"📌 Position: {side.upper()} | Entry:{entry} | Size:{size} | PnL:{pnl}")
            time.sleep(60)
            continue

        candles = get_candles()
        print(f"Candles: {len(candles)}")

        signal, price, atr = get_signal(candles)

        if signal:
            candle_time = now.replace(
                minute=(now.minute // 15) * 15,
                second=0,
                microsecond=0
            )
            if last_candle == candle_time:
                print("⏭️ Is candle me already trade ho chuka hai")
            else:
                place_order(signal, price, atr)
                last_candle = candle_time
        else:
            print("No signal")

        time.sleep(60)

    except Exception as e:
        print(f"⚠️ Error: {e}")
        send_telegram(f"⚠️ Bot Error: {e}")
        time.sleep(30)
