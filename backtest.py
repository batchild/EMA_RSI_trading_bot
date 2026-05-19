import ccxt
import pandas as pd
import numpy as np
import time
import requests
from datetime import datetime, timezone

# ============================================================================
# ⚙️ BOT CONFIGURATION
# ============================================================================
# Replace these strings with your authentic Telegram parameters
TELEGRAM_BOT_TOKEN = "8826088133:AAFXS4c08N9OAFSjWH0jBd8kek74e0no2xU"
TELEGRAM_CHAT_ID = "@EMA_RSI_Btrading_bot"  # Channel username (e.g., '@mychannel') or channel numerical ID

# The exact 11 target pairs you requested
TARGET_PAIRS = [
    'INTC/USDT:USDT',
    'ZEC/USDT:USDT',
    'TRX/USDT:USDT',
    'BSB/USDT:USDT',
    'ENA/USDT:USDT',
    'SUI/USDT:USDT',
    'ADA/USDT:USDT',
    'DOGE/USDT:USDT',
    'BTC/USDT:USDT',
    'XRP/USDT:USDT',
    'HYPE/USDT:USDT'
]

TIMEFRAME = '15m'
RR_RATIO = 3.3
POLLING_INTERVAL_SECONDS = 30  # Frequency of checking for closed candles

# ============================================================================
# TECHNICAL ANALYSIS ENGINE (Identical to your setup)
# ============================================================================
class TechnicalAnalyzer:
    @staticmethod
    def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
        if len(prices) < period:
            return np.full_like(prices, np.nan, dtype=float)
        ema = np.full_like(prices, np.nan, dtype=float)
        multiplier = 2.0 / (period + 1)
        ema[period - 1] = np.mean(prices[:period])
        for i in range(period, len(prices)):
            ema[i] = (prices[i] * multiplier) + (ema[i - 1] * (1 - multiplier))
        return ema

    @staticmethod
    def calculate_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
        if len(prices) < period + 1:
            return np.full_like(prices, np.nan, dtype=float)
        rsi = np.full_like(prices, np.nan, dtype=float)
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi[period] = 100 - (100 / (1 + rs)) if rs > 0 else 0
        for i in range(period + 1, len(prices)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            rs = avg_gain / avg_loss if avg_loss != 0 else 0
            rsi[i] = 100 - (100 / (1 + rs)) if rs > 0 else 0
        return rsi

# ============================================================================
# TELEGRAM DISPATCHER
# ============================================================================
def send_telegram_alert(message: str):
    """Dispatches a formatted payload directly to your Telegram bot or channel channel."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("🚀 Signal successfully transmitted to Telegram.")
        else:
            print(f"❌ Telegram API Error: {response.text}")
    except Exception as e:
        print(f"⚠️ Network error while dispatching to Telegram: {e}")

# ============================================================================
# LIVE EXECUTION CORE
# ============================================================================
def run_live_scanner():
    # Instantiates specific connection to Binance USDT-M Perpetual Markets
    exchange = ccxt.binanceusdm({'enableRateLimit': True})
    print(f"🤖 Live Trading Monitor Active. Monitoring {len(TARGET_PAIRS)} pairs on {TIMEFRAME} chart...")
    
    # State tracking object: stops duplicate notifications inside the same 15-minute window
    # Stores format: { "BTC/USDT:USDT": timestamp }
    last_alerted_candles = {}

    while True:
        for symbol in TARGET_PAIRS:
            try:
                # Pull 300 historical candles (gives comfortable data overhead for accurate EMA200 calculation)
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=300)
                if len(ohlcv) < 210:
                    continue
                
                # IMPORTANT FOR LIVE BOTS: 
                # ohlcv[-1] represents the current, live, fluctuating open candle.
                # ohlcv[-2] represents the LAST COMPLETED, FIXED candle.
                # To prevent fake signals, we evaluate indicators exclusively at index -2.
                trigger_candle = ohlcv[-2]
                candle_timestamp = trigger_candle[0] 
                
                # Check if this specific closed candle was already processed and notified
                if last_alerted_candles.get(symbol) == candle_timestamp:
                    continue
                
                # Convert past arrays into processable numpy types
                closes = np.array([candle[4] for candle in ohlcv], dtype=float)
                highs = np.array([candle[2] for candle in ohlcv], dtype=float)
                lows = np.array([candle[3] for candle in ohlcv], dtype=float)
                
                # Calculate indicator frames
                ema_200 = TechnicalAnalyzer.calculate_ema(closes, period=200)
                rsi_14 = TechnicalAnalyzer.calculate_rsi(closes, period=14)
                
                # Extract values specific to the frozen candle index (-2)
                close_p = closes[-2]
                ema_p = ema_200[-2]
                rsi_p = rsi_14[-2]
                
                if np.isnan(ema_p) or np.isnan(rsi_p):
                    continue

                # Isolate the last 3 closed candles (indices -4, -3, and -2) to locate stop-loss benchmarks
                last_3_lows = lows[-4:-1]
                last_3_highs = highs[-4:-1]
                
                signal_detected = False
                direction = ""
                entry_price = close_p
                sl = 0.0
                tp = 0.0

                # 🟢 Evaluate LONG Setup Conditions
                if close_p > ema_p and rsi_p < 30:
                    sl = float(min(last_3_lows))
                    risk = entry_price - sl
                    if risk > 0:
                        tp = entry_price + (risk * RR_RATIO)
                        direction = "LONG 🟢"
                        signal_detected = True

                # 🔴 Evaluate SHORT Setup Conditions
                elif close_p < ema_p and rsi_p > 70:
                    sl = float(max(last_3_highs))
                    risk = sl - entry_price
                    if risk > 0:
                        tp = entry_price - (risk * RR_RATIO)
                        direction = "SHORT 🔴"
                        signal_detected = True

                # Dispatch notification if parameters sync up perfectly
                if signal_detected:
                    human_readable_time = datetime.fromtimestamp(candle_timestamp / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                    
                    # Clean format using markdown syntax
                    alert_msg = (
                        f"🚨 *NEW STRATEGY SIGNAL DETECTED* 🚨\n\n"
                        f"• *Asset:* `{symbol.split(':')[0]}` (Perpetual)\n"
                        f"• *Direction:* {direction}\n"
                        f"• *Timeframe:* {TIMEFRAME}\n\n"
                        f"🔹 *Fixed Entry Price:* `{entry_price:,.5f}`\n"
                        f"🛑 *Stop Loss (3-Candle):* `{sl:,.5f}`\n"
                        f"🎯 *Take Profit ({RR_RATIO}R):* `{tp:,.5f}`\n\n"
                        f"⏰ *Closed Trigger Candle Time:* {human_readable_time}"
                    )
                    
                    print(f"🎯 Signal spotted for {symbol}! Dispatching details...")
                    send_telegram_alert(alert_msg)
                    
                    # Lock this candle to ensure it never alerts again
                    last_alerted_candles[symbol] = candle_timestamp

            except Exception as e:
                # Safeguards processing loop if connectivity issues affect a single token
                print(f"⚠️ Transient issue tracking {symbol}: {e}")
        
        # Idle processing to optimize CPU usage and respect rate limits
        time.sleep(POLLING_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        run_live_scanner()
    except KeyboardInterrupt:
        print("\nStopping bot framework execution gracefully...")