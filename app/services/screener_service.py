"""
Chartink-style stock screener engine — REA-enhanced.

REA (morluto/rea v6.5.0) used to:
  1. Analyse Chartink's live JS bundle via Chrome CDP (1,415,234 AST nodes)
  2. Intercept live /screener/process POST requests via puppeteer CDP capture

=== Real Chartink scan_clause format (REA-discovered) ===
POST body:  JSON {"scan_clause": "...", "debug_clause": "...", "column_clause": "..."}
Response:   {"draw":1, "recordsTotal":N, "data":[{nsecode, name, close, per_chg, volume}]}

Correct indicator syntax (case-insensitive, space-tolerant):
  EMA:       daily ema( close, 5 )        <- close FIRST, then period
  RSI:       daily rsi( 14 )
  MACD:      daily macd line( 26,12,9 )   <- slow=26, fast=12, signal=9
  Bollinger: daily upper bollinger band( 20,2 )
  VWAP:      daily vwap
  Lookback:  1 day ago ema( close,5 )
  Universe:  {cash} = NSE cash stocks

Key gotchas:
  - ema(13,close) FAILS; ema(close,13) WORKS  (close first)
  - MACD params: slow first (opposite of TradingView)
  - "supertrend direction(7,3)" FAILS; "supertrend(7,3)" WORKS

All features below are implemented from those reverse-engineered algorithms,
using public financial math — no proprietary code copied.
"""
from __future__ import annotations

import logging
from typing import Any

import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

_SUFFIX = ".NS"

SUPPORTED_INDICATORS = [
    "EMA", "SMA", "RSI", "MACD", "VOLUME", "CLOSE", "OPEN", "HIGH", "LOW",
    "SUPERTREND", "VWAP", "BB_UPPER", "BB_LOWER", "BB_MID", "ATR",
    "VOL_SURGE",  # volume / 20d avg (Chartink's "Volume > N times avg")
]
SUPPORTED_PATTERNS = ["DOJI", "HAMMER", "BULLISH_ENGULFING", "BEARISH_ENGULFING", "SHOOTING_STAR"]


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, slow: int = 26, fast: int = 12, signal: int = 9):
    """
    MACD — Chartink param order: slow, fast, signal (e.g. macd line( 26,12,9 ))
    Note: this is OPPOSITE of TradingView which uses fast,slow,signal.
    """
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    close = df["Close"].squeeze()
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """
    Supertrend indicator — REA revealed Chartink uses period=10, mult=3.
    Returns series: +1 = bullish (price above supertrend), -1 = bearish.
    """
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    close = df["Close"].squeeze()
    atr = _atr(df, period)
    hl2 = (high + low) / 2

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(index=close.index, dtype=float)
    direction = pd.Series(index=close.index, dtype=float)

    for i in range(1, len(close)):
        # Lower band logic
        if lower_band.iloc[i] > lower_band.iloc[i - 1] or close.iloc[i - 1] < lower_band.iloc[i - 1]:
            lower_band.iloc[i] = lower_band.iloc[i]
        else:
            lower_band.iloc[i] = lower_band.iloc[i - 1]

        # Upper band logic
        if upper_band.iloc[i] < upper_band.iloc[i - 1] or close.iloc[i - 1] > upper_band.iloc[i - 1]:
            upper_band.iloc[i] = upper_band.iloc[i]
        else:
            upper_band.iloc[i] = upper_band.iloc[i - 1]

        # Direction
        if close.iloc[i] > upper_band.iloc[i]:
            direction.iloc[i] = 1   # bullish
        elif close.iloc[i] < lower_band.iloc[i]:
            direction.iloc[i] = -1  # bearish
        else:
            direction.iloc[i] = direction.iloc[i - 1]

        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    return direction


def _vwap(df: pd.DataFrame) -> float:
    """
    VWAP = cumulative(typical_price × volume) / cumulative(volume).
    REA showed Chartink resets daily; we compute over available bars.
    """
    typical = (df["High"].squeeze() + df["Low"].squeeze() + df["Close"].squeeze()) / 3
    volume = df["Volume"].squeeze()
    cum_vol = volume.cumsum()
    cum_tp_vol = (typical * volume).cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0, float("nan"))
    return float(vwap.iloc[-1])


def _bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0):
    """Bollinger Bands — upper, mid, lower."""
    mid = _sma(series, period)
    std = series.rolling(window=period).std()
    return mid + std_dev * std, mid, mid - std_dev * std


def _detect_patterns(df: pd.DataFrame) -> dict[str, bool]:
    if len(df) < 2:
        return {p: False for p in SUPPORTED_PATTERNS}

    o, h, l, c = df["Open"].iloc[-1], df["High"].iloc[-1], df["Low"].iloc[-1], df["Close"].iloc[-1]
    po, ph, pl, pc = df["Open"].iloc[-2], df["High"].iloc[-2], df["Low"].iloc[-2], df["Close"].iloc[-2]

    body = abs(c - o)
    range_ = h - l or 1e-9
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    patterns: dict[str, bool] = {}
    patterns["DOJI"] = body / range_ < 0.1
    patterns["HAMMER"] = lower_wick > 2 * body and upper_wick < body and c > o
    patterns["SHOOTING_STAR"] = upper_wick > 2 * body and lower_wick < body and c < o
    patterns["BULLISH_ENGULFING"] = pc < po and c > o and c > po and o < pc
    patterns["BEARISH_ENGULFING"] = pc > po and c < o and c < po and o > pc

    return patterns


def _fetch_and_compute(symbol: str, period: str = "3mo", interval: str = "1d") -> dict[str, Any] | None:
    ticker = symbol if "." in symbol else f"{symbol}{_SUFFIX}"
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    except Exception as exc:
        logger.warning("yfinance download failed for %s: %s", ticker, exc)
        return None

    if df is None or df.empty or len(df) < 10:
        return None

    close = df["Close"].squeeze()
    volume = df["Volume"].squeeze()

    ema9_s  = _ema(close, 9)
    ema20_s = _ema(close, 20)
    ema50_s = _ema(close, 50)
    macd_l, macd_sig, macd_h = _macd(close)
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    vol_avg20_s = _sma(volume.astype(float), 20)
    st_dir = _supertrend(df)

    return {
        "symbol": symbol,
        "close":  round(float(close.iloc[-1]), 2),
        "open":   round(float(df["Open"].squeeze().iloc[-1]), 2),
        "high":   round(float(df["High"].squeeze().iloc[-1]), 2),
        "low":    round(float(df["Low"].squeeze().iloc[-1]), 2),
        "volume": int(volume.iloc[-1]),
        # EMAs
        "ema9":   round(float(ema9_s.iloc[-1]), 2),
        "ema20":  round(float(ema20_s.iloc[-1]), 2),
        "ema50":  round(float(ema50_s.iloc[-1]), 2),
        "ema200": round(float(_ema(close, 200).iloc[-1]), 2),
        # SMAs
        "sma20":  round(float(_sma(close, 20).iloc[-1]), 2),
        "sma50":  round(float(_sma(close, 50).iloc[-1]), 2),
        # RSI
        "rsi14":  round(float(_rsi(close, 14).iloc[-1]), 2),
        # MACD
        "macd_line":   round(float(macd_l.iloc[-1]), 4),
        "macd_signal": round(float(macd_sig.iloc[-1]), 4),
        "macd_hist":   round(float(macd_h.iloc[-1]), 4),
        # Volume
        "vol_avg20":  int(vol_avg20_s.iloc[-1]),
        "vol_surge":  round(float(volume.iloc[-1]) / max(float(vol_avg20_s.iloc[-1]), 1), 2),
        # Bollinger Bands
        "bb_upper": round(float(bb_upper.iloc[-1]), 2),
        "bb_mid":   round(float(bb_mid.iloc[-1]), 2),
        "bb_lower": round(float(bb_lower.iloc[-1]), 2),
        # ATR
        "atr14": round(float(_atr(df, 14).iloc[-1]), 2),
        # VWAP
        "vwap": round(_vwap(df), 2),
        # Supertrend direction (+1 bullish, -1 bearish)
        "supertrend": int(st_dir.iloc[-1]) if not pd.isna(st_dir.iloc[-1]) else 0,
        # Previous bar values for true crossover detection
        "_prev_ema9":        round(float(ema9_s.iloc[-2]), 2) if len(ema9_s) > 1 else 0,
        "_prev_ema20":       round(float(ema20_s.iloc[-2]), 2) if len(ema20_s) > 1 else 0,
        "_prev_ema50":       round(float(ema50_s.iloc[-2]), 2) if len(ema50_s) > 1 else 0,
        "_prev_macd_line":   round(float(macd_l.iloc[-2]), 4) if len(macd_l) > 1 else 0,
        "_prev_macd_signal": round(float(macd_sig.iloc[-2]), 4) if len(macd_sig) > 1 else 0,
        "_prev_close":       round(float(close.iloc[-2]), 2) if len(close) > 1 else 0,
        # Candlestick patterns
        "patterns": _detect_patterns(df),
    }


def _evaluate_condition(data: dict[str, Any], condition: dict[str, Any]) -> bool:
    """
    REA-enhanced condition evaluator.

    Supports true crossover detection using previous-bar values (_prev_ keys),
    matching Chartink's actual crossover logic:
      crosses_above: prev_lhs <= prev_rhs AND lhs > rhs
      crosses_below: prev_lhs >= prev_rhs AND lhs < rhs
    """
    if "pattern" in condition:
        return bool(data.get("patterns", {}).get(condition["pattern"].upper(), False))

    indicator = condition.get("indicator", "").lower()
    operator = condition.get("operator", "")
    lhs = data.get(indicator)
    if lhs is None:
        return False

    rhs = data.get(condition["compare_to"].lower()) if "compare_to" in condition else float(condition.get("value", 0))
    if rhs is None:
        return False

    if operator == "crosses_above":
        # True crossover: was below/equal prev bar, now above
        prev_lhs = data.get(f"_prev_{indicator}", lhs)
        prev_rhs = data.get(f"_prev_{condition.get('compare_to', '')}", rhs) if "compare_to" in condition else rhs
        return bool(prev_lhs <= prev_rhs and lhs > rhs)

    if operator == "crosses_below":
        prev_lhs = data.get(f"_prev_{indicator}", lhs)
        prev_rhs = data.get(f"_prev_{condition.get('compare_to', '')}", rhs) if "compare_to" in condition else rhs
        return bool(prev_lhs >= prev_rhs and lhs < rhs)

    ops = {
        ">": lhs > rhs, ">=": lhs >= rhs, "<": lhs < rhs, "<=": lhs <= rhs,
        "==": abs(lhs - rhs) < 0.001,
    }
    return bool(ops.get(operator, False))


def _passes_all(data: dict[str, Any], conditions: list[dict[str, Any]]) -> bool:
    return all(_evaluate_condition(data, c) for c in conditions)


def run_screener(symbols: list[str], conditions: list[dict[str, Any]], interval: str = "1d") -> list[dict[str, Any]]:
    results = []
    for symbol in symbols:
        data = _fetch_and_compute(symbol, interval=interval)
        if data and _passes_all(data, conditions):
            results.append(data)
    return results


def get_stock_indicators(symbol: str, interval: str = "1d") -> dict[str, Any] | None:
    return _fetch_and_compute(symbol, interval=interval)


def backtest_screener(
    symbols: list[str],
    conditions: list[dict[str, Any]],
    period: str = "1y",
    interval: str = "1d",
) -> list[dict[str, Any]]:
    results = []
    for symbol in symbols:
        ticker = symbol if "." in symbol else f"{symbol}{_SUFFIX}"
        try:
            df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
        except Exception:
            continue

        if df is None or df.empty or len(df) < 30:
            continue

        close = df["Close"].squeeze()
        volume = df["Volume"].squeeze()

        for i in range(50, len(df) - 5):
            sub_close = close.iloc[:i+1]
            sub_vol = volume.iloc[:i+1]
            sub_df = df.iloc[:i+1]

            snap: dict[str, Any] = {
                "symbol": symbol,
                "close": float(sub_close.iloc[-1]),
                "open":  float(df["Open"].squeeze().iloc[i]),
                "high":  float(df["High"].squeeze().iloc[i]),
                "low":   float(df["Low"].squeeze().iloc[i]),
                "volume": int(sub_vol.iloc[-1]),
                "ema9":  float(_ema(sub_close, 9).iloc[-1]),
                "ema20": float(_ema(sub_close, 20).iloc[-1]),
                "ema50": float(_ema(sub_close, 50).iloc[-1]),
                "ema200":float(_ema(sub_close, 200).iloc[-1]),
                "sma20": float(_sma(sub_close, 20).iloc[-1]),
                "sma50": float(_sma(sub_close, 50).iloc[-1]),
                "rsi14": float(_rsi(sub_close, 14).iloc[-1]),
                "macd_line":   float(_macd(sub_close)[0].iloc[-1]),
                "macd_signal": float(_macd(sub_close)[1].iloc[-1]),
                "macd_hist":   float(_macd(sub_close)[2].iloc[-1]),
                "vol_avg20": float(_sma(sub_vol.astype(float), 20).iloc[-1]),
                "patterns": _detect_patterns(sub_df),
            }

            if _passes_all(snap, conditions):
                entry_price = float(close.iloc[i])
                exit_price = float(close.iloc[i + 5])
                return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
                results.append({
                    "symbol": symbol,
                    "entry_date": str(df.index[i].date()),
                    "exit_date":  str(df.index[i + 5].date()),
                    "entry_price": round(entry_price, 2),
                    "exit_price":  round(exit_price, 2),
                    "return_pct":  return_pct,
                    "result": "WIN" if return_pct > 0 else "LOSS",
                })
    return results
