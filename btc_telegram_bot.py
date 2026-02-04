#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bitcoin Up or Down — Telegram Bot v3
Симуляция 15-минутных ставок в стиле Polymarket
"""

import requests
import time
import os
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8567469797:AAFKfSKciZBmL1TNvOzWwRKETaRWIxbvdqc")
CHAT_ID = os.getenv("CHAT_ID", "440615055")

# Интервал проверки (каждую минуту проверяем, не пора ли закрыть ставку)
CHECK_INTERVAL = 60  # 1 минута

# Настройки ставок
STARTING_BALANCE = 1000      # Начальный депозит
MIN_CONFIDENCE = 40          # Минимальная уверенность для ставки (%)
MIN_BET_PERCENT = 3          # Минимальный размер ставки (% от депозита)
MAX_BET_PERCENT = 5          # Максимальный размер ставки (% от депозита)
BET_DURATION_MINUTES = 15    # Длительность ставки (минут)

# Коэффициенты выплат Polymarket (примерные)
WIN_MULTIPLIER = 0.85        # При выигрыше получаем +85% от ставки
LOSE_MULTIPLIER = 1.0        # При проигрыше теряем 100% ставки

# ═══════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ═══════════════════════════════════════════════════════════════

simulation = {
    'balance': STARTING_BALANCE,
    'total_bets': 0,
    'wins': 0,
    'losses': 0,
    'active_bet': None,      # Текущая активная ставка
    'history': [],           # История ставок
    'total_profit': 0
}

price_history = []
last_signal_time = None

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
# ПОЛУЧЕНИЕ ДАННЫХ
# ═══════════════════════════════════════════════════════════════

def get_btc_price():
    """Получает цену BTC из 3 источников."""
    
    # Источник 1: Binance
    try:
        response = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=5
        )
        if response.status_code == 200:
            return float(response.json()['price'])
    except:
        pass
    
    # Источник 2: CoinGecko
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=10
        )
        if response.status_code == 200:
            return float(response.json()['bitcoin']['usd'])
    except:
        pass
    
    # Источник 3: Coinbase
    try:
        response = requests.get(
            "https://api.coinbase.com/v2/prices/BTC-USD/spot",
            timeout=10
        )
        if response.status_code == 200:
            return float(response.json()['data']['amount'])
    except:
        pass
    
    return 0


def get_candles():
    """Получает свечи с Binance."""
    try:
        response = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "1m", "limit": 100},
            timeout=10
        )
        if response.status_code == 200:
            return [{
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5])
            } for k in response.json()]
    except:
        pass
    return None


def get_orderbook():
    """Получает данные стакана."""
    try:
        response = requests.get(
            "https://api.binance.com/api/v3/depth",
            params={"symbol": "BTCUSDT", "limit": 20},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            bid_vol = sum(float(b[1]) for b in data['bids'])
            ask_vol = sum(float(a[1]) for a in data['asks'])
            total = bid_vol + ask_vol
            return (bid_vol / total * 100) if total > 0 else 50
    except:
        pass
    return 50

# ═══════════════════════════════════════════════════════════════
# ИНДИКАТОРЫ
# ═══════════════════════════════════════════════════════════════

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = sum(d for d in recent if d > 0) / period
    losses = sum(-d for d in recent if d < 0) / period
    if losses == 0:
        return 100
    rs = gains / losses
    return round(100 - (100 / (1 + rs)), 1)


def calculate_macd(prices):
    if len(prices) < 35:
        return 0
    def ema(data, period):
        mult = 2 / (period + 1)
        result = [data[0]]
        for p in data[1:]:
            result.append((p * mult) + (result[-1] * (1 - mult)))
        return result
    ema12 = ema(prices, 12)
    ema26 = ema(prices, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(ema26))]
    signal = ema(macd_line, 9)
    return round(macd_line[-1] - signal[-1], 2)


def calculate_vwap(candles):
    if not candles:
        return 0
    tp_vol = sum((c['high'] + c['low'] + c['close']) / 3 * c['volume'] for c in candles)
    vol = sum(c['volume'] for c in candles)
    return round(tp_vol / vol, 2) if vol > 0 else 0


def get_momentum(prices, period=10):
    """Моментум за последние N свечей."""
    if len(prices) < period:
        return 0
    return ((prices[-1] - prices[-period]) / prices[-period]) * 100

# ═══════════════════════════════════════════════════════════════
# РАСЧЁТ СИГНАЛА
# ═══════════════════════════════════════════════════════════════

def calculate_signal(price, candles, buy_pressure):
    """Рассчитывает сигнал и уверенность."""
    
    if candles:
        closes = [c['close'] for c in candles]
    elif len(price_history) > 20:
        closes = price_history
    else:
        closes = [price] * 50
    
    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    vwap = calculate_vwap(candles) if candles else price
    momentum = get_momentum(closes)
    
    score = 0
    reasons = []
    
    # RSI (вес 25)
    if rsi < 30:
        score += 25
        reasons.append(f"🟢 RSI перепродан ({rsi})")
    elif rsi > 70:
        score -= 25
        reasons.append(f"🔴 RSI перекуплен ({rsi})")
    elif rsi < 40:
        score += 15
        reasons.append(f"🟢 RSI низкий ({rsi})")
    elif rsi > 60:
        score -= 15
        reasons.append(f"🔴 RSI высокий ({rsi})")
    else:
        reasons.append(f"⚪ RSI нейтрален ({rsi})")
    
    # MACD (вес 25)
    if macd > 100:
        score += 25
        reasons.append("🟢 MACD сильный бычий")
    elif macd > 0:
        score += 15
        reasons.append("🟢 MACD бычий")
    elif macd < -100:
        score -= 25
        reasons.append("🔴 MACD сильный медвежий")
    elif macd < 0:
        score -= 15
        reasons.append("🔴 MACD медвежий")
    
    # VWAP (вес 20)
    if vwap > 0:
        vwap_diff = ((price - vwap) / vwap) * 100
        if vwap_diff > 0.3:
            score += 20
            reasons.append(f"🟢 Выше VWAP (+{vwap_diff:.2f}%)")
        elif vwap_diff > 0:
            score += 10
            reasons.append(f"🟢 Чуть выше VWAP")
        elif vwap_diff < -0.3:
            score -= 20
            reasons.append(f"🔴 Ниже VWAP ({vwap_diff:.2f}%)")
        else:
            score -= 10
            reasons.append(f"🔴 Чуть ниже VWAP")
    
    # Momentum (вес 15)
    if momentum > 0.3:
        score += 15
        reasons.append(f"🟢 Моментум вверх (+{momentum:.2f}%)")
    elif momentum < -0.3:
        score -= 15
        reasons.append(f"🔴 Моментум вниз ({momentum:.2f}%)")
    else:
        reasons.append("⚪ Моментум нейтрален")
    
    # Order Flow (вес 15)
    if buy_pressure > 55:
        score += 15
        reasons.append(f"🟢 Покупатели ({buy_pressure:.0f}%)")
    elif buy_pressure < 45:
        score -= 15
        reasons.append(f"🔴 Продавцы ({100-buy_pressure:.0f}%)")
    else:
        reasons.append("⚪ Баланс ордеров")
    
    # Направление и уверенность
    direction = 'UP' if score > 0 else 'DOWN'
    confidence = min(abs(score), 100)
    
    return {
        'direction': direction,
        'confidence': confidence,
        'score': score,
        'reasons': reasons,
        'rsi': rsi,
        'macd': macd,
        'vwap': vwap,
        'momentum': momentum
    }

# ═══════════════════════════════════════════════════════════════
# СТАВКИ
# ═══════════════════════════════════════════════════════════════

def calculate_bet_size(confidence):
    """
    Рассчитывает размер ставки в зависимости от уверенности.
    40% уверенность → 3% от депозита
    80%+ уверенность → 5% от депозита
    """
    if confidence < MIN_CONFIDENCE:
        return 0
    
    # Линейная интерполяция между MIN и MAX
    confidence_range = 80 - MIN_CONFIDENCE  # 40 пунктов
    bet_range = MAX_BET_PERCENT - MIN_BET_PERCENT  # 2%
    
    normalized = min(confidence - MIN_CONFIDENCE, confidence_range) / confidence_range
    bet_percent = MIN_BET_PERCENT + (normalized * bet_range)
    
    return simulation['balance'] * (bet_percent / 100)


def open_bet(direction, confidence, entry_price):
    """Открывает новую ставку."""
    global simulation
    
    if simulation['active_bet'] is not None:
        return None  # Уже есть активная ставка
    
    if confidence < MIN_CONFIDENCE:
        return None
    
    bet_amount = calculate_bet_size(confidence)
    bet_percent = (bet_amount / simulation['balance']) * 100
    
    simulation['active_bet'] = {
        'direction': direction,
        'entry_price': entry_price,
        'amount': bet_amount,
        'confidence': confidence,
        'open_time': datetime.now(timezone.utc),
        'close_time': datetime.now(timezone.utc) + timedelta(minutes=BET_DURATION_MINUTES)
    }
    
    return {
        'amount': bet_amount,
        'percent': bet_percent
    }


def check_and_close_bet(current_price):
    """Проверяет и закрывает ставку если прошло 15 минут."""
    global simulation
    
    if simulation['active_bet'] is None:
        return None
    
    bet = simulation['active_bet']
    now = datetime.now(timezone.utc)
    
    # Проверяем, прошло ли 15 минут
    if now < bet['close_time']:
        remaining = (bet['close_time'] - now).total_seconds() / 60
        return {'status': 'active', 'remaining_minutes': remaining}
    
    # Закрываем ставку
    price_change = current_price - bet['entry_price']
    
    if bet['direction'] == 'UP':
        won = price_change > 0
    else:
        won = price_change < 0
    
    # Расчёт P&L
    if won:
        pnl = bet['amount'] * WIN_MULTIPLIER
        simulation['wins'] += 1
    else:
        pnl = -bet['amount'] * LOSE_MULTIPLIER
        simulation['losses'] += 1
    
    simulation['balance'] += pnl
    simulation['total_bets'] += 1
    simulation['total_profit'] += pnl
    
    result = {
        'status': 'closed',
        'won': won,
        'direction': bet['direction'],
        'entry_price': bet['entry_price'],
        'exit_price': current_price,
        'price_change': price_change,
        'amount': bet['amount'],
        'pnl': pnl,
        'confidence': bet['confidence']
    }
    
    simulation['history'].append(result)
    simulation['active_bet'] = None
    
    return result

# ═══════════════════════════════════════════════════════════════
# СООБЩЕНИЯ
# ═══════════════════════════════════════════════════════════════

def format_new_bet_message(price, signal, bet_info):
    """Сообщение при открытии новой ставки."""
    
    now = datetime.now(timezone.utc)
    close_time = now + timedelta(minutes=BET_DURATION_MINUTES)
    
    emoji = "🟢" if signal['direction'] == 'UP' else "🔴"
    arrow = "📈" if signal['direction'] == 'UP' else "📉"
    
    msg = f"""
