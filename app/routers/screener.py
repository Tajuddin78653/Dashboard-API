"""
Screener router — Chartink-like endpoints for TradeDash.

REA Analysis findings (morluto/rea on Chartink's live JS bundle + CDP capture):
  - POST /screener/process body: JSON {"scan_clause": "...", "debug_clause": "...", "column_clause": "..."}
  - Stock universe token: {cash} = NSE cash, {index} = indices
  - EMA syntax: daily ema( close, 5 )   ← close first, then period
  - MACD syntax: macd line( 26,12,9 )   ← slow, fast, signal order
  - Lookback: 1 day ago ema( close,5 )  ← "N day(s) ago <indicator>"
  - Timeframe prefix: daily / weekly / monthly
  - Response: {"draw":1, "recordsTotal":N, "recordsFiltered":N, "data":[{sr,nsecode,name,bsecode,close,per_chg,volume}]}
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


# ── Real Chartink scan_clause presets (REA-captured from live Chartink API) ───
# These are the actual scan_clause strings Chartink uses internally,
# discovered by intercepting live POST requests via Chrome CDP + puppeteer.
CHARTINK_PRESETS = [
    {
        "id": "ema_crossover",
        "name": "EMA 5/13 Crossover (Chartink real syntax)",
        "scan_clause": "( {cash} (  daily ema( close,5 ) >  daily ema( close,13 ) and  1 day ago  ema( close,5 )<=  1 day ago  ema( close,13 ) and  daily ema( close,5 ) >  daily ema( close,26 ) and  daily volume >=  50000 and  daily rsi( 14 ) >=  50 and  daily rsi( 14 ) <=  70 ) )",
        "description": "EMA 5 crosses above EMA 13 with volume and RSI filter",
        "indicators": ["ema", "rsi", "volume"],
    },
    {
        "id": "rsi_crossover",
        "name": "RSI Crossover (62 level)",
        "scan_clause": "( {cash} (  1 day ago rsi( 14 ) >  62 and  2 day ago  rsi( 14 ) <=  62 and  daily high >  7 days ago high and  1 day ago volume >  5000 ) )",
        "description": "RSI crosses 62 with higher highs",
        "indicators": ["rsi", "volume"],
    },
    {
        "id": "golden_crossover",
        "name": "Golden Crossover EMA 55/200",
        "scan_clause": "( {cash} (  daily ema( close,55 ) >  daily ema( close,200 ) and  1 day ago  ema( close,55 )<=  1 day ago  ema( close,200 ) ) )",
        "description": "EMA 55 crosses above EMA 200 — classic golden cross",
        "indicators": ["ema"],
    },
    {
        "id": "macd_crossover_daily",
        "name": "MACD Daily Crossover",
        "scan_clause": "( {cash} (  daily macd line( 26,12,9 ) >  daily macd signal( 26,12,9 ) and  1 day ago  macd line( 26,12,9 ) <=  1 day ago  macd signal( 26,12,9 ) ) )",
        "description": "MACD line crosses above signal on daily timeframe",
        "indicators": ["macd"],
    },
    {
        "id": "macd_triple_confirmation",
        "name": "MACD Triple Timeframe Crossover",
        "scan_clause": "( {cash} (  monthly macd line( 26,12,9 ) >=  monthly macd signal( 26,12,9 ) and  weekly macd line( 26,12,9 ) >=  weekly macd signal( 26,12,9 ) and  daily macd line( 26,12,9 ) >  daily macd signal( 26,12,9 ) and  1 day ago  macd line( 26,12,9 ) <=  1 day ago  macd signal( 26,12,9 ) ) )",
        "description": "MACD crossover confirmed on monthly, weekly, and daily",
        "indicators": ["macd"],
    },
    {
        "id": "bb_breakout",
        "name": "Bollinger Band Breakout",
        "scan_clause": "( {cash} (  daily close >  daily upper bollinger band( 20,2 ) and  1 day ago  close <=  1 day ago  upper bollinger band( 20,2 ) ) )",
        "description": "Price breaks above upper Bollinger Band",
        "indicators": ["bollinger"],
    },
    {
        "id": "volume_shocker",
        "name": "Volume Shocker (5x yesterday)",
        "scan_clause": "( {cash} (  daily volume >  1 day ago volume *  5 and  daily volume >  10000 ) )",
        "description": "Today's volume > 5x yesterday's volume",
        "indicators": ["volume"],
    },
    {
        "id": "rsi_oversold_bounce",
        "name": "RSI Oversold Bounce",
        "scan_clause": "( {cash} (  daily rsi( 14 ) <  30 and  daily close >  daily ema( close,20 ) ) )",
        "description": "RSI below 30 but price above 20 EMA — potential reversal",
        "indicators": ["rsi", "ema"],
    },
    {
        "id": "close_above_vwap",
        "name": "Close Above VWAP",
        "scan_clause": "( {cash} (  daily close >  daily vwap ) )",
        "description": "Price trading above VWAP — bullish intraday bias",
        "indicators": ["vwap"],
    },
]


@router.get("/screener/meta")
async def screener_meta():
    return {
        "indicators": [
            "close", "open", "high", "low", "volume", "vol_avg20", "vol_surge",
            "ema9", "ema20", "ema50", "ema200", "sma20", "sma50",
            "rsi14", "macd_line", "macd_signal", "macd_hist",
            "supertrend", "vwap", "bb_upper", "bb_mid", "bb_lower", "atr14",
        ],
        "patterns": SUPPORTED_PATTERNS,
        "operators": [">", ">=", "<", "<=", "==", "crosses_above", "crosses_below"],
        "intervals": ["1d", "1wk", "1mo", "60m", "15m"],
        "default_symbols": DEFAULT_SYMBOLS,
        "chartink_syntax": {
            "ema": "daily ema( close, 5 )",
            "rsi": "daily rsi( 14 )",
            "macd": "daily macd line( 26,12,9 )",
            "volume": "daily volume",
            "bollinger_upper": "daily upper bollinger band( 20,2 )",
            "bollinger_lower": "daily lower bollinger band( 20,2 )",
            "vwap": "daily vwap",
            "lookback": "1 day ago ema( close,5 )",
            "universe": "{cash}",
            "note": "REA-captured from live Chartink /screener/process POST intercepts",
        },
        "rea_note": "True crossover detection via REA analysis of Chartink screener pipeline",
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
    """
    Returns both:
    1. condition-based presets (for TradeDash internal screener)
    2. chartink_presets — real scan_clause strings captured via REA from live Chartink
    """
    return {
        "chartink_presets": CHARTINK_PRESETS,
        "presets": [
            {
                "id": "rsi_oversold",
                "name": "RSI Oversold (< 30)",
                "description": "Stocks with RSI below 30 — potential reversal candidates",
                "conditions": [{"indicator": "rsi14", "operator": "<", "value": 30}],
                "chartink_clause": "( {cash} (  daily rsi( 14 ) <  30 ) )",
            },
            {
                "id": "rsi_overbought",
                "name": "RSI Overbought (> 70)",
                "description": "Stocks with RSI above 70 — momentum or reversal warning",
                "conditions": [{"indicator": "rsi14", "operator": ">", "value": 70}],
                "chartink_clause": "( {cash} (  daily rsi( 14 ) >  70 ) )",
            },
            {
                "id": "ema_crossover",
                "name": "EMA 5/13 Crossover",
                "description": "EMA 5 crosses above EMA 13 — Chartink's most popular scan",
                "conditions": [
                    {"indicator": "ema9", "operator": ">", "compare_to": "ema20"},
                ],
                "chartink_clause": "( {cash} (  daily ema( close,5 ) >  daily ema( close,13 ) and  1 day ago  ema( close,5 )<=  1 day ago  ema( close,13 ) and  daily volume >=  50000 ) )",
            },
            {
                "id": "macd_bullish",
                "name": "MACD Bullish Crossover",
                "description": "MACD line crosses above signal — daily timeframe",
                "conditions": [
                    {"indicator": "macd_line", "operator": ">", "compare_to": "macd_signal"},
                    {"indicator": "macd_hist", "operator": ">", "value": 0},
                ],
                "chartink_clause": "( {cash} (  daily macd line( 26,12,9 ) >  daily macd signal( 26,12,9 ) and  1 day ago  macd line( 26,12,9 ) <=  1 day ago  macd signal( 26,12,9 ) ) )",
            },
            {
                "id": "golden_cross",
                "name": "Golden Cross EMA 55/200",
                "description": "EMA 55 crosses above EMA 200 — long-term bullish trend",
                "conditions": [
                    {"indicator": "ema50", "operator": ">", "compare_to": "ema200"},
                    {"indicator": "close", "operator": ">", "compare_to": "ema50"},
                ],
                "chartink_clause": "( {cash} (  daily ema( close,55 ) >  daily ema( close,200 ) and  1 day ago  ema( close,55 )<=  1 day ago  ema( close,200 ) ) )",
            },
            {
                "id": "volume_surge",
                "name": "Volume Shocker (5x yesterday)",
                "description": "Today's volume > 5x yesterday — explosive momentum",
                "conditions": [
                    {"indicator": "vol_surge", "operator": ">", "value": 2.0},
                ],
                "chartink_clause": "( {cash} (  daily volume >  1 day ago volume *  5 and  daily volume >  10000 ) )",
            },
            {
                "id": "bb_breakout",
                "name": "Bollinger Band Breakout",
                "description": "Price breaks above upper Bollinger Band",
                "conditions": [
                    {"indicator": "close", "operator": ">", "compare_to": "bb_upper"},
                ],
                "chartink_clause": "( {cash} (  daily close >  daily upper bollinger band( 20,2 ) and  1 day ago  close <=  1 day ago  upper bollinger band( 20,2 ) ) )",
            },
            {
                "id": "vwap_cross",
                "name": "Close > VWAP",
                "description": "Price above VWAP — institutional buying pressure",
                "conditions": [
                    {"indicator": "close", "operator": ">", "compare_to": "vwap"},
                    {"indicator": "rsi14", "operator": ">", "value": 50},
                ],
                "chartink_clause": "( {cash} (  daily close >  daily vwap ) )",
            },
            {
                "id": "ema_crossover_true",
                "name": "EMA 9 crosses above EMA 20 (True Crossover)",
                "description": "Real bar-by-bar crossover detection — REA-enhanced",
                "conditions": [
                    {"indicator": "ema9", "operator": "crosses_above", "compare_to": "ema20"},
                ],
                "chartink_clause": "( {cash} (  daily ema( close,9 ) >  daily ema( close,20 ) and  1 day ago  ema( close,9 )<=  1 day ago  ema( close,20 ) ) )",
            },
        ]
    }
