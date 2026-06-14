impimport requests, time, datetime, hmac, hashlib, json

BASE = 'https://cdn-ind.testnet.deltaex.org'
API_KEY = 'Ag6qMLKDsgFU8B1tlVEeJIBKxUveeV'
API_SECRET = 'PpifqTPhZHb2CdeawQgDCAwaXU21PoPuC4ZQA4DKekf1JCYoj769tjDbammi'

def sign_request(method, path, body=''):
    ts = str(int(time.time()))
    msg = method + ts + path + body
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {'api-key': API_KEY, 'timestamp': ts, 'signature': sig, 'Content-Type': 'application/json'}

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
        'symbol': 'BTCUSD', 'resolution': '15m',
        'start': start, 'end': end
    })
    return r.json().get('result', [])

def get_signal(candles):
    if len(candles) < 50: return None, None, None
    closes = [float(c['close']) for c in candles]
    ema10 = sum(closes[-10:])/10
    ema50 = sum(closes[-50:])/50
    ema200 = sum(closes[-200:])/200 if len(closes)>=200 else None
    price = closes[-1]
    highs = [float(c['high']) for c in candles[-14:]]
    lows = [float(c['low']) for c in candles[-14:]]
    atr = sum([h-l for h,l in zip(highs,lows)])/14
    rsi_gains = [max(0, closes[i]-closes[i-1]) for i in range(-14,0)]
    rsi_losses = [max(0, closes[i-1]-closes[i]) for i in range(-14,0)]
    rs = (sum(rsi_gains)/14)/(sum(rsi_losses)/14+0.0001)
    rsi = 100 - 100/(1+rs)
    if ema200 and ema10>ema50 and price>ema200 and rsi>50:
        return 'buy', price, atr
    if ema200 and ema10<ema50 and price<ema200 and rsi<50:
        return 'sell', price, atr
    return None, None, None

def place_stop_order(side, stop_price, close_side):
    """Place a separate stop order for SL or TP"""
    body = json.dumps({
        'product_id': 84,
        'size': 5,
        'side': close_side,           # opposite side to close position
        'order_type': 'limit_order',
        'stop_order_type': 'stop_loss_order',
        'stop_price': str(int(stop_price)),
        'limit_price': str(int(stop_price)),
        'reduce_only': True
    })
    headers = sign_request('POST', '/v2/orders', body)
    r = requests.post(BASE+'/v2/orders', headers=headers, data=body)
    return r.json()

def place_order(signal, price, atr):
    sl = round(price-(atr*1.0),0) if signal=='buy' else round(price+(atr*1.0),0)
    tp = round(price+(atr*2.0),0) if signal=='buy' else round(price-(atr*2.0),0)
    print(f"SIGNAL: {signal.upper()} | Price:{price} | SL:{sl} | TP:{tp}")

    # Step 1: Main market order
    body = json.dumps({
        'product_id': 84,
        'size': 5,
        'side': signal,
        'order_type': 'market_order'
    })
    headers = sign_request('POST', '/v2/orders', body)
    r = requests.post(BASE+'/v2/orders', headers=headers, data=body)
    result = r.json()

    if result.get('success'):
        print(f"✅ Main order placed!")
        time.sleep(2)  # Wait for order to fill

        # Step 2: Place SL stop order
        close_side = 'sell' if signal == 'buy' else 'buy'
        sl_result = place_stop_order(signal, sl, close_side)
        if sl_result.get('success'):
            print(f"✅ SL order placed at {sl}")
        else:
            print(f"❌ SL order failed: {sl_result}")

        # Step 3: Place TP stop order
        tp_result = place_stop_order(signal, tp, close_side)
        if tp_result.get('success'):
            print(f"✅ TP order placed at {tp}")
        else:
            print(f"❌ TP order failed: {tp_result}")
    else:
        print(f"❌ Main order failed: {result}")

print("="*40)
print(" BTCUSD ALGO - Delta Testnet")
print(" EMA 10/50/200 + RSI + ATR")
print(" SL: 1x ATR | TP: 2x ATR")
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
        candle_time = now.replace(minute=(now.minute//15)*15, second=0, microsecond=0)
        if last_candle == candle_time:
            print("Already traded this candle")
        else:
            place_order(signal, price, atr)
            last_candle = candle_time
    else:
        print("No signal")
    time.sleep(60)
