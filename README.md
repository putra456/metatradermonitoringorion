# ⚡ PutraDev Trading Monitor

> Professional private trading analytics & monitoring platform for MetaTrader accounts  
> **MT4 / MT5 • Real-time monitoring • Advanced analytics • Telegram control**

<p align="center">
  <b>PutraDev – Don't Steal</b><br>
  <sub>© 2026 PutraDev. All rights reserved.</sub>
</p>

---

## ✨ Overview

**PutraDev Trading Monitor** is a professional SaaS-style trading dashboard built for monitoring **real MetaTrader trading accounts** in real-time.

Inspired by platforms like:

- **MyFxBook**
- **FXBlue**
- **Prop firm analytics dashboards**
- **TradingView / Binance style UI**

This platform provides:

- secure authentication
- multi-account monitoring
- live account metrics
- open positions tracking
- trade history
- advanced trading analytics
- Telegram bot alerts & owner controls
- real-time updates via WebSocket

---

## 🧩 Features

### 🔐 Authentication
- Secure login system
- Password hashing
- Role-based access
- Owner-level administration

### 👑 Default Owner Account
- **Username:** `ZachOnly`
- **Password:** `lupi123`

Owner privileges:

- unlimited monitored accounts
- access to all analytics
- access to all users
- full Telegram bot control
- backup control
- system administration

---

## 📦 Plan Limits

| Plan  | Max Accounts |
|------|--------------|
| Free | 1 |
| Basic | 3 |
| Pro | 10 |
| Owner | Unlimited |

---

## 🏦 Multi Broker Support

Users can connect trading accounts using:

- **Platform:** MT4 / MT5
- **Login**
- **Password**
- **Server**

> The system is designed to retrieve **real trading data** from MetaTrader accounts.  
> No fake or simulated trading data is intended.

---

## 📡 Real-Time Monitoring

Live account overview includes:

- Balance
- Equity
- Margin
- Free Margin
- Floating P/L
- Leverage
- Drawdown %

Real-time delivery:

- **WebSocket-based updates**
- fast dashboard refresh
- live PnL changes

---

## 📈 Open Positions

Track active trades with:

- Symbol
- Buy / Sell
- Lot Size
- Entry Price
- Current Price
- Profit / Loss
- Stop Loss
- Take Profit
- Open Time

---

## 📜 Trade History

Trade history view includes:

- closed trades
- entry & exit price
- profit per trade
- trade duration
- execution timeline

---

## 🧠 Advanced Analytics

Analytics dashboard provides:

### Charts
- equity curve
- daily profit chart
- monthly performance
- yearly performance logic

### Statistics
- win rate
- profit factor
- risk reward ratio
- maximum drawdown
- average trade duration
- largest winner
- largest loser
- consecutive wins
- consecutive losses

---

## 🤖 Telegram Bot Integration

Owner can configure a Telegram bot with full control.

### Owner Commands
- `/register_owner`
- `/status`
- `/accounts`
- `/profit`
- `/analytics`
- `/backup`
- `/users`
- `/help`

### Automatic Alerts
- profit milestones
- large drawdown warnings
- connection failures
- new trade opened
- trade closed

---

## 🎨 UI / UX

Designed with a premium dark SaaS aesthetic:

- dark mode by default
- glassmorphism UI
- rounded cards
- soft shadows
- smooth transitions
- responsive layout
- modern trading dashboard look

---

## 🗂 Project Structure

```bash
/project
├── server.py
├── index.html
├── style.css
└── requirements.txt
