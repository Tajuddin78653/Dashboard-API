"""
Screener router — Chartink-like endpoints for TradeDash.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.services.screener_service import (
    run_screener, get_stock_indicators, backtest_screener,
    SUPPORTED_INDICATORS, SUPPORTED_PATTERNS,
)

router = APIRouter(tags=["screener"])

DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "WIPRO", "AXISBANK", "KOTAKBANK", "LT",
    "BAJFINANCE", "MARUTI", "HINDUNILVR", "ITC", "ONGC",
    "TECHM", "HCLTECH", "SUNPHARMA", "TATAMOTORS", "TITAN",
    "ADANIPORTS", "ULTRACEMCO", "NTPC", "POWERGRID", "BPCL",
    "TATASTEEL", "JSWSTEEL", "COALINDIA", "DRREDDY", "CIPLA",
]


class ConditionItem(BaseModel):
    indicator:  str | None = None
    operator:   str | None = None
    value:      float | None = None
    compare_to: str | None = None
    pattern:    str | None = None


class ScreenerRequest(BaseModel):
    symbols:    list[str] = Field(default_factory=list)
    conditions: list[ConditionItem]
    interval:   str = "1d"


class BacktestRequest(BaseModel):
    symbols:    list[str] = Field(default_factory=list)
    conditions: list[ConditionItem]
    period:     str = "1y"
    interval:   str = "1d"


@router.get("/screener/meta")
async def screener_meta():
    return {
        "indicators": [
            "close", "open", "high", "low", "volume", "vol_avg20",
            "ema9", "ema20", "ema50", "ema200", "sma20", "sma50",
            "rsi14", "macd_line", "macd_signal", "macd_hist",
        ],
        "patterns": SUPPORTED_PATTERNS,
        "operators": [">", ">=", "<", "<=", "==", "crosses_above", "crosses_below"],
        "intervals": ["1d", "1wk", "1mo", "60m", "15m"],
        "default_symbols": DEFAULT_SYMBOLS,
    }


@router.post("/screener/run")
async def run_screener_endpoint(req: ScreenerRequest):
    symbols = req.symbols or DEFAULT_SYMBOLS
    conditions = [c.model_dump(exclude_none=True) for c in req.conditions]
    if not conditions:
        raise HTTPException(status_code=400, detail="At least one condition is required")
    if len(symbols) > 100:
        raise HTTPException(status_code=400, detail="Max 100 symbols per scan")
    try:
        results = run_screener(symbols, conditions, interval=req.interval)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"scanned": len(symbols), "matched": len(results), "results": results}


@router.get("/screener/stock/{symbol}")
async def stock_indicators(symbol: str, interval: str = "1d"):
    data = get_stock_indicators(symbol.upper(), interval=interval)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
    return data


@router.post("/screener/backtest")
async def backtest_endpoint(req: BacktestRequest):
    symbols = req.symbols or DEFAULT_SYMBOLS[:10]
    conditions = [c.model_dump(exclude_none=True) for c in req.conditions]
    if not conditions:
        raise HTTPException(status_code=400, detail="At least one condition is required")
    if len(symbols) > 30:
        raise HTTPException(status_code=400, detail="Max 30 symbols for backtest")
    try:
        trades = backtest_screener(symbols, conditions, period=req.period, interval=req.interval)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    wins = [t for t in trades if t["result"] == "WIN"]
    total = len(trades)
    return {
        "total_signals": total,
        "wins": len(wins),
        "losses": total - len(wins),
        "win_rate": round(len(wins) / total * 100, 1) if total else 0,
        "avg_return_pct": round(sum(t["return_pct"] for t in trades) / total, 2) if total else 0,
        "trades": trades,
    }


@router.get("/screener/presets")
async def get_presets():
    return {
        "presets": [
            {
                "id": "rsi_oversold",
                "name": "RSI Oversold (< 30)",
                "description": "Stocks with RSI below 30 — potential reversal candidates",
                "conditions": [{"indicator": "rsi14", "operator": "<", "value": 30}],
            },
            {
                "id": "rsi_overbought",
                "name": "RSI Overbought (> 70)",
                "description": "Stocks with RSI above 70 — momentum or reversal warning",
                "conditions": [{"indicator": "rsi14", "operator": ">", "value": 70}],
            },
            {
                "id": "ema_crossover",
                "name": "EMA 9 > EMA 20 Crossover",
                "description": "Short-term EMA crossed above long-term — bullish signal",
                "conditions": [
                    {"indicator": "ema9", "operator": ">", "compare_to": "ema20"},
                    {"indicator": "close", "operator": ">", "compare_to": "ema50"},
                ],
            },
            {
                "id": "macd_bullish",
                "name": "MACD Bullish",
                "description": "MACD line above signal line with positive histogram",
                "conditions": [
                    {"indicator": "macd_line", "operator": ">", "compare_to": "macd_signal"},
                    {"indicator": "macd_hist", "operator": ">", "value": 0},
                ],
            },
            {
                "id": "golden_cross",
                "name": "Golden Cross (EMA50 > EMA200)",
                "description": "Long-term bullish trend — 50 EMA above 200 EMA",
                "conditions": [
                    {"indicator": "ema50", "operator": ">", "compare_to": "ema200"},
                    {"indicator": "close", "operator": ">", "compare_to": "ema50"},
                ],
            },
            {
                "id": "hammer_pattern",
                "name": "Hammer Candlestick",
                "description": "Bullish reversal hammer pattern detected",
                "conditions": [{"pattern": "HAMMER"}],
            },
            {
                "id": "bullish_engulfing",
                "name": "Bullish Engulfing",
                "description": "Strong bullish reversal pattern",
                "conditions": [{"pattern": "BULLISH_ENGULFING"}],
            },
            {
                "id": "volume_surge",
                "name": "Volume Surge + RSI > 50",
                "description": "High momentum stocks with bullish RSI",
                "conditions": [
                    {"indicator": "rsi14", "operator": ">", "value": 50},
                    {"indicator": "close", "operator": ">", "compare_to": "ema20"},
                ],
            },
        ]
    }
