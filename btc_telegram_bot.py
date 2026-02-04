#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bitcoin Up or Down — Telegram Bot (Railway Version)
Работает 24/7 на сервере
"""

import requests
import time
import os
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКИ TELEGRAM (берутся из переменных окружения Railway)
# ═══════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8567469797:AAFKfSKciZBmL1TNvOzWwRKETaRWIxbvdqc")
CHAT_ID = os.getenv("CHAT_ID", "440615055")

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКИ БОТА
# ═══════════════════════════════════════════════════════════════

SIGNAL_INTERVAL = 300  # 5 минут между сигналами
MIN_CONFIDENCE = 60    # Минимальная уверенность для ставки
STARTING_BALANCE = 1000
BET_PERCENTAGE = 5

# ═══════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ═══════════════════════════════════════════════════════════════

simulation = {
    'balance': STARTING_BALANCE,
    'total_bets': 0,
    'wins': 0,
    'losses': 0,
    'last_bet': None
}

# ═══════════════════════════════════════════════════════════════
# ФУНКЦИЯ ОТПРАВКИ В TELEGRAM
# ═══════════════════════════════════════════════════════════════

def send_telegram(message):
    """Отправляет сообщение в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=data, timeout=10)
        return response.json().get('ok', False)
    except Exception as e:
        print(f"Ошибка Telegram: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# ПОЛУЧЕНИЕ ДАННЫХ
# ═══════════════════════════════════════════════════════════════

def get_btc_price():
    """Получает цену BTC с Binance."""
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        response = requests.get(url, params={"symbol": "BTCUSDT"}, timeout=5)
        return float(response.json()['price'])
    except:
        return 0


def get_candles(interval='1m', limit=100):
    """Получает свечи с Binance."""
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
        response = requests.get(url, params=params, timeout=10)
        
        candles = []
        for k in response.json():
            candles.append({
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5])
            })
        return candles
    except:
        return []


def get_orderbook():
    """Получает Order Flow данные."""
    try:
        url = "https://api.binance.com/api/v3/depth"
        response = requests.get(url, params={"symbol": "BTCUSDT", "limit": 20}, timeout=5)
        data = response.json()
        
        bid_volume = sum(float(bid[1]) for bid in data['bids'])
        ask_volume = sum(float(ask[1]) for ask in data['asks'])
        total = bid_volume + ask_volume
        
        return {
            'buy_pressure': (bid_volume / total * 100) if total > 0 else 50,
            'delta': bid_volume - ask_volume
        }
    except:
        return {'buy_pressure': 50, 'delta': 0}


# ═══════════════════════════════════════════════════════════════
# ИНДИКАТОРЫ
# ═══════════════════════════════════════════════════════════════

def calculate_rsi(prices, period=14):
    """RSI — перекупленность/перепроданность."""
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
    """MACD — тренд и импульс."""
    if len(prices) < 35:
        return {'histogram': 0}
    
    def ema(data, period):
        mult = 2 / (period + 1)
        result = [data[0]]
        for price in data[1:]:
            result.append((price * mult) + (result[-1] * (1 - mult)))
        return result
    
    ema12 = ema(prices, 12)
    ema26 = ema(prices, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(ema26))]
    signal_line = ema(macd_line, 9)
    
    return {'histogram': round(macd_line[-1] - signal_line[-1], 2)}


def calculate_vwap(candles):
    """VWAP — средневзвешенная цена."""
    if not candles:
        return 0
    
    tp_vol = sum((c['high'] + c['low'] + c['close']) / 3 * c['volume'] for c in candles)
    vol = sum(c['volume'] for c in candles)
    
    return round(tp_vol / vol, 2) if vol > 0 else 0


def get_heikin_ashi_trend(candles):
    """Heikin Ashi — направление тренда."""
    if len(candles) < 5:
        return 'neutral'
    
    ha_candles = []
    for i, c in enumerate(candles):
        ha_close = (c['open'] + c['high'] + c['low'] + c['close']) / 4
        if i == 0:
            ha_open = (c['open'] + c['close']) / 2
        else:
            ha_open = (ha_candles[-1]['open'] + ha_candles[-1]['close']) / 2
        ha_candles.append({'open': ha_open, 'close': ha_close})
    
    recent = ha_candles[-5:]
    bullish = sum(1 for c in recent if c['close'] > c['open'])
    
    if bullish >= 4:
        return 'bullish'
    elif bullish <= 1:
        return 'bearish'
    return 'neutral'


# ═══════════════════════════════════════════════════════════════
# РАСЧЁТ СИГНАЛА
# ═══════════════════════════════════════════════════════════════

def calculate_signal(price, candles, orderbook):
    """Рассчитывает торговый сигнал."""
    
    closes = [c['close'] for c in candles]
    
    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    vwap = calculate_vwap(candles)
    ha_trend = get_heikin_ashi_trend(candles)
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
    else:
        score -= 15
        reasons.append("🔴 MACD медвежий")
    
    # VWAP
    if price > vwap:
        diff = ((price - vwap) / vwap) * 100
        score += 20 if diff > 0.3 else 10
        reasons.append(f"🟢 Цена выше VWAP (+{diff:.2f}%)")
    else:
        diff = ((vwap - price) / vwap) * 100
        score -= 20 if diff > 0.3 else 10
        reasons.append(f"🔴 Цена ниже VWAP (-{diff:.2f}%)")
    
    # Heikin Ashi
    if ha_trend == 'bullish':
        score += 15
        reasons.append("🟢 HA тренд вверх")
    elif ha_trend == 'bearish':
        score -= 15
        reasons.append("🔴 HA тренд вниз")
    else:
        reasons.append("⚪ HA нейтрален")
    
    # Order Flow
    if buy_pressure > 55:
        score += 15
        reasons.append(f"🟢 Покупатели ({buy_pressure:.0f}%)")
    elif buy_pressure < 45:
        score -= 15
        reasons.append(f"🔴 Продавцы ({100-buy_pressure:.0f}%)")
    else:
        reasons.append(f"⚪ Баланс рынка")
    
    direction = "UP 📈" if score > 0 else "DOWN 📉"
    confidence = min(abs(score), 100)
    
    return {
        'direction': direction,
        'direction_simple': 'UP' if score > 0 else 'DOWN',
        'confidence': confidence,
        'score': score,
        'reasons': reasons,
        'rsi': rsi,
        'vwap': vwap
    }


