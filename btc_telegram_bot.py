#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bitcoin Up or Down — Telegram Bot (Railway Version v2)
С запасными источниками данных
"""

import requests
import time
import os
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8567469797:AAFKfSKciZBmL1TNvOzWwRKETaRWIxbvdqc")
CHAT_ID = os.getenv("CHAT_ID", "440615055")

SIGNAL_INTERVAL = 300
MIN_CONFIDENCE = 60
STARTING_BALANCE = 1000
BET_PERCENTAGE = 5

simulation = {
    'balance': STARTING_BALANCE,
    'total_bets': 0,
    'wins': 0,
    'losses': 0,
    'last_bet': None
}

price_history = []

# ═══════════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════════

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=data, timeout=10)
        return response.json().get('ok', False)
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# ПОЛУЧЕНИЕ ДАННЫХ (3 источника)
# ═══════════════════════════════════════════════════════════════

def get_btc_price():
    """Пробует 3 разных источника."""
    
    # Источник 1: Binance
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        response = requests.get(url, params={"symbol": "BTCUSDT"}, timeout=5)
        if response.status_code == 200:
            price = float(response.json()['price'])
            print(f"✓ Binance: ${price:,.0f}")
            return price
    except Exception as e:
        print(f"✗ Binance failed: {e}")
    
    # Источник 2: CoinGecko
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": "bitcoin", "vs_currencies": "usd"}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            price = float(response.json()['bitcoin']['usd'])
            print(f"✓ CoinGecko: ${price:,.0f}")
            return price
    except Exception as e:
        print(f"✗ CoinGecko failed: {e}")
    
    # Источник 3: Coinbase
    try:
        url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            price = float(response.json()['data']['amount'])
            print(f"✓ Coinbase: ${price:,.0f}")
            return price
    except Exception as e:
        print(f"✗ Coinbase failed: {e}")
    
    return 0


def get_btc_data():
    """Получает расширенные данные."""
    
    # Пробуем Binance для свечей
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": "BTCUSDT", "interval": "1m", "limit": 100}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            candles = []
            for k in response.json():
                candles.append({
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5])
                })
            return {'candles': candles, 'source': 'Binance'}
    except:
        pass
    
    # Fallback: используем историю цен
    return {'candles': None, 'source': 'PriceHistory'}


def get_orderbook():
    """Order Flow данные."""
    try:
        url = "https://api.binance.com/api/v3/depth"
        response = requests.get(url, params={"symbol": "BTCUSDT", "limit": 20}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            bid_vol = sum(float(b[1]) for b in data['bids'])
            ask_vol = sum(float(a[1]) for a in data['asks'])
            total = bid_vol + ask_vol
            return {'buy_pressure': (bid_vol / total * 100) if total > 0 else 50}
    except:
        pass
    return {'buy_pressure': 50}

# ═══════════════════════════════════════════════════════════════
# ИНДИКАТОРЫ
# ═══════════════════════════════════════════════════════════════

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = [d if d > 0 else 0 for d in recent]
    losses = [-d if d < 0 else 0 for d in recent]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calculate_macd(prices):
    if len(prices) < 35:
        return {'histogram': 0}
    def ema(data, period):
        mult = 2 / (period + 1)
        result = [data[0]]
        for p in data[1:]:
            result.append((p * mult) + (result[-1] * (1 - mult)))
        return result
    ema12 = ema(prices, 12)
    ema26 = ema(prices, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(ema26))]
    signal_line = ema(macd_line, 9)
    return {'histogram': round(macd_line[-1] - signal_line[-1], 2)}


def calculate_vwap(candles):
    if not candles:
        return 0
    tp_vol = sum((c['high'] + c['low'] + c['close']) / 3 * c['volume'] for c in candles)
    vol = sum(c['volume'] for c in candles)
    return round(tp_vol / vol, 2) if vol > 0 else 0


def get_trend(prices):
    if len(prices) < 10:
        return 'neutral'
    recent = prices[-10:]
    up_moves = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
    if up_moves >= 7:
        return 'bullish'
    elif up_moves <= 3:
        return 'bearish'
    return 'neutral'

# ═══════════════════════════════════════════════════════════════
# СИГНАЛ
# ═══════════════════════════════════════════════════════════════

def calculate_signal(price, candles, orderbook, prices):
    
    if candles:
        closes = [c['close'] for c in candles]
    else:
        closes = prices if len(prices) > 20 else [price] * 50
    
    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    vwap = calculate_vwap(candles) if candles else price
    trend = get_trend(closes)
    buy_pressure = orderbook['buy_pressure']
    
    score = 0
    reasons = []
    
    # RSI
    if rsi < 30:
        score += 25
        reasons.append(f"🟢 RSI перепродан ({rsi})")
    elif rsi > 70:
        score -= 25
        reasons.append(f"🔴 RSI перекуплен ({rsi})")
    elif rsi < 45:
        score += 10
        reasons.append(f"🟡 RSI низкий ({rsi})")
    elif rsi > 55:
        score -= 10
        reasons.append(f"🟡 RSI высокий ({rsi})")
    else:
        reasons.append(f"⚪ RSI нейтрален ({rsi})")
    
    # MACD
    if macd['histogram'] > 50:
        score += 25
        reasons.append("🟢 MACD сильный бычий")
    elif macd['histogram'] > 0:
        score += 15
        reasons.append("🟢 MACD бычий")
    elif macd['histogram'] < -50:
        score -= 25
        reasons.append("🔴 MACD сильный медвежий")
    elif macd['histogram'] < 0:
        score -= 15
        reasons.append("🔴 MACD медвежий")
    
    # VWAP
    if vwap > 0:
        if price > vwap:
            diff = ((price - vwap) / vwap) * 100
            score += 15
            reasons.append(f"🟢 Выше VWAP (+{diff:.2f}%)")
        else:
            diff = ((vwap - price) / vwap) * 100
            score -= 15
            reasons.append(f"🔴 Ниже VWAP (-{diff:.2f}%)")
    
    # Trend
    if trend == 'bullish':
        score += 15
        reasons.append("🟢 Тренд вверх")
    elif trend == 'bearish':
        score -= 15
        reasons.append("🔴 Тренд вниз")
    else:
        reasons.append("⚪ Тренд нейтрален")
    
    # Order Flow
    if buy_pressure > 55:
        score += 15
        reasons.append(f"🟢 Покупатели ({buy_pressure:.0f}%)")
    elif buy_pressure < 45:
        score -= 15
        reasons.append(f"🔴 Продавцы ({100-buy_pressure:.0f}%)")
    
    direction = "UP 📈" if score > 0 else "DOWN 📉"
    confidence = min(abs(score), 100)
    
    return {
        'direction': direction,
        'direction_simple': 'UP' if score > 0 else 'DOWN',
        'confidence': confidence,
        'reasons': reasons,
        'rsi': rsi,
        'vwap': vwap
    }

# ═══════════════════════════════════════════════════════════════
# СИМУЛЯЦИЯ
# ═══════════════════════════════════════════════════════════════

def process_last_bet(current_price):
    global simulation
    if simulation['last_bet'] is None:
        return None
    bet = simulation['last_bet']
    won = (current_price > bet['entry_price']) if bet['direction'] == 'UP' else (current_price < bet['entry_price'])
    if won:
        simulation['wins'] += 1
        simulation['balance'] += bet['amount'] * 0.9
        result = "✅ WIN"
    else:
        simulation['losses'] += 1
        simulation['balance'] -= bet['amount']
        result = "❌ LOSS"
    simulation['last_bet'] = None
    return {'result': result, 'won': won, 'entry': bet['entry_price'], 'exit': current_price, 'pnl': bet['amount'] * 0.9 if won else -bet['amount']}


def place_bet(direction, confidence, price):
    global simulation
    if confidence < MIN_CONFIDENCE:
        return None
    bet_amount = simulation['balance'] * (BET_PERCENTAGE / 100)
    simulation['last_bet'] = {'direction': direction, 'entry_price': price, 'amount': bet_amount}
    simulation['total_bets'] += 1
    return bet_amount

# ═══════════════════════════════════════════════════════════════
# СООБЩЕНИЕ
# ═══════════════════════════════════════════════════════════════

def format_message(price, signal, bet_result, new_bet):
    now = datetime.now(timezone.utc)
    strength = "🔥" if signal['confidence'] >= 70 else "💪" if signal['confidence'] >= 55 else "😐"
    
    msg = f"""<b>━━━ BITCOIN SIGNAL ━━━</b>
