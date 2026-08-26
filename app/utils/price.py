import asyncio
import yfinance as yf


async def get_price(symbol: str, fallback: float | None = None) -> float | None:
    """Fetch NSE live price for a symbol. Returns fallback if yfinance fails."""
    try:
        loop = asyncio.get_event_loop()
        ticker = await loop.run_in_executor(None, lambda: yf.Ticker(f"{symbol}.NS"))
        info = await loop.run_in_executor(None, lambda: ticker.fast_info)
        price = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        return float(price) if price else fallback
    except Exception:
        return fallback


async def get_prices_batch(symbols: list[str]) -> dict[str, float]:
    """Fetch live prices for multiple NSE symbols at once."""
    if not symbols:
        return {}
    try:
        loop = asyncio.get_event_loop()
        tickers = " ".join(f"{s}.NS" for s in symbols)
        data = await loop.run_in_executor(
            None, lambda: yf.download(tickers, period="1d", progress=False)
        )
        prices: dict[str, float] = {}
        if data.empty:
            return prices
        if hasattr(data.columns, "levels"):  # MultiIndex (multiple symbols)
            close = data["Close"]
            for sym in symbols:
                col = f"{sym}.NS"
                if col in close.columns:
                    series = close[col].dropna()
                    if not series.empty:
                        prices[sym] = float(series.iloc[-1])
        else:  # Single symbol
            series = data["Close"].dropna()
            if not series.empty and symbols:
                prices[symbols[0]] = float(series.iloc[-1])
        return prices
    except Exception:
        return {}