<b>━━━ 🎯 НОВАЯ СТАВКА ━━━</b>
🕐 {now.strftime('%H:%M:%S UTC')}

<b>💰 BTC: ${price:,.2f}</b>

<b>{emoji} СТАВКА: {signal['direction']} {arrow}</b>
📊 Уверенность: {signal['confidence']}%
💵 Сумма: ${bet_info['amount']:.2f} ({bet_info['percent']:.1f}%)

<b>⏱ Закрытие в: {close_time.strftime('%H:%M:%S UTC')}</b>
<i>(через 15 минут)</i>

<b>📈 Анализ:</b>
"""
    for reason in signal['reasons']:
        msg += f"{reason}\n"
    
    win_rate = (simulation['wins'] / simulation['total_bets'] * 100) if simulation['total_bets'] > 0 else 0
    
    msg += f"""
<b>💼 Баланс: ${simulation['balance']:.2f}</b>
📊 Ставок: {simulation['total_bets']} | Win: {simulation['wins']} | Loss: {simulation['losses']}
🎯 Win Rate: {win_rate:.1f}%
<b>━━━━━━━━━━━━━━━━━━━━━</b>
"""
    return msg


def format_close_bet_message(result, current_price):
    """Сообщение при закрытии ставки."""
    
    now = datetime.now(timezone.utc)
    
    if result['won']:
        status_emoji = "✅"
        status_text = "ВЫИГРЫШ"
        pnl_text = f"+${result['pnl']:.2f}"
    else:
        status_emoji = "❌"
        status_text = "ПРОИГРЫШ"
        pnl_text = f"-${abs(result['pnl']):.2f}"
    
    price_diff = result['exit_price'] - result['entry_price']
    price_percent = (price_diff / result['entry_price']) * 100
    
    win_rate = (simulation['wins'] / simulation['total_bets'] * 100) if simulation['total_bets'] > 0 else 0
    total_pnl = simulation['balance'] - STARTING_BALANCE
    
    msg = f"""