🕐 {now.strftime('%H:%M UTC')}

<b>💰 BTC: ${price:,.2f}</b>

<b>{'🟢' if signal['direction_simple'] == 'UP' else '🔴'} {signal['direction']}</b>
📊 {signal['confidence']}% {strength}

<b>Индикаторы:</b>
"""
    for r in signal['reasons']:
        msg += f"{r}\n"
    
    if bet_result:
        msg += f"\n<b>Прошлая:</b> {bet_result['result']} ({'+' if bet_result['pnl']>0 else ''}{bet_result['pnl']:.0f}$)\n"
    
    if new_bet:
        msg += f"\n<b>🎯 Ставка:</b> {signal['direction']} ${new_bet:.0f}\n"
    
    pnl = simulation['balance'] - STARTING_BALANCE
    wr = (simulation['wins']/simulation['total_bets']*100) if simulation['total_bets'] > 0 else 0
    msg += f"\n<b>💼</b> ${simulation['balance']:.0f} ({'+' if pnl>=0 else ''}{pnl:.0f}$) | WR: {wr:.0f}%"
    
    return msg

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global price_history
    
    print("🚀 Bitcoin Bot v2 запущен!")
    send_telegram("🤖 <b>Bitcoin Bot v2 запущен!</b>\n\nТеперь с резервными источниками данных.")
    
    while True:
        try:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Получаю данные...")
            
            price = get_btc_price()
            
            if price == 0:
                print("⚠️ Все источники недоступны, жду 60 сек...")
                time.sleep(60)
                continue
            
            # Сохраняем историю цен
            price_history.append(price)
            if len(price_history) > 200:
                price_history = price_history[-200:]
            
            data = get_btc_data()
            orderbook = get_orderbook()
            
            signal = calculate_signal(price, data['candles'], orderbook, price_history)
            bet_result = process_last_bet(price)
            new_bet = place_bet(signal['direction_simple'], signal['confidence'], price)
            
            message = format_message(price, signal, bet_result, new_bet)
            
            if send_telegram(message):
                print(f"✅ Сигнал отправлен: {signal['direction']} ({signal['confidence']}%)")
            else:
                print("❌ Ошибка отправки в Telegram")
            
            print(f"⏳ Следующий через {SIGNAL_INTERVAL//60} мин...")
            time.sleep(SIGNAL_INTERVAL)
            
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
