# Quant Platform Analyse

Public, sanitized snapshot of a private A-share quantitative analysis and backtesting platform.

This repository contains:

- Flask web application for screening, backtest views, weekly strategy views, user/admin pages, and health pages.
- Daily crawler and data import pipeline code.
- Backtest and weekly strategy batch scripts.
- CSV/Excel/SQLite market storage utilities.
- Tests for data import/export, validation, app integration, and strategy history.
- Example Docker, nginx, and VPN infrastructure configuration.

This public snapshot intentionally excludes:

- Real `.env` files and deployment secrets.
- SQLite databases, user databases, login logs, and market databases.
- Excel/CSV/JSON market data, generated reports, backups, and repair artifacts.
- TLS certificates, htpasswd files, QR codes, and real VPN UUID/configuration.
- Internal operations notes and host-specific run state.

The private repository keeps the full operational copy.