<b>━━━ {status_emoji} {status_text} ━━━</b>
🕐 {now.strftime('%H:%M:%S UTC')}

<b>Ставка: {result['direction']} {'📈' if result['direction'] == 'UP' else '📉'}</b>
📊 Уверенность была: {result['confidence']}%

<b>💵 Вход:</b> ${result['entry_price']:,.2f}
<b>💵 Выход:</b> ${result['exit_price']:,.2f}
<b>📊 Изменение:</b> {'+' if price_diff > 0 else ''}{price_diff:.2f} ({'+' if price_percent > 0 else ''}{price_percent:.3f}%)

<b>💰 P&L: {pnl_text}</b>

<b>━━━ 📊 СТАТИСТИКА ━━━</b>
💼 Баланс: ${simulation['balance']:.2f}
📈 Общий P&L: {'+' if total_pnl >= 0 else ''}${total_pnl:.2f} ({'+' if total_pnl >= 0 else ''}{(total_pnl/STARTING_BALANCE)*100:.1f}%)
🎯 Win Rate: {win_rate:.1f}% ({simulation['wins']}W / {simulation['losses']}L)
📋 Всего ставок: {simulation['total_bets']}
<b>━━━━━━━━━━━━━━━━━━━━━</b>
"""
    return msg


def format_status_message(price, signal):
    """Статус когда нет активной ставки и сигнал слабый."""
    
    now = datetime.now(timezone.utc)
    win_rate = (simulation['wins'] / simulation['total_bets'] * 100) if simulation['total_bets'] > 0 else 0
    total_pnl = simulation['balance'] - STARTING_BALANCE
    
    msg = f"""
<b>━━━ 📊 МОНИТОРИНГ ━━━</b>
🕐 {now.strftime('%H:%M:%S UTC')}

<b>💰 BTC: ${price:,.2f}</b>

<b>⏸ Сигнал слабый ({signal['confidence']}%)</b>
<i>Минимум для ставки: {MIN_CONFIDENCE}%</i>

Направление: {signal['direction']} {'📈' if signal['direction'] == 'UP' else '📉'}

<b>💼 Баланс: ${simulation['balance']:.2f}</b>
📈 P&L: {'+' if total_pnl >= 0 else ''}${total_pnl:.2f}
🎯 WR: {win_rate:.1f}% | {simulation['total_bets']} ставок
<b>━━━━━━━━━━━━━━━━━━━━━</b>
"""
    return msg


def format_waiting_message(price, bet, remaining):
    """Статус ожидания закрытия ставки."""
    
    now = datetime.now(timezone.utc)
    current_pnl = price - bet['entry_price']
    if bet['direction'] == 'DOWN':
        current_pnl = -current_pnl
    
    is_winning = current_pnl > 0
    
    msg = f"""
<b>━━━ ⏳ СТАВКА АКТИВНА ━━━</b>
🕐 {now.strftime('%H:%M:%S UTC')}

<b>💰 BTC: ${price:,.2f}</b>

<b>{'🟢' if bet['direction'] == 'UP' else '🔴'} {bet['direction']} {'📈' if bet['direction'] == 'UP' else '📉'}</b>
💵 Ставка: ${bet['amount']:.2f}
📊 Вход: ${bet['entry_price']:,.2f}

<b>{'✅' if is_winning else '❌'} Текущий P&L: {'+' if current_pnl > 0 else ''}{current_pnl:.2f}</b>

<b>⏱ Осталось: {remaining:.1f} мин</b>
<b>━━━━━━━━━━━━━━━━━━━━━</b>
"""
    return msg

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global price_history, last_signal_time
    
    print("🚀 Bitcoin Bot v3 (Polymarket Style) запущен!")
    print(f"⚙️ Минимальная уверенность: {MIN_CONFIDENCE}%")
    print(f"⚙️ Размер ставки: {MIN_BET_PERCENT}%-{MAX_BET_PERCENT}%")
    print(f"⚙️ Длительность: {BET_DURATION_MINUTES} минут")
    
    send_telegram(f"""🤖 <b>Bitcoin Bot v3 запущен!</b>

<b>Настройки:</b>
• Минимальная уверенность: {MIN_CONFIDENCE}%
• Размер ставки: {MIN_BET_PERCENT}%-{MAX_BET_PERCENT}%
• Длительность ставки: {BET_DURATION_MINUTES} мин
• Депозит: ${STARTING_BALANCE}

<i>Симуляция ставок в стиле Polymarket</i>
""")
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            print(f"\n[{now.strftime('%H:%M:%S')}] Проверка...")
            
            # Получаем данные
            price = get_btc_price()
            if price == 0:
                print("⚠️ Нет данных о цене")
                time.sleep(30)
                continue
            
            price_history.append(price)
            if len(price_history) > 200:
                price_history = price_history[-200:]
            
            candles = get_candles()
            buy_pressure = get_orderbook()
            
            # Рассчитываем сигнал
            signal = calculate_signal(price, candles, buy_pressure)
            
            # Проверяем активную ставку
            bet_result = check_and_close_bet(price)
            
            if bet_result:
                if bet_result['status'] == 'closed':
                    # Ставка закрылась — отправляем результат
                    msg = format_close_bet_message(bet_result, price)
                    send_telegram(msg)
                    print(f"{'✅ WIN' if bet_result['won'] else '❌ LOSS'}: {bet_result['pnl']:.2f}")
                    
                    # Сразу проверяем, можно ли открыть новую
                    time.sleep(2)
                    
                elif bet_result['status'] == 'active':
                    # Ставка ещё активна — отправляем статус каждые 5 минут
                    remaining = bet_result['remaining_minutes']
                    
                    # Отправляем апдейт каждые 5 минут
                    if remaining <= 10 and remaining > 9.5:
                        msg = format_waiting_message(price, simulation['active_bet'], remaining)
                        send_telegram(msg)
                    elif remaining <= 5 and remaining > 4.5:
                        msg = format_waiting_message(price, simulation['active_bet'], remaining)
                        send_telegram(msg)
                    elif remaining <= 1 and remaining > 0.5:
                        msg = format_waiting_message(price, simulation['active_bet'], remaining)
                        send_telegram(msg)
                    
                    print(f"⏳ Ставка активна, осталось {remaining:.1f} мин")
            
            # Если нет активной ставки — пробуем открыть
            if simulation['active_bet'] is None:
                if signal['confidence'] >= MIN_CONFIDENCE:
                    bet_info = open_bet(signal['direction'], signal['confidence'], price)
                    if bet_info:
                        msg = format_new_bet_message(price, signal, bet_info)
                        send_telegram(msg)
                        print(f"🎯 Открыта ставка: {signal['direction']} ${bet_info['amount']:.2f}")
                else:
                    # Отправляем статус каждые 15 минут если нет ставки
                    if last_signal_time is None or (now - last_signal_time).total_seconds() >= 900:
                        msg = format_status_message(price, signal)
                        send_telegram(msg)
                        last_signal_time = now
                        print(f"📊 Сигнал слабый: {signal['confidence']}%")
            
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            time.sleep(60)




if __name__ == "__main__":
    main()
