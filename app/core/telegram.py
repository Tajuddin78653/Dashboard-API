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
    arrow = "🟢" if signal_type == "BUY" else "🔴"
    msg = (
        f"📡 <b>New Signal — TradeDash</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Signal   : {signal_id}\n"
        f"📌 Symbol   : {symbol}\n"
        f"{arrow} Type     : {signal_type}\n"
        f"💰 Price    : ₹{price:,.2f}\n"
        f"📊 Strategy : {strategy}\n"
    )
    await send_message(msg)


async def notify_trade_entry(
    trade_id: str, symbol: str, entry: float, qty: int,
    sl: float, tp: float, capital: float
) -> None:
    msg = (
        f"📝 <b>Trade Entry — TradeDash</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Trade    : {trade_id}\n"
        f"📌 Symbol   : {symbol}\n"
        f"💰 Entry    : ₹{entry:,.2f}\n"
        f"📦 Qty      : {qty}\n"
        f"🔴 SL       : ₹{sl:,.2f}\n"
        f"🟢 TP       : ₹{tp:,.2f}\n"
        f"💵 Capital  : ₹{capital:,.2f}\n"
    )
    await send_message(msg)


async def notify_trade_exit(
    trade_id: str, symbol: str, entry: float, exit_p: float,
    net_pnl: float, reason: str
) -> None:
    emoji = "✅" if net_pnl >= 0 else "❌"
    sign = "+" if net_pnl >= 0 else ""
    msg = (
        f"{emoji} <b>Trade Exit — TradeDash</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Trade    : {trade_id}\n"
        f"📌 Symbol   : {symbol}\n"
        f"💰 Entry    : ₹{entry:,.2f} → ₹{exit_p:,.2f}\n"
        f"❤️ Net P&L  : {sign}₹{net_pnl:,.2f}\n"
        f"📝 Reason   : {reason}\n"
    )
    await send_message(msg)


async def notify_eod_summary(
    total: int, winners: int, losers: int, net_pnl: float
) -> None:
    emoji = "🟢" if net_pnl >= 0 else "🔴"
    sign = "+" if net_pnl >= 0 else ""
    msg = (
        f"📊 <b>EOD Summary — TradeDash</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Total Trades : {total}\n"
        f"✅ Winners      : {winners}\n"
        f"❌ Losers       : {losers}\n"
        f"{emoji} Net P&L      : {sign}₹{net_pnl:,.2f}\n"
    )
    await send_message(msg)