# ═══════════════════════════════════════════════════════════════
# СИМУЛЯЦИЯ СТАВОК
# ═══════════════════════════════════════════════════════════════

def process_last_bet(current_price):
    """Проверяет результат последней ставки."""
    global simulation
    
    if simulation['last_bet'] is None:
        return None
    
    bet = simulation['last_bet']
    
    if bet['direction'] == 'UP':
        won = current_price > bet['entry_price']
    else:
        won = current_price < bet['entry_price']
    
    if won:
        simulation['wins'] += 1
        simulation['balance'] += bet['amount'] * 0.9
        result = "✅ WIN"
    else:
        simulation['losses'] += 1
        simulation['balance'] -= bet['amount']
        result = "❌ LOSS"
    
    simulation['last_bet'] = None
    
    return {
        'result': result,
        'won': won,
        'entry': bet['entry_price'],
        'exit': current_price,
        'pnl': bet['amount'] * 0.9 if won else -bet['amount']
    }


def place_bet(direction, confidence, price):
    """Размещает виртуальную ставку."""
    global simulation
    
    if confidence < MIN_CONFIDENCE:
        return None
    
    bet_amount = simulation['balance'] * (BET_PERCENTAGE / 100)
    
    simulation['last_bet'] = {
        'direction': direction,
        'entry_price': price,
        'amount': bet_amount
    }
    simulation['total_bets'] += 1
    
    return bet_amount


# ═══════════════════════════════════════════════════════════════
# ФОРМАТИРОВАНИЕ СООБЩЕНИЯ
# ═══════════════════════════════════════════════════════════════

def format_message(price, signal, bet_result, new_bet_amount):
    """Форматирует сообщение для Telegram."""
    
    now = datetime.now(timezone.utc)
    
    if signal['confidence'] >= 70:
        strength = "🔥 СИЛЬНЫЙ"
    elif signal['confidence'] >= 55:
        strength = "💪 СРЕДНИЙ"
    else:
        strength = "😐 СЛАБЫЙ"
    
    msg = f"""
<b>━━━ BITCOIN SIGNAL ━━━</b>
🕐 {now.strftime('%H:%M UTC')} | {now.strftime('%d.%m.%Y')}

<b>💰 BTC: ${price:,.2f}</b>

<b>{'🟢' if signal['direction_simple'] == 'UP' else '🔴'} СИГНАЛ: {signal['direction']}</b>
📊 Уверенность: {signal['confidence']}% ({strength})

<b>📈 Индикаторы:</b>
"""
    
    for reason in signal['reasons']:
        msg += f"  {reason}\n"
    
    if bet_result:
        msg += f"""
<b>📋 Прошлая ставка:</b>
  {bet_result['result']}
  Вход: ${bet_result['entry']:,.2f}
  Выход: ${bet_result['exit']:,.2f}
  P&L: {'+' if bet_result['pnl'] > 0 else ''}${bet_result['pnl']:,.2f}
"""
    
    if new_bet_amount:
        msg += f"""
<b>🎯 Новая ставка:</b>
  {signal['direction']} | ${new_bet_amount:,.2f}
"""
    elif signal['confidence'] < MIN_CONFIDENCE:
        msg += f"\n<b>⏸ Пропуск</b> (уверенность &lt;{MIN_CONFIDENCE}%)\n"
    
    win_rate = (simulation['wins'] / simulation['total_bets'] * 100) if simulation['total_bets'] > 0 else 0
    pnl = simulation['balance'] - STARTING_BALANCE
    
    msg += f"""
<b>💼 Симуляция:</b>
  ${simulation['balance']:,.2f} ({'+' if pnl >= 0 else ''}{pnl/STARTING_BALANCE*100:.1f}%)
  W{simulation['wins']}/L{simulation['losses']} | WR: {win_rate:.0f}%
<b>━━━━━━━━━━━━━━━━━━━━</b>
"""
    
    return msg


# ═══════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ
# ═══════════════════════════════════════════════════════════════

def main():
    """Запуск бота."""
    
    print("🚀 Bitcoin Bot запущен на сервере!")
    print(f"📱 Интервал: {SIGNAL_INTERVAL // 60} минут")
    
    # Приветствие
    send_telegram("🤖 <b>Bitcoin Bot запущен на сервере!</b>\n\nСигналы каждые 5 минут 24/7")
    
    while True:
        try:
            price = get_btc_price()
            candles = get_candles('1m', 100)
            orderbook = get_orderbook()
            
            if price == 0 or not candles:
                print("⚠️ Ошибка данных, повтор...")
                time.sleep(30)
                continue
            
            signal = calculate_signal(price, candles, orderbook)
            bet_result = process_last_bet(price)
            new_bet = place_bet(signal['direction_simple'], signal['confidence'], price)
            
            message = format_message(price, signal, bet_result, new_bet)
            
            if send_telegram(message):
                print(f"✅ Сигнал: {signal['direction']} ({signal['confidence']}%)")
            
            time.sleep(SIGNAL_INTERVAL)
            
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
