import asyncio
import yfinance as yf

_PRICE_SEM = asyncio.Semaphore(10)  # max 10 concurrent fast_info fetches — prevents yfinance 429s


async def get_price(symbol: str, fallback: float | None = None) -> float | None:
    """Fetch NSE live price for a symbol using fast_info.last_price.
    Falls back to the Chartink trigger price if yfinance cannot return a live quote.
    Never uses previous_close as a fallback - that would be yesterday's price.
    """
    try:
        loop = asyncio.get_event_loop()
        ticker = await loop.run_in_executor(None, lambda: yf.Ticker(f"{symbol}.NS"))
        info = await loop.run_in_executor(None, lambda: ticker.fast_info)
        price = getattr(info, "last_price", None)
        if price and float(price) > 0:
            return float(price)
        return fallback
    except Exception:
        return fallback


async def _fetch_one(symbol: str) -> tuple[str, float | None]:
    """Semaphore-gated fetch for a single symbol."""
    async with _PRICE_SEM:
        price = await get_price(symbol)
    return symbol, price


async def get_prices_batch(symbols: list[str]) -> dict[str, float]:
    """Fetch live NSE prices for multiple symbols concurrently.
    Semaphore(10) caps concurrent yfinance calls to prevent rate-limit bans.
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