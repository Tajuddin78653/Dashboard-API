"""
strategy_engine.py — Captain Strategy presets and target/SL/TSL calculations.
"""

from typing import Dict, Any, NamedTuple


class StrategyParameters(NamedTuple):
    target_pct: float
    sl_pct: float
    tsl_pct: float
    capital_pct: float
    name: str


CAPTAIN_PRESETS: Dict[str, StrategyParameters] = {
    "conservative": StrategyParameters(
        target_pct=1.0,
        sl_pct=0.5,
        tsl_pct=0.5,
        capital_pct=10.0,
        name="Conservative",
    ),
    "smart": StrategyParameters(
        target_pct=1.5,
        sl_pct=1.0,
        tsl_pct=1.0,
        capital_pct=15.0,
        name="Smart Captain",
    ),
    "aggressive": StrategyParameters(
        target_pct=3.0,
        sl_pct=1.5,
        tsl_pct=1.0,
        capital_pct=25.0,
        name="Aggressive",
    ),
}


def get_strategy_params(
    strategy_key: str = "smart",
    custom_target: float | None = None,
    custom_sl: float | None = None,
    custom_tsl: float | None = None,
    custom_capital: float | None = None,
) -> StrategyParameters:
    """Retrieve strategy parameters by key or build custom parameters."""
    key = (strategy_key or "smart").lower()
    if key in CAPTAIN_PRESETS and custom_target is None:
        return CAPTAIN_PRESETS[key]

    return StrategyParameters(
        target_pct=custom_target if custom_target is not None else 1.5,
        sl_pct=custom_sl if custom_sl is not None else 1.0,
        tsl_pct=custom_tsl if custom_tsl is not None else 1.0,
        capital_pct=custom_capital if custom_capital is not None else 15.0,
        name="Custom Strategy",
    )


def calculate_trade_levels(
    entry_price: float,
    strategy: StrategyParameters,
) -> Dict[str, float]:
    """Calculate target, initial stop loss, and initial trailing stop loss level."""
    target_price = round(entry_price * (1 + strategy.target_pct / 100.0), 2)
    stop_loss = round(entry_price * (1 - strategy.sl_pct / 100.0), 2)
    initial_tsl = stop_loss

    return {
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "trailing_sl": initial_tsl,
        "target_pct": strategy.target_pct,
        "sl_pct": strategy.sl_pct,
        "tsl_pct": strategy.tsl_pct,
    }


def update_trailing_stop_loss(
    entry_price: float,
    peak_price: float,
    current_tsl: float,
    tsl_pct: float,
) -> float:
    """
    Ratchets trailing stop loss upward as peak price increases.
    Trailing SL NEVER moves downwards.
    """
    proposed_tsl = round(peak_price * (1 - tsl_pct / 100.0), 2)
    # Ensure TSL only ratchets upwards
    return max(current_tsl, proposed_tsl)
