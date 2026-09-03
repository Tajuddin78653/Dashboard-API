import httpx
from app.config import settings


async def send_message(text: str, token: str = "", chat_id: str = "") -> None:
    t = token or settings.BOT_TOKEN
    c = chat_id or settings.CHAT_ID
    if not t or not c:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{t}/sendMessage",
                data={"chat_id": c, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
    except Exception:
        pass


async def notify_new_signal(
    symbol: str, signal_type: str, price: float, strategy: str, signal_id: str
) -> None:
    arrow = "\U0001f7e2" if signal_type == "BUY" else "\U0001f534"
    msg = (
        f"\U0001f4e1 <b>New Signal \u2014 TradeDash</b>\n"
        f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"\U0001f4cb Signal   : {signal_id}\n"
        f"\U0001f4cc Symbol   : {symbol}\n"
        f"{arrow} Type     : {signal_type}\n"
        f"\U0001f4b0 Price    : \u20b9{price:,.2f}\n"
        f"\U0001f4ca Strategy : {strategy}\n"
    )
    await send_message(msg)


async def notify_trade_entry(
    trade_id: str, symbol: str, entry: float, qty: int,
    sl: float, tp: float, capital: float
) -> None:
    msg = (
        f"\U0001f7e2 <b>Trade Entry \u2014 TradeDash</b>\n"
        f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"\U0001f194 Trade    : {trade_id}\n"
        f"\U0001f4cc Symbol   : {symbol}\n"
        f"\U0001f4b5 Entry    : \u20b9{entry:,.2f}\n"
        f"\U0001f522 Qty      : {qty}\n"
        f"\U0001f6d1 SL       : \u20b9{sl:,.2f}\n"
        f"\U0001f3af TP       : \u20b9{tp:,.2f}\n"
        f"\U0001f4b8 Capital  : \u20b9{capital:,.2f}\n"
    )
    await send_message(msg)


async def notify_trade_exit(
    trade_id: str, symbol: str, entry: float, exit_p: float,
    net_pnl: float, reason: str
) -> None:
    emoji = "\u2705" if net_pnl >= 0 else "\u274c"
    sign = "+" if net_pnl >= 0 else ""
    msg = (
        f"{emoji} <b>Trade Exit \u2014 TradeDash</b>\n"
        f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"\U0001f194 Trade    : {trade_id}\n"
        f"\U0001f4cc Symbol   : {symbol}\n"
        f"\U0001f4b0 Entry    : \u20b9{entry:,.2f}  \u2192\u20b9{exit_p:,.2f}\n"
        f"\U0001f49b Net P&L  : {sign}\u20b9{net_pnl:,.2f}\n"
        f"\U0001f4dd Reason   : {reason}\n"
    )
    await send_message(msg)


async def notify_eod_summary(
    total: int, winners: int, losers: int, net_pnl: float
) -> None:
    emoji = "\U0001f4c8" if net_pnl >= 0 else "\U0001f4c9"
    sign = "+" if net_pnl >= 0 else ""
    msg = (
        f"\U0001f4ca <b>EOD Summary \u2014 TradeDash</b>\n"
        f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"\U0001f522 Total Trades : {total}\n"
        f"\u2705 Winners      : {winners}\n"
        f"\u274c Losers       : {losers}\n"
        f"{emoji} Net P&L      : {sign}\u20b9{net_pnl:,.2f}\n"
    )
    await send_message(msg)