# TradeDash API — Changelog

All notable changes are documented here. Each version is tagged in Git for instant rollback.

---

## [v1.2-dhan] — 2025
### Fixed
- **JWT payload** — `create_access_token` now embeds `name`, `email`, `role` in token — previously only `sub` + `exp` were included, causing all frontend role/name reads to fail

---

## [v1.1-dhan] — 2025
### Added
- `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` settings in config.py
- `/admin/config` now returns `dhan_configured` (bool) and `dhan_client_id_hint` (masked)
- `dhan_order_id` nullable column on Trade model (VARCHAR 50)
- Auto-migration 0005: adds `dhan_order_id` column on startup (idempotent)
- `dhan_order_id` exposed in `TradeResponse` and `OpenPositionResponse` schemas
- `.env.example` updated with Dhan credential placeholders

---

## [v1.0-sigma] — 2025
### Initial Production Release
- FastAPI backend with JWT auth (admin / trader / viewer roles)
- Chartink webhook ingestion — dual bot support with UUID secure tokens
- Paper trade auto-creation on every signal
- Capital guard: skip if price > CAPITAL_PER_TRADE
- Min-profit guard: skip if gross at TP < Rs.20
- Fixed 1% SL / 1% TP exit logic (simplified from trailing SL)
- APScheduler: price monitor every 60s, force-exit at FORCE_EXIT_TIME, EOD summary at 15:30
- Telegram alerts: signal entry, trade entry, trade exit, EOD summary
- Dhan intraday brokerage charges calculator
- PostgreSQL via Supabase, Redis via Upstash
- Auto-migrations on startup (0001–0004)
- Deployed on Render
