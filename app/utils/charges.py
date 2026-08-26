def calc_charges(entry_price: float, exit_price: float, qty: int) -> float:
    """Calculate Dhan intraday brokerage charges."""
    buy_tv = entry_price * qty
    sell_tv = exit_price * qty
    total_tv = buy_tv + sell_tv

    brokerage = min(20.0, buy_tv * 0.0003) + min(20.0, sell_tv * 0.0003)
    stt = sell_tv * 0.00025          # 0.025% on sell side only
    exc = total_tv * 0.0000345       # NSE exchange transaction charges
    sebi = total_tv * 0.000001       # SEBI turnover fee
    gst = (brokerage + exc + sebi) * 0.18  # 18% GST on brokerage + exc + sebi

    return round(brokerage + stt + exc + sebi + gst, 2)
