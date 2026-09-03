import asyncio
import yfinance as yf


async def get_price(symbol: str, fallback: float | None = None) -> float | None:
    """Fetch NSE live price for a symbol using fast_info.last_price.
    Falls back to the Chartink trigger price if yfinance cannot return a live quote.
    Never uses previous_close as a fallback — that would be yesterday's price.
    """
    try:
        loop = asyncio.get_event_loop()
        ticker = await loop.run_in_executor(None, lambda: yf.Ticker(f"{symbol}.NS"))
        info = await loop.run_in_executor(None, lambda: ticker.fast_info)
        price = getattr(info, "last_price", None)
        # Only accept a positive, non-zero live price — never fall back to previous_close
        if price and float(price) > 0:
            return float(price)
        return fallback
    except Exception:
        return fallback


async def _fetch_one(symbol: str) -> tuple[str, float | None]:
    """Helper: fetch live price for a single symbol."""
    price = await get_price(symbol)
    return symbol, price


async def get_prices_batch(symbols: list[str]) -> dict[str, float]:
    """Fetch live NSE prices for multiple symbols concurrently using fast_info.last_price.

    Previously used yf.download() which returns daily OHLC candles — the last row's
    'Close' is the PREVIOUS DAY'S closing price, not the live price. That caused false
    SL/TSL triggers. This version fetches each ticker's fast_info.last_price in parallel.
    """
    if not symbols:
        return {}
    tasks = [_fetch_one(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    prices: dict[str, float] = {}
    for item in results:
        if isinstance(item, Exception):
            continue
        sym, price = item
        if price is not None and price > 0:
            prices[sym] = price
    return prices