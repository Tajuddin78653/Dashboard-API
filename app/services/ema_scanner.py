"""
EMA 13/50 Strict Crossover Scanner
===================================
Scans all ~180 NSE F&O stocks on 5-min chart.

BUY signal - ALL 3 must be true:
  1. Strict EMA crossover: prev_ema13 < prev_ema50  AND  curr_ema13 > curr_ema50
  2. MACD line > Signal line  (momentum bullish)
  3. RSI(14) strict cross above 50: prev_rsi < 50  AND  curr_rsi >= 50

SELL signal - ALL 3 must be true:
  1. Strict EMA crossover: prev_ema13 > prev_ema50  AND  curr_ema13 < curr_ema50
  2. MACD line < Signal line  (momentum bearish)
  3. RSI(14) strict cross below 50: prev_rsi > 50  AND  curr_rsi <= 50

Market trend gate (Advance/Decline of 50 Nifty-500 stocks):
  A/D ratio >= 1.2 -> BULLISH  -> show BUY signals only
  A/D ratio <= 0.8 -> BEARISH  -> show SELL signals only
  otherwise        -> SIDEWAYS -> show both

Auto-scan runs every 5 min during market hours via scheduler.
Results cached in Redis key "ema_scan:latest" with 10-min TTL.
Manual scan (off-market) hits run_ema_scanner() directly.
"""

from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

PERIOD   = "60d"
INTERVAL = "5m"
MIN_BARS = 60
REDIS_KEY = "ema_scan:latest"
REDIS_TTL = 600  # 10 minutes

FNO_SYMBOLS = [
    "AARTIIND","ABB","ABBOTINDIA","ABCAPITAL","ABFRL","ACC","ADANIENT",
    "ADANIPORTS","ALKEM","AMBUJACEM","ANGELONE","APLAPOLLO","APOLLOHOSP",
    "APOLLOTYRE","ASHOKLEY","ASIANPAINT","ASTRAL","ATUL","AUBANK",
    "AUROPHARMA","AXISBANK","BAJAJ-AUTO","BAJAJFINSV","BAJFINANCE",
    "BALKRISIND","BALRAMCHIN","BANDHANBNK","BANKBARODA","BATAINDIA",
    "BEL","BERGEPAINT","BHARATFORG","BHARTIARTL","BHEL","BIOCON",
    "BOSCHLTD","BPCL","BRITANNIA","BSOFT","CANBK","CANFINHOME",
    "CDSL","CESC","CGPOWER","CHAMBLFERT","CHOLAFIN","CIPLA",
    "COALINDIA","COFORGE","COLPAL","CONCOR","COROMANDEL","CUMMINSIND",
    "DABUR","DALBHARAT","DEEPAKNTR","DELTACORP","DIVISLAB","DIXON",
    "DLF","DRREDDY","EICHERMOT","ESCORTS","EXIDEIND","FEDERALBNK",
    "FINNIFTY","FORTIS","GAIL","GLENMARK","GMRINFRA","GNFC",
    "GODREJCP","GODREJPROP","GRANULES","GRASIM","GSPL","GUJGASLTD",
    "HAL","HAVELLS","HCLTECH","HDFCAMC","HDFCBANK","HDFCLIFE",
    "HEROMOTOCO","HINDALCO","HINDCOPPER","HINDPETRO","HINDUNILVR",
    "HONAUT","IBULHSGFIN","ICICIBANK","ICICIGI","ICICIPRULI",
    "IDEA","IDFCFIRSTB","IEX","IGL","INDHOTEL","INDIACEM",
    "INDIAMART","INDUSINDBK","INDUSTOWER","INFY","IOC","IPCALAB",
    "IRCTC","ITC","JINDALSTEL","JKCEMENT","JSWSTEEL","JUBLFOOD",
    "KOTAKBANK","KPITTECH","LALPATHLAB","LAURUSLABS","LICHSGFIN",
    "LT","LTIM","LTTS","LUPIN","M&M","M&MFIN","MANAPPURAM",
    "MARICO","MARUTI","MCDOWELL-N","MCX","METROPOLIS","MFSL",
    "MGL","MOTHERSON","MPHASIS","MRF","MUTHOOTFIN","NAM-INDIA",
    "NATIONALUM","NAUKRI","NAVINFLUOR","NESTLEIND","NMDC","NTPC",
    "OBEROIRLTY","OFSS","ONGC","PAGEIND","PEL","PERSISTENT",
    "PETRONET","PFC","PIDILITIND","PIIND","PNB","POLYCAB",
    "POWERGRID","PVRINOX","RAMCOCEM","RBLBANK","RECLTD","RELIANCE",
    "SAIL","SBICARD","SBILIFE","SBIN","SHREECEM","SHRIRAMFIN",
    "SIEMENS","SRF","SUNPHARMA","SUNTV","SUPREMEIND","SUZLON",
    "SYNGENE","TATACHEM","TATACOMM","TATACONSUM","TATAMOTORS",
    "TATAPOWER","TATASTEEL","TCS","TECHM","TITAN","TORNTPHARM",
    "TORNTPOWER","TRENT","TVSMOTOR","UBL","ULTRACEMCO","UPL",
    "VEDL","VOLTAS","WIPRO","ZOMATO","ZYDUSLIFE",
]

AD_SAMPLE = [
    "RELIANCE.NS","TCS.NS","INFY.NS","HDFCBANK.NS","ICICIBANK.NS",
    "BHARTIARTL.NS","SBIN.NS","BAJFINANCE.NS","LT.NS","HCLTECH.NS",
    "WIPRO.NS","AXISBANK.NS","MARUTI.NS","ASIANPAINT.NS","NTPC.NS",
    "KOTAKBANK.NS","TITAN.NS","SUNPHARMA.NS","POWERGRID.NS","TATAMOTORS.NS",
    "ADANIENT.NS","ADANIPORTS.NS","BAJAJFINSV.NS","COALINDIA.NS","ONGC.NS",
    "JSWSTEEL.NS","HINDALCO.NS","INDUSINDBK.NS","TATASTEEL.NS","ULTRACEMCO.NS",
    "GRASIM.NS","TECHM.NS","DRREDDY.NS","CIPLA.NS","DIVISLAB.NS",
    "BRITANNIA.NS","EICHERMOT.NS","BAJAJ-AUTO.NS","HEROMOTOCO.NS","TATACONSUM.NS",
    "ITC.NS","NESTLEIND.NS","APOLLOHOSP.NS","BPCL.NS","HINDUNILVR.NS",
    "M&M.NS","SBILIFE.NS","HDFCLIFE.NS","TRENT.NS","ZOMATO.NS",
]


def _fetch_ohlc(ticker: str) -> Optional[pd.DataFrame]:
    try:
        df = yf.download(ticker, interval=INTERVAL, period=PERIOD,
                         progress=False, auto_adjust=True, multi_level_index=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[[c for c in ["Open","High","Low","Close","Volume"] if c in df.columns]].copy()
        df.dropna(subset=["Close"], inplace=True)
        return df if len(df) >= MIN_BARS else None
    except Exception:
        return None


def _ema_series(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l = loss.ewm(com=period - 1, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd_series(close: pd.Series, fast=12, slow=26, sig=9):
    ema_f  = close.ewm(span=fast,  adjust=False).mean()
    ema_s  = close.ewm(span=slow,  adjust=False).mean()
    macd   = ema_f - ema_s
    signal = macd.ewm(span=sig, adjust=False).mean()
    return macd, signal


def _scan_one(symbol: str) -> dict:
    base = {
        "symbol": symbol, "signal": "NONE",
        "close": None, "ema13": None, "ema50": None,
        "rsi": None, "macd": None, "macd_signal": None,
        "error": None,
    }
    try:
        df = _fetch_ohlc(f"{symbol}.NS")
        if df is None:
            base["error"] = "no data"
            return base

        close = df["Close"]
        ema13 = _ema_series(close, 13)
        ema50 = _ema_series(close, 50)
        rsi   = _rsi_series(close, 14)
        macd_line, macd_sig = _macd_series(close)

        if len(ema13) < 2:
            base["error"] = "insufficient bars"
            return base

        curr_e13  = float(ema13.iloc[-1])
        prev_e13  = float(ema13.iloc[-2])
        curr_e50  = float(ema50.iloc[-1])
        prev_e50  = float(ema50.iloc[-2])
        curr_rsi  = float(rsi.iloc[-1])
        prev_rsi  = float(rsi.iloc[-2])
        curr_macd = float(macd_line.iloc[-1])
        curr_msig = float(macd_sig.iloc[-1])
        curr_px   = float(close.iloc[-1])

        base["close"]       = round(curr_px,   2)
        base["ema13"]       = round(curr_e13,  2)
        base["ema50"]       = round(curr_e50,  2)
        base["rsi"]         = round(curr_rsi,  2)
        base["macd"]        = round(curr_macd, 4)
        base["macd_signal"] = round(curr_msig, 4)

        buy_ema  = (prev_e13 < prev_e50) and (curr_e13 > curr_e50)
        buy_macd = curr_macd > curr_msig
        buy_rsi  = (prev_rsi < 50) and (curr_rsi >= 50)

        sel_ema  = (prev_e13 > prev_e50) and (curr_e13 < curr_e50)
        sel_macd = curr_macd < curr_msig
        sel_rsi  = (prev_rsi > 50) and (curr_rsi <= 50)

        if buy_ema and buy_macd and buy_rsi:
            base["signal"] = "BUY"
        elif sel_ema and sel_macd and sel_rsi:
            base["signal"] = "SELL"

    except Exception as e:
        base["error"] = str(e)[:80]
    return base


def _get_ad_trend() -> str:
    """Advance/Decline ratio -> BULLISH / BEARISH / SIDEWAYS."""
    try:
        data = yf.download(" ".join(AD_SAMPLE), period="2d", interval="1d",
                           progress=False, auto_adjust=True, multi_level_index=False)
        if data.empty:
            return "SIDEWAYS"
        if isinstance(data.columns, pd.MultiIndex):
            close = data.xs("Close", axis=1, level=0)
        else:
            close = data[["Close"]] if "Close" in data.columns else None
        if close is None:
            return "SIDEWAYS"
        adv = dec = 0
        for col in close.columns:
            s = close[col].dropna()
            if len(s) < 2:
                continue
            chg = float(s.iloc[-1]) - float(s.iloc[-2])
            if chg > 0.01:
                adv += 1
            elif chg < -0.01:
                dec += 1
        ratio = adv / dec if dec > 0 else 9.99
        if ratio >= 1.2:
            return "BULLISH"
        if ratio <= 0.8:
            return "BEARISH"
        return "SIDEWAYS"
    except Exception:
        return "SIDEWAYS"


async def run_ema_scanner() -> dict:
    """
    Run EMA 13/50 strict crossover scan on all F&O stocks.
    Returns triggered BUY and SELL stocks + market trend.
    Called by scheduler (auto) and POST /scanner/run (manual).
    Result is cached to Redis automatically.
    """
    loop = asyncio.get_event_loop()

    market_trend = await loop.run_in_executor(None, _get_ad_trend)
    tasks   = [loop.run_in_executor(None, _scan_one, sym) for sym in FNO_SYMBOLS]
    results = await asyncio.gather(*tasks)

    buy_signals  = []
    sell_signals = []

    for r in results:
        if r["signal"] == "BUY":
            buy_signals.append(r)
        elif r["signal"] == "SELL":
            sell_signals.append(r)

    if market_trend == "BULLISH":
        sell_signals = []
    elif market_trend == "BEARISH":
        buy_signals  = []

    result = {
        "market_trend":  market_trend,
        "total_scanned": len(FNO_SYMBOLS),
        "buy_count":     len(buy_signals),
        "sell_count":    len(sell_signals),
        "buy_signals":   buy_signals,
        "sell_signals":  sell_signals,
        "scan_errors":   sum(1 for r in results if r.get("error") and r["signal"] == "NONE"),
        "scanned_at":    datetime.now(timezone.utc).isoformat(),
    }

    # Cache to Redis (non-fatal)
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        await redis.set(REDIS_KEY, json.dumps(result))
        await redis.expire(REDIS_KEY, REDIS_TTL)
        logger.info("EMA scan cached to Redis: %d BUY, %d SELL, trend=%s",
                    result["buy_count"], result["sell_count"], market_trend)
    except Exception as e:
        logger.warning("EMA scan Redis cache failed: %s", e)

    return result


async def get_cached_scan() -> Optional[dict]:
    """Load latest scan result from Redis. Returns None if no cache."""
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        raw = await redis.get(REDIS_KEY)
        if raw:
            return json.loads(raw)
        return None
    except Exception as e:
        logger.warning("EMA scan Redis read failed: %s", e)
        return None