"""
Chartink-style stock screener engine.
Fetches live OHLCV data via yfinance, computes indicators,
and evaluates user-defined scan conditions.
"""
from __future__ import annotations

import logging
from typing import Any

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

_SUFFIX = ".NS"

SUPPORTED_INDICATORS = ["EMA", "SMA", "RSI", "MACD", "VOLUME", "CLOSE", "OPEN", "HIGH", "LOW"]
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


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


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

    return {
        "symbol": symbol,
        "close": round(float(close.iloc[-1]), 2),
        "open": round(float(df["Open"].squeeze().iloc[-1]), 2),
        "high": round(float(df["High"].squeeze().iloc[-1]), 2),
        "low": round(float(df["Low"].squeeze().iloc[-1]), 2),
        "volume": int(volume.iloc[-1]),
        "ema9":   round(float(_ema(close, 9).iloc[-1]), 2),
        "ema20":  round(float(_ema(close, 20).iloc[-1]), 2),
        "ema50":  round(float(_ema(close, 50).iloc[-1]), 2),
        "ema200": round(float(_ema(close, 200).iloc[-1]), 2),
        "sma20":  round(float(_sma(close, 20).iloc[-1]), 2),
        "sma50":  round(float(_sma(close, 50).iloc[-1]), 2),
        "rsi14":  round(float(_rsi(close, 14).iloc[-1]), 2),
        "macd_line":   round(float(_macd(close)[0].iloc[-1]), 4),
        "macd_signal": round(float(_macd(close)[1].iloc[-1]), 4),
        "macd_hist":   round(float(_macd(close)[2].iloc[-1]), 4),
        "vol_avg20":   int(_sma(volume.astype(float), 20).iloc[-1]),
        "patterns": _detect_patterns(df),
    }


def _evaluate_condition(data: dict[str, Any], condition: dict[str, Any]) -> bool:
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

    ops = {
        ">": lhs > rhs, ">=": lhs >= rhs, "<": lhs < rhs, "<=": lhs <= rhs,
        "==": abs(lhs - rhs) < 0.001, "crosses_above": lhs > rhs, "crosses_below": lhs < rhs,
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
