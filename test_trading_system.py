"""
test_trading_system.py — Verification test for Captain Strategy, Risk Controls, and Trailing SL.
"""

from app.services.strategy_engine import (
    get_strategy_params,
    calculate_trade_levels,
    update_trailing_stop_loss,
    CAPTAIN_PRESETS,
)
from app.services.broker_adapter import get_broker_adapter, PaperBrokerAdapter


def test_captain_strategies():
    print("Testing Captain Strategy Presets...")
    
    # 1. Conservative: 1% Target, 0.5% SL, 0.5% TSL
    cons = get_strategy_params("conservative")
    assert cons.target_pct == 1.0
    assert cons.sl_pct == 0.5
    assert cons.tsl_pct == 0.5
    print(" [OK] Conservative Strategy verified.")

    # 2. Smart: 1.5% Target, 1.0% SL, 1.0% TSL
    smart = get_strategy_params("smart")
    assert smart.target_pct == 1.5
    assert smart.sl_pct == 1.0
    assert smart.tsl_pct == 1.0
    print(" [OK] Smart Captain Strategy verified.")

    # 3. Calculation of Target & SL
    levels = calculate_trade_levels(entry_price=1000.0, strategy=smart)
    assert levels["target_price"] == 1015.0  # +1.5%
    assert levels["stop_loss"] == 990.0     # -1.0%
    assert levels["trailing_sl"] == 990.0
    print(f" [OK] Smart Levels verified: Target={levels['target_price']}, SL={levels['stop_loss']}")


def test_dynamic_trailing_sl():
    print("\nTesting Dynamic Trailing Stop Loss Ratcheting...")
    entry_price = 1000.0
    initial_sl = 990.0
    tsl_pct = 1.0

    # Step 1: Price goes up to 1010.0 (+1%)
    new_tsl = update_trailing_stop_loss(entry_price, peak_price=1010.0, current_tsl=initial_sl, tsl_pct=tsl_pct)
    # 1010 * 0.99 = 999.90
    assert new_tsl == 999.9
    print(f" [OK] Price 1010.0 -> Trailing SL moved up from 990.0 to {new_tsl}")

    # Step 2: Price pulls back to 1005.0 -> TSL must NOT move down
    pullback_tsl = update_trailing_stop_loss(entry_price, peak_price=1005.0, current_tsl=new_tsl, tsl_pct=tsl_pct)
    assert pullback_tsl == 999.9  # Remains 999.9
    print(f" [OK] Price pull-back to 1005.0 -> Trailing SL protected at {pullback_tsl}")

    # Step 3: Price advances to 1020.0 -> TSL ratchets to 1020 * 0.99 = 1009.8 (Locked in profit!)
    profit_tsl = update_trailing_stop_loss(entry_price, peak_price=1020.0, current_tsl=pullback_tsl, tsl_pct=tsl_pct)
    assert profit_tsl == 1009.8
    assert profit_tsl > entry_price  # Locked in profit
    print(f" [OK] Price 1020.0 -> Trailing SL ratcheted to {profit_tsl} (LOCKED IN PROFIT!)")


def test_broker_adapters():
    print("\nTesting Broker Adapters...")
    paper_broker = get_broker_adapter(paper_mode=True)
    assert isinstance(paper_broker, PaperBrokerAdapter)
    print(" [OK] Paper Broker Adapter instantiated successfully.")


if __name__ == "__main__":
    test_captain_strategies()
    test_dynamic_trailing_sl()
    test_broker_adapters()
    print("\nAll verification tests passed successfully!")
