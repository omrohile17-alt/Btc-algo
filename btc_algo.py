import sys
sys.stdout.reconfigure(line_buffering=True)
import requests, time, datetime, hmac, hashlib, json

BASE = 'https://cdn-ind.testnet.deltaex.org'
API_KEY = 'Ag6qMLKDsgFU8B1tlVEeJIBKxUveeV'
API_SECRET = 'PpifqTPhZHb2CdeawQgDCAwaXU21PoPuC4ZQA4DKekf1JCYoj769tjDbammi'

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

def get_position():
    headers = sign_request('GET', '/v2/positions/margined')
    r = requests.get(BASE+'/v2/positions/margined', headers=headers)
    for p in r.json().get('result', []):
        if p.get('product_id') == 84 and float(p.get('size', 0)) > 0:
            return p
    return None

def get_candles():
    end = int(time.time())
    start = end - (200 * 15 * 60)
    r = requests.get(BASE+'/v2/history/candles', params={
        'symbol': 'BTCUSD',
        'resolution': '15m',
        'start': start,
        'end': end
    })
    return r.json().get('result', [])

def get_signal(candles):
    if len(candles) < 200:
        return None, None, None

    closes = [float(c['close']) for c in candles]
    highs  = [float(c['high'])  for c in candles]
    lows   = [float(c['low'])   for c in candles]

    def ema(data, period):
        k = 2/(period+1)
        e = sum(data[:period])/period
        for v in data[period:]:
            e = v*k + e*(1-k)
        return e

    ema10  = ema(closes, 10)
    ema50  = ema(closes, 50)
    ema200 = ema(closes, 200)
    price  = closes[-1]

    atr = sum([highs[i] - lows[i] for i in range(-14, 0)]) / 14

    gains  = [max(0, closes[i]-closes[i-1]) for i in range(-14, 0)]
    losses = [max(0, closes[i-1]-closes[i]) for i in range(-14, 0)]
    rs  = (sum(gains)/14) / (sum(losses)/14 + 0.0001)
    rsi = 100 - 100/(1+rs)

    if ema10 > ema50 and price > ema200 and rsi > 55:
        return 'buy', price, atr
    if ema10 < ema50 and price < ema200 and rsi < 45:
        return 'sell', price, atr

    return None, None, None

def place_sl(side, sl):
    sl_side = 'buy' if side == 'sell' else 'sell'
    body = json.dumps({
        'product_id': 84,
        'size': 1,
        'side': sl_side,
        'order_type': 'limit_order',
        'limit_price': str(int(sl)),
        'stop_price': str(int(sl)),
        'stop_order_type': 'stop_loss_order',
        'reduce_only': True
    })
    headers = sign_request('POST', '/v2/orders', body)
    r = requests.post(BASE+'/v2/orders', headers=headers, data=body)
    result = r.json()
    if result.get('success'):
        print(f"✅ SL placed: {sl}")
    else:
        print(f"❌ SL failed: {result}")

def place_tp(side, tp):
    tp_side = 'buy' if side == 'sell' else 'sell'
    body = json.dumps({
        'product_id': 84,
        'size': 1,
        'side': tp_side,
        'order_type': 'limit_order',
        'limit_price': str(int(tp)),
        'reduce_only': True
    })
    headers = sign_request('POST', '/v2/orders', body)
    r = requests.post(BASE+'/v2/orders', headers=headers, data=body)
    result = r.json()
    if result.get('success'):
        print(f"✅ TP placed: {tp}")
    else:
        print(f"❌ TP failed: {result}")

def place_order(signal, price, atr):
    if signal == 'buy':
        sl = round(price - (atr * 2.0), 0)
        tp = round(price + (atr * 4.0), 0)
    else:
        sl = round(price + (atr * 2.0), 0)
        tp = round(price - (atr * 4.0), 0)

    print(f"SIGNAL: {signal.upper()} | Price:{price} | SL:{sl} | TP:{tp}")

    body = json.dumps({
        'product_id': 84,
        'size': 1,
        'side': signal,
        'order_type': 'market_order'
    })
    headers = sign_request('POST', '/v2/orders', body)
    r = requests.post(BASE+'/v2/orders', headers=headers, data=body)
    result = r.json()

    if result.get('success'):
        print(f"✅ Main order placed!")
        time.sleep(2)
        place_sl(signal, sl)
        place_tp(signal, tp)
    else:
        print(f"❌ Order failed: {result}")

print("="*40)
print(" BTCUSD ALGO - Delta Testnet")
print(" EMA 10/50/200 + RSI + ATR")
print(" SL: 2.0x ATR | TP: 4.0x ATR")
print("="*40)

last_candle = None

while True:
    now = datetime.datetime.now()
    print(f"\n[{now.strftime('%H:%M:%S')}] Checking...")

    pos = get_position()
    if pos:
        print(f"Position open: {pos.get('side')} | Entry:{pos.get('entry_price')}")
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
            print("Already traded this candle")
        else:
            place_order(signal, price, atr)
            last_candle = candle_time
    else:
        print("No signal")

    time.sleep(60)
