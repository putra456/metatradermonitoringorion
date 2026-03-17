"""
╔══════════════════════════════════════════════════════════════╗
║              PutraDev Trading Monitor Platform               ║
║                    server.py - Backend                        ║
║                                                              ║
║  © 2026 PutraDev. All rights reserved.                       ║
║  PutraDev – Don't Steal                                      ║
╚══════════════════════════════════════════════════════════════╝

Professional MetaTrader monitoring platform with real-time
data retrieval, advanced analytics, Telegram bot integration,
and multi-account dashboard capabilities.
"""

import os
import sys
import json
import time
import hashlib
import asyncio
import sqlite3
import logging
import shutil
import tempfile
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Set
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, HTTPException,
    Depends, status, Request, Response, Query
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from passlib.context import CryptContext
from jose import JWTError, jwt

# ─── Logging Configuration ───────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("PutraDev")

# ─── MetaTrader5 Import (Windows Only) ───────────────────────
MT5_AVAILABLE = False
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
    logger.info("MetaTrader5 module loaded successfully")
except ImportError:
    logger.warning("MetaTrader5 module not available - install on Windows with MT5 terminal")
    mt5 = None

# ─── Telegram Bot Import ─────────────────────────────────────
TELEGRAM_AVAILABLE = False
try:
    from telegram import Bot, Update
    from telegram.ext import (
        ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
    )
    TELEGRAM_AVAILABLE = True
    logger.info("Telegram bot module loaded successfully")
except ImportError:
    logger.warning("python-telegram-bot not available")

# ─── Constants & Configuration ────────────────────────────────
SECRET_KEY = "putradev-secret-key-2026-zachonly-trading-monitor-platform"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
DATABASE_PATH = "putradev_trading.db"

PLAN_LIMITS = {
    "free": 1,
    "basic": 3,
    "pro": 10,
    "owner": 999999
}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ─── Pydantic Models ─────────────────────────────────────────

class UserLogin(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str
    password: str
    plan: str = "free"

class AccountAdd(BaseModel):
    platform: str  # MT4 or MT5
    login: int
    password: str
    server: str
    nickname: str = ""

class TelegramConfig(BaseModel):
    bot_token: str

class PlanUpdate(BaseModel):
    username: str
    plan: str

# ─── Database Manager ────────────────────────────────────────

class DatabaseManager:
    """SQLite database manager for all platform data."""

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.init_database()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                plan TEXT DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS trading_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                login INTEGER NOT NULL,
                password_encrypted TEXT NOT NULL,
                server TEXT NOT NULL,
                nickname TEXT DEFAULT '',
                is_connected INTEGER DEFAULT 0,
                last_update TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                balance REAL DEFAULT 0,
                equity REAL DEFAULT 0,
                margin REAL DEFAULT 0,
                free_margin REAL DEFAULT 0,
                floating_pnl REAL DEFAULT 0,
                leverage INTEGER DEFAULT 0,
                drawdown_pct REAL DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS open_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                ticket INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                trade_type TEXT NOT NULL,
                lot_size REAL DEFAULT 0,
                entry_price REAL DEFAULT 0,
                current_price REAL DEFAULT 0,
                profit REAL DEFAULT 0,
                stop_loss REAL DEFAULT 0,
                take_profit REAL DEFAULT 0,
                open_time TIMESTAMP,
                swap REAL DEFAULT 0,
                commission REAL DEFAULT 0,
                magic INTEGER DEFAULT 0,
                comment TEXT DEFAULT '',
                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                ticket INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                trade_type TEXT NOT NULL,
                lot_size REAL DEFAULT 0,
                entry_price REAL DEFAULT 0,
                exit_price REAL DEFAULT 0,
                profit REAL DEFAULT 0,
                stop_loss REAL DEFAULT 0,
                take_profit REAL DEFAULT 0,
                open_time TIMESTAMP,
                close_time TIMESTAMP,
                swap REAL DEFAULT 0,
                commission REAL DEFAULT 0,
                duration_seconds INTEGER DEFAULT 0,
                magic INTEGER DEFAULT 0,
                comment TEXT DEFAULT '',
                FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telegram_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_token TEXT,
                owner_chat_id TEXT,
                is_active INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS notifications_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                notification_type TEXT NOT NULL,
                message TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                profit REAL DEFAULT 0,
                trades_count INTEGER DEFAULT 0,
                win_count INTEGER DEFAULT 0,
                loss_count INTEGER DEFAULT 0,
                balance_end REAL DEFAULT 0,
                equity_end REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0,
                UNIQUE(account_id, date),
                FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_account ON account_snapshots(account_id);
            CREATE INDEX IF NOT EXISTS idx_snapshots_time ON account_snapshots(timestamp);
            CREATE INDEX IF NOT EXISTS idx_positions_account ON open_positions(account_id);
            CREATE INDEX IF NOT EXISTS idx_history_account ON trade_history(account_id);
            CREATE INDEX IF NOT EXISTS idx_daily_stats ON daily_stats(account_id, date);
        """)

        # Create default owner account
        owner_exists = cursor.execute(
            "SELECT id FROM users WHERE username = ?", ("ZachOnly",)
        ).fetchone()

        if not owner_exists:
            owner_hash = pwd_context.hash("lupi123")
            cursor.execute(
                "INSERT INTO users (username, password_hash, role, plan) VALUES (?, ?, ?, ?)",
                ("ZachOnly", owner_hash, "owner", "owner")
            )
            logger.info("Default owner account 'ZachOnly' created")

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")

    def execute(self, query: str, params: tuple = ()) -> list:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.commit()
        conn.close()
        return results

    def execute_one(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = cursor.fetchone()
        conn.commit()
        conn.close()
        return result

    def execute_insert(self, query: str, params: tuple = ()) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        last_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return last_id

    def execute_update(self, query: str, params: tuple = ()) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        return rows_affected

    def create_backup(self) -> str:
        backup_name = f"backup_putradev_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        backup_path = os.path.join(tempfile.gettempdir(), backup_name)
        shutil.copy2(self.db_path, backup_path)
        logger.info(f"Database backup created: {backup_path}")
        return backup_path


# ─── MetaTrader Connection Manager ───────────────────────────

class MT5ConnectionManager:
    """Manages connections to MetaTrader 5 terminals and retrieves real trading data."""

    def __init__(self):
        self.active_connections: Dict[int, dict] = {}
        self.initialized = False

    def initialize(self) -> bool:
        if not MT5_AVAILABLE:
            logger.error("MT5 module not available. Install on Windows with MT5 terminal.")
            return False
        if not self.initialized:
            if mt5.initialize():
                self.initialized = True
                logger.info("MT5 terminal initialized")
                return True
            else:
                logger.error(f"MT5 initialization failed: {mt5.last_error()}")
                return False
        return True

    def connect_account(self, login: int, password: str, server: str) -> dict:
        """Connect to a MetaTrader account and return account info."""
        if not MT5_AVAILABLE:
            return {"success": False, "error": "MetaTrader5 not available on this system"}

        if not self.initialize():
            return {"success": False, "error": "Failed to initialize MT5 terminal"}

        authorized = mt5.login(login=login, password=password, server=server)
        if not authorized:
            error = mt5.last_error()
            logger.error(f"Login failed for {login}@{server}: {error}")
            return {"success": False, "error": f"Login failed: {error}"}

        info = mt5.account_info()
        if info is None:
            return {"success": False, "error": "Failed to retrieve account info"}

        account_data = {
            "success": True,
            "login": info.login,
            "name": info.name,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "leverage": info.leverage,
            "profit": info.profit,
            "currency": info.currency,
            "company": info.company
        }

        self.active_connections[login] = {
            "password": password,
            "server": server,
            "last_connected": datetime.now()
        }

        logger.info(f"Successfully connected to account {login}@{server}")
        return account_data

    def get_account_info(self, login: int, password: str, server: str) -> dict:
        """Get current account information."""
        if not MT5_AVAILABLE:
            return None

        authorized = mt5.login(login=login, password=password, server=server)
        if not authorized:
            return None

        info = mt5.account_info()
        if info is None:
            return None

        # Calculate drawdown
        drawdown_pct = 0.0
        if info.balance > 0:
            drawdown_pct = ((info.balance - info.equity) / info.balance) * 100
            if drawdown_pct < 0:
                drawdown_pct = 0.0

        return {
            "balance": round(info.balance, 2),
            "equity": round(info.equity, 2),
            "margin": round(info.margin, 2),
            "free_margin": round(info.margin_free, 2),
            "floating_pnl": round(info.profit, 2),
            "leverage": info.leverage,
            "drawdown_pct": round(drawdown_pct, 2),
            "currency": info.currency,
            "company": info.company,
            "name": info.name
        }

    def get_open_positions(self, login: int, password: str, server: str) -> list:
        """Get all open positions for the account."""
        if not MT5_AVAILABLE:
            return []

        authorized = mt5.login(login=login, password=password, server=server)
        if not authorized:
            return []

        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            return []

        result = []
        for pos in positions:
            trade_type = "BUY" if pos.type == 0 else "SELL"
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "trade_type": trade_type,
                "lot_size": pos.volume,
                "entry_price": round(pos.price_open, 5),
                "current_price": round(pos.price_current, 5),
                "profit": round(pos.profit, 2),
                "stop_loss": round(pos.sl, 5),
                "take_profit": round(pos.tp, 5),
                "open_time": datetime.fromtimestamp(pos.time).isoformat(),
                "swap": round(pos.swap, 2),
                "commission": round(pos.commission, 2),
                "magic": pos.magic,
                "comment": pos.comment
            })

        return result

    def get_trade_history(self, login: int, password: str, server: str,
                          days_back: int = 365) -> list:
        """Get closed trade history."""
        if not MT5_AVAILABLE:
            return []

        authorized = mt5.login(login=login, password=password, server=server)
        if not authorized:
            return []

        from_date = datetime.now() - timedelta(days=days_back)
        to_date = datetime.now()

        deals = mt5.history_deals_get(from_date, to_date)
        if deals is None or len(deals) == 0:
            return []

        # Group deals by position to form complete trades
        trades_map: Dict[int, dict] = {}
        result = []

        for deal in deals:
            if deal.entry == 0:  # Entry deal
                trades_map[deal.position_id] = {
                    "ticket": deal.position_id,
                    "symbol": deal.symbol,
                    "trade_type": "BUY" if deal.type == 0 else "SELL",
                    "lot_size": deal.volume,
                    "entry_price": round(deal.price, 5),
                    "open_time": datetime.fromtimestamp(deal.time).isoformat(),
                    "commission": round(deal.commission, 2),
                    "swap": 0.0,
                    "magic": deal.magic,
                    "comment": deal.comment
                }
            elif deal.entry == 1:  # Exit deal
                if deal.position_id in trades_map:
                    trade = trades_map[deal.position_id]
                    close_time = datetime.fromtimestamp(deal.time)
                    open_time = datetime.fromisoformat(trade["open_time"])
                    duration = int((close_time - open_time).total_seconds())

                    trade.update({
                        "exit_price": round(deal.price, 5),
                        "profit": round(deal.profit, 2),
                        "close_time": close_time.isoformat(),
                        "duration_seconds": duration,
                        "swap": round(deal.swap, 2),
                        "commission": round(trade["commission"] + deal.commission, 2)
                    })
                    result.append(trade)
                    del trades_map[deal.position_id]
                else:
                    # Standalone exit
                    close_time = datetime.fromtimestamp(deal.time)
                    result.append({
                        "ticket": deal.position_id,
                        "symbol": deal.symbol,
                        "trade_type": "BUY" if deal.type == 1 else "SELL",
                        "lot_size": deal.volume,
                        "entry_price": 0,
                        "exit_price": round(deal.price, 5),
                        "profit": round(deal.profit, 2),
                        "open_time": close_time.isoformat(),
                        "close_time": close_time.isoformat(),
                        "duration_seconds": 0,
                        "swap": round(deal.swap, 2),
                        "commission": round(deal.commission, 2),
                        "magic": deal.magic,
                        "comment": deal.comment
                    })

        result.sort(key=lambda x: x.get("close_time", ""), reverse=True)
        return result

    def get_symbol_data(self, symbol: str, timeframe: str = "H1",
                         count: int = 500) -> list:
        """Get OHLCV candle data for charting."""
        if not MT5_AVAILABLE:
            return []

        tf_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1
        }

        mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_H1)
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)

        if rates is None or len(rates) == 0:
            return []

        candles = []
        for rate in rates:
            candles.append({
                "time": int(rate[0]),
                "open": float(rate[1]),
                "high": float(rate[2]),
                "low": float(rate[3]),
                "close": float(rate[4]),
                "volume": float(rate[5])
            })

        return candles

    def get_symbols(self) -> list:
        """Get available trading symbols."""
        if not MT5_AVAILABLE:
            return []

        symbols = mt5.symbols_get()
        if symbols is None:
            return []

        return [
            {"name": s.name, "description": s.description, "path": s.path}
            for s in symbols if s.visible
        ]

    def shutdown(self):
        if MT5_AVAILABLE and self.initialized:
            mt5.shutdown()
            self.initialized = False
            logger.info("MT5 terminal shutdown")


# ─── Analytics Engine ────────────────────────────────────────

class AnalyticsEngine:
    """Advanced trading analytics calculator."""

    @staticmethod
    def calculate_statistics(trades: list) -> dict:
        """Calculate comprehensive trading statistics from trade history."""
        if not trades:
            return AnalyticsEngine._empty_stats()

        profits = [t.get("profit", 0) for t in trades if "profit" in t]
        if not profits:
            return AnalyticsEngine._empty_stats()

        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p < 0]
        breakeven = [p for p in profits if p == 0]

        total_trades = len(profits)
        total_profit = sum(profits)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0

        profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float('inf') if wins else 0
        risk_reward = (avg_win / avg_loss) if avg_loss > 0 else float('inf') if avg_win > 0 else 0

        # Max drawdown from cumulative profit
        cumulative = []
        running = 0
        peak = 0
        max_dd = 0
        for p in profits:
            running += p
            cumulative.append(running)
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd

        # Durations
        durations = [t.get("duration_seconds", 0) for t in trades if "duration_seconds" in t]
        avg_duration = sum(durations) / len(durations) if durations else 0

        # Consecutive wins/losses
        consec_wins = AnalyticsEngine._max_consecutive(profits, positive=True)
        consec_losses = AnalyticsEngine._max_consecutive(profits, positive=False)

        # Largest win/loss
        largest_win = max(wins) if wins else 0
        largest_loss = min(losses) if losses else 0

        # Daily breakdown
        daily_profits = {}
        for t in trades:
            close_time = t.get("close_time", "")
            if close_time:
                day = close_time[:10]
                daily_profits.setdefault(day, 0)
                daily_profits[day] += t.get("profit", 0)

        # Monthly breakdown
        monthly_profits = {}
        for t in trades:
            close_time = t.get("close_time", "")
            if close_time:
                month = close_time[:7]
                monthly_profits.setdefault(month, 0)
                monthly_profits[month] += t.get("profit", 0)

        # Equity curve
        equity_curve = []
        running = 0
        for i, p in enumerate(profits):
            running += p
            equity_curve.append({"trade": i + 1, "equity": round(running, 2)})

        return {
            "total_trades": total_trades,
            "total_profit": round(total_profit, 2),
            "win_count": win_count,
            "loss_count": loss_count,
            "breakeven_count": len(breakeven),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "∞",
            "risk_reward_ratio": round(risk_reward, 2) if risk_reward != float('inf') else "∞",
            "max_drawdown": round(max_dd, 2),
            "avg_trade_duration_seconds": round(avg_duration),
            "avg_trade_duration_human": AnalyticsEngine._format_duration(avg_duration),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "consecutive_wins": consec_wins,
            "consecutive_losses": consec_losses,
            "daily_profits": daily_profits,
            "monthly_profits": monthly_profits,
            "equity_curve": equity_curve,
            "cumulative_profit": cumulative
        }

    @staticmethod
    def _max_consecutive(profits: list, positive: bool = True) -> int:
        max_count = 0
        current = 0
        for p in profits:
            if (positive and p > 0) or (not positive and p < 0):
                current += 1
                max_count = max(max_count, current)
            else:
                current = 0
        return max_count

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}d {hours}h"

    @staticmethod
    def _empty_stats() -> dict:
        return {
            "total_trades": 0, "total_profit": 0, "win_count": 0,
            "loss_count": 0, "breakeven_count": 0, "win_rate": 0,
            "profit_factor": 0, "risk_reward_ratio": 0, "max_drawdown": 0,
            "avg_trade_duration_seconds": 0, "avg_trade_duration_human": "0s",
            "largest_win": 0, "largest_loss": 0, "avg_win": 0, "avg_loss": 0,
            "consecutive_wins": 0, "consecutive_losses": 0,
            "daily_profits": {}, "monthly_profits": {},
            "equity_curve": [], "cumulative_profit": []
        }


# ─── Telegram Bot Manager ────────────────────────────────────

class TelegramBotManager:
    """Manages the Telegram bot for notifications and commands."""

    def __init__(self, db: DatabaseManager, mt5_mgr: MT5ConnectionManager):
        self.db = db
        self.mt5_mgr = mt5_mgr
        self.bot: Optional[Bot] = None
        self.app = None
        self.owner_chat_id: Optional[str] = None
        self.is_running = False
        self._load_config()

    def _load_config(self):
        config = self.db.execute_one("SELECT * FROM telegram_config ORDER BY id DESC LIMIT 1")
        if config:
            if config["owner_chat_id"]:
                self.owner_chat_id = config["owner_chat_id"]

    async def start_bot(self, token: str):
        if not TELEGRAM_AVAILABLE:
            logger.error("Telegram bot module not available")
            return False

        try:
            self.bot = Bot(token=token)
            bot_info = await self.bot.get_me()
            logger.info(f"Telegram bot started: @{bot_info.username}")

            self.app = ApplicationBuilder().token(token).build()

            # Register handlers
            self.app.add_handler(CommandHandler("start", self._cmd_start))
            self.app.add_handler(CommandHandler("register_owner", self._cmd_register_owner))
            self.app.add_handler(CommandHandler("status", self._cmd_status))
            self.app.add_handler(CommandHandler("accounts", self._cmd_accounts))
            self.app.add_handler(CommandHandler("profit", self._cmd_profit))
            self.app.add_handler(CommandHandler("analytics", self._cmd_analytics))
            self.app.add_handler(CommandHandler("backup", self._cmd_backup))
            self.app.add_handler(CommandHandler("users", self._cmd_users))
            self.app.add_handler(CommandHandler("help", self._cmd_help))

            await self.app.initialize()
            await self.app.start()
            if self.app.updater:
                await self.app.updater.start_polling(drop_pending_updates=True)
            self.is_running = True
            return True

        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")
            return False

    async def stop_bot(self):
        if self.app and self.is_running:
            try:
                if self.app.updater:
                    await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except Exception as e:
                logger.warning(f"Error stopping bot: {e}")
            self.is_running = False

    async def send_notification(self, message: str):
        if self.bot and self.owner_chat_id:
            try:
                await self.bot.send_message(
                    chat_id=self.owner_chat_id,
                    text=message,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to send Telegram notification: {e}")

    def _is_owner(self, chat_id: str) -> bool:
        return str(chat_id) == str(self.owner_chat_id)

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🚀 <b>PutraDev Trading Monitor</b>\n\n"
            "Welcome to the professional trading analytics platform.\n\n"
            "Use /register_owner to register as the owner.\n"
            "Use /help for available commands.",
            parse_mode="HTML"
        )

    async def _cmd_register_owner(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)

        if self.owner_chat_id is None:
            self.owner_chat_id = chat_id
            self.db.execute(
                "INSERT OR REPLACE INTO telegram_config (id, owner_chat_id, is_active) VALUES (1, ?, 1)",
                (chat_id,)
            )
            await update.message.reply_text(
                f"✅ <b>Owner registered!</b>\n\n"
                f"Chat ID: <code>{chat_id}</code>\n"
                f"You now have full bot control.",
                parse_mode="HTML"
            )
            logger.info(f"Telegram owner registered: {chat_id}")
        elif self._is_owner(chat_id):
            await update.message.reply_text("✅ You are already registered as the owner.", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Owner is already registered.", parse_mode="HTML")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(str(update.effective_chat.id)):
            await update.message.reply_text("❌ Owner only command.")
            return

        accounts = self.db.execute("SELECT COUNT(*) as cnt FROM trading_accounts")
        users = self.db.execute("SELECT COUNT(*) as cnt FROM users")
        connected = self.db.execute("SELECT COUNT(*) as cnt FROM trading_accounts WHERE is_connected = 1")

        acc_count = accounts[0]["cnt"] if accounts else 0
        user_count = users[0]["cnt"] if users else 0
        conn_count = connected[0]["cnt"] if connected else 0

        await update.message.reply_text(
            f"📊 <b>System Status</b>\n\n"
            f"👥 Users: {user_count}\n"
            f"📈 Trading Accounts: {acc_count}\n"
            f"🔗 Connected: {conn_count}\n"
            f"🖥 MT5 Available: {'✅' if MT5_AVAILABLE else '❌'}\n"
            f"⏰ Server Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML"
        )

    async def _cmd_accounts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(str(update.effective_chat.id)):
            await update.message.reply_text("❌ Owner only command.")
            return

        accounts = self.db.execute(
            """SELECT ta.*, u.username FROM trading_accounts ta
               JOIN users u ON ta.user_id = u.id ORDER BY ta.id"""
        )

        if not accounts:
            await update.message.reply_text("📈 No trading accounts registered.")
            return

        msg = "📈 <b>Trading Accounts</b>\n\n"
        for acc in accounts:
            status = "🟢" if acc["is_connected"] else "🔴"
            msg += (
                f"{status} {acc['nickname'] or acc['login']}\n"
                f"   Platform: {acc['platform']} | Login: {acc['login']}\n"
                f"   Server: {acc['server']}\n"
                f"   Owner: {acc['username']}\n\n"
            )

        await update.message.reply_text(msg, parse_mode="HTML")

    async def _cmd_profit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(str(update.effective_chat.id)):
            await update.message.reply_text("❌ Owner only command.")
            return

        snapshots = self.db.execute(
            """SELECT ta.nickname, ta.login, s.balance, s.equity, s.floating_pnl
               FROM account_snapshots s
               JOIN trading_accounts ta ON s.account_id = ta.id
               WHERE s.id IN (SELECT MAX(id) FROM account_snapshots GROUP BY account_id)"""
        )

        if not snapshots:
            await update.message.reply_text("💰 No profit data available yet.")
            return

        msg = "💰 <b>Profit Summary</b>\n\n"
        total_balance = 0
        total_equity = 0
        total_float = 0

        for s in snapshots:
            name = s["nickname"] or str(s["login"])
            msg += (
                f"📊 <b>{name}</b>\n"
                f"   Balance: ${s['balance']:,.2f}\n"
                f"   Equity: ${s['equity']:,.2f}\n"
                f"   Float P/L: ${s['floating_pnl']:,.2f}\n\n"
            )
            total_balance += s["balance"]
            total_equity += s["equity"]
            total_float += s["floating_pnl"]

        msg += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 <b>Total Balance:</b> ${total_balance:,.2f}\n"
            f"💎 <b>Total Equity:</b> ${total_equity:,.2f}\n"
            f"💎 <b>Total Float:</b> ${total_float:,.2f}"
        )

        await update.message.reply_text(msg, parse_mode="HTML")

    async def _cmd_analytics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(str(update.effective_chat.id)):
            await update.message.reply_text("❌ Owner only command.")
            return

        accounts = self.db.execute("SELECT id, nickname, login FROM trading_accounts")

        if not accounts:
            await update.message.reply_text("📊 No accounts for analytics.")
            return

        msg = "📊 <b>Analytics Summary</b>\n\n"

        for acc in accounts:
            history = self.db.execute(
                "SELECT * FROM trade_history WHERE account_id = ? ORDER BY close_time",
                (acc["id"],)
            )
            trades = [dict(h) for h in history]
            stats = AnalyticsEngine.calculate_statistics(trades)

            name = acc["nickname"] or str(acc["login"])
            msg += (
                f"📈 <b>{name}</b>\n"
                f"   Trades: {stats['total_trades']}\n"
                f"   Win Rate: {stats['win_rate']}%\n"
                f"   Profit: ${stats['total_profit']:,.2f}\n"
                f"   PF: {stats['profit_factor']}\n"
                f"   Max DD: ${stats['max_drawdown']:,.2f}\n\n"
            )

        await update.message.reply_text(msg, parse_mode="HTML")

    async def _cmd_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(str(update.effective_chat.id)):
            await update.message.reply_text("❌ Owner only command.")
            return

        try:
            backup_path = self.db.create_backup()
            with open(backup_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=os.path.basename(backup_path),
                    caption="✅ Database backup created successfully."
                )
            os.remove(backup_path)
        except Exception as e:
            await update.message.reply_text(f"❌ Backup failed: {e}")

    async def _cmd_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(str(update.effective_chat.id)):
            await update.message.reply_text("❌ Owner only command.")
            return

        users = self.db.execute("SELECT username, role, plan, created_at, last_login FROM users ORDER BY id")

        msg = "👥 <b>Registered Users</b>\n\n"
        for u in users:
            role_emoji = "👑" if u["role"] == "owner" else "👤"
            msg += (
                f"{role_emoji} <b>{u['username']}</b>\n"
                f"   Role: {u['role']} | Plan: {u['plan']}\n"
                f"   Joined: {u['created_at']}\n"
                f"   Last Login: {u['last_login'] or 'Never'}\n\n"
            )

        await update.message.reply_text(msg, parse_mode="HTML")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 <b>PutraDev Bot Commands</b>\n\n"
            "/register_owner - Register as owner\n"
            "/status - System status\n"
            "/accounts - List trading accounts\n"
            "/profit - Profit summary\n"
            "/analytics - Analytics summary\n"
            "/backup - Create database backup\n"
            "/users - List registered users\n"
            "/help - Show this help",
            parse_mode="HTML"
        )


# ─── Authentication Utilities ────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ─── Initialize Global Instances ──────────────────────────────

db = DatabaseManager()
mt5_mgr = MT5ConnectionManager()
analytics = AnalyticsEngine()
telegram_bot = TelegramBotManager(db, mt5_mgr)

# WebSocket connections
ws_connections: Dict[str, Set[WebSocket]] = {}


# ─── Background Tasks ────────────────────────────────────────

async def monitor_accounts_task():
    """Background task: periodically update account data and detect changes."""
    logger.info("Account monitoring background task started")
    previous_positions: Dict[int, set] = {}

    while True:
        try:
            accounts = db.execute(
                """SELECT ta.*, u.username FROM trading_accounts ta
                   JOIN users u ON ta.user_id = u.id WHERE ta.is_connected = 1"""
            )

            for acc in accounts:
                account_id = acc["id"]
                login = acc["login"]
                password = acc["password_encrypted"]
                server = acc["server"]

                # Get account info
                info = mt5_mgr.get_account_info(login, password, server)
                if info:
                    db.execute_insert(
                        """INSERT INTO account_snapshots
                           (account_id, balance, equity, margin, free_margin,
                            floating_pnl, leverage, drawdown_pct)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (account_id, info["balance"], info["equity"],
                         info["margin"], info["free_margin"],
                         info["floating_pnl"], info["leverage"],
                         info["drawdown_pct"])
                    )

                    # Check drawdown warning
                    if info["drawdown_pct"] > 10:
                        await telegram_bot.send_notification(
                            f"⚠️ <b>High Drawdown Alert!</b>\n\n"
                            f"Account: {acc['nickname'] or login}\n"
                            f"Drawdown: {info['drawdown_pct']}%\n"
                            f"Equity: ${info['equity']:,.2f}"
                        )

                # Get open positions and detect new/closed trades
                positions = mt5_mgr.get_open_positions(login, password, server)
                current_tickets = {p["ticket"] for p in positions}
                prev_tickets = previous_positions.get(account_id, set())

                # New trades opened
                new_tickets = current_tickets - prev_tickets
                for ticket in new_tickets:
                    pos = next((p for p in positions if p["ticket"] == ticket), None)
                    if pos:
                        await telegram_bot.send_notification(
                            f"📈 <b>New Trade Opened</b>\n\n"
                            f"Account: {acc['nickname'] or login}\n"
                            f"Symbol: {pos['symbol']}\n"
                            f"Type: {pos['trade_type']}\n"
                            f"Lots: {pos['lot_size']}\n"
                            f"Price: {pos['entry_price']}"
                        )

                # Trades closed
                closed_tickets = prev_tickets - current_tickets
                if closed_tickets:
                    await telegram_bot.send_notification(
                        f"📉 <b>Trade(s) Closed</b>\n\n"
                        f"Account: {acc['nickname'] or login}\n"
                        f"Closed tickets: {len(closed_tickets)}"
                    )

                previous_positions[account_id] = current_tickets

                # Update open positions in DB
                conn = db.get_connection()
                conn.execute("DELETE FROM open_positions WHERE account_id = ?", (account_id,))
                for pos in positions:
                    conn.execute(
                        """INSERT INTO open_positions
                           (account_id, ticket, symbol, trade_type, lot_size,
                            entry_price, current_price, profit, stop_loss,
                            take_profit, open_time, swap, commission, magic, comment)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (account_id, pos["ticket"], pos["symbol"], pos["trade_type"],
                         pos["lot_size"], pos["entry_price"], pos["current_price"],
                         pos["profit"], pos["stop_loss"], pos["take_profit"],
                         pos["open_time"], pos["swap"], pos["commission"],
                         pos["magic"], pos["comment"])
                    )
                conn.commit()
                conn.close()

                # Update trade history
                history = mt5_mgr.get_trade_history(login, password, server, days_back=90)
                if history:
                    conn = db.get_connection()
                    for trade in history:
                        existing = conn.execute(
                            "SELECT id FROM trade_history WHERE account_id = ? AND ticket = ?",
                            (account_id, trade["ticket"])
                        ).fetchone()
                        if not existing:
                            conn.execute(
                                """INSERT INTO trade_history
                                   (account_id, ticket, symbol, trade_type, lot_size,
                                    entry_price, exit_price, profit, stop_loss, take_profit,
                                    open_time, close_time, swap, commission, duration_seconds,
                                    magic, comment)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (account_id, trade["ticket"], trade["symbol"],
                                 trade["trade_type"], trade["lot_size"],
                                 trade["entry_price"], trade.get("exit_price", 0),
                                 trade["profit"], trade.get("stop_loss", 0),
                                 trade.get("take_profit", 0), trade["open_time"],
                                 trade.get("close_time", ""), trade["swap"],
                                 trade["commission"], trade.get("duration_seconds", 0),
                                 trade["magic"], trade["comment"])
                            )
                    conn.commit()
                    conn.close()

                # Send WebSocket updates
                ws_data = json.dumps({
                    "type": "account_update",
                    "account_id": account_id,
                    "info": info,
                    "positions": positions,
                    "timestamp": datetime.now().isoformat()
                })

                user_key = f"user_{acc['user_id']}"
                if user_key in ws_connections:
                    dead = set()
                    for ws in ws_connections[user_key]:
                        try:
                            await ws.send_text(ws_data)
                        except Exception:
                            dead.add(ws)
                    ws_connections[user_key] -= dead

        except Exception as e:
            logger.error(f"Monitor task error: {e}")

        await asyncio.sleep(5)  # Update every 5 seconds


# ─── FastAPI Application ─────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("═══════════════════════════════════════════════")
    logger.info("  PutraDev Trading Monitor Platform Starting   ")
    logger.info("  © 2026 PutraDev. All rights reserved.        ")
    logger.info("═══════════════════════════════════════════════")

    # Start background monitor task
    monitor_task = asyncio.create_task(monitor_accounts_task())

    # Start Telegram bot if configured
    config = db.execute_one("SELECT * FROM telegram_config WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
    if config and config["bot_token"]:
        asyncio.create_task(telegram_bot.start_bot(config["bot_token"]))

    yield

    monitor_task.cancel()
    await telegram_bot.stop_bot()
    mt5_mgr.shutdown()
    logger.info("PutraDev platform shutdown complete")


app = FastAPI(
    title="PutraDev Trading Monitor",
    description="Professional Trading Analytics & Monitoring Platform",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helper: Extract and verify user from token ──────────────

def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header.split(" ")[1]
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.execute_one("SELECT * FROM users WHERE username = ?", (payload.get("sub"),))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return dict(user)


# ─── API Routes: Authentication ──────────────────────────────

@app.post("/api/auth/login")
async def login(data: UserLogin):
    user = db.execute_one("SELECT * FROM users WHERE username = ?", (data.username,))
    if not user or not pwd_context.verify(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")

    db.execute_update(
        "UPDATE users SET last_login = ? WHERE id = ?",
        (datetime.now().isoformat(), user["id"])
    )

    token = create_access_token({"sub": user["username"], "role": user["role"]})

    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "plan": user["plan"]
        }
    }


@app.post("/api/auth/register")
async def register(data: UserCreate):
    existing = db.execute_one("SELECT id FROM users WHERE username = ?", (data.username,))
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    if data.plan not in PLAN_LIMITS:
        data.plan = "free"

    password_hash = pwd_context.hash(data.password)
    user_id = db.execute_insert(
        "INSERT INTO users (username, password_hash, plan) VALUES (?, ?, ?)",
        (data.username, password_hash, data.plan)
    )

    token = create_access_token({"sub": data.username, "role": "user"})

    return {
        "token": token,
        "user": {
            "id": user_id,
            "username": data.username,
            "role": "user",
            "plan": data.plan
        }
    }


@app.get("/api/auth/me")
async def get_me(request: Request):
    user = get_current_user(request)
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "plan": user["plan"],
        "created_at": user["created_at"],
        "last_login": user["last_login"]
    }


# ─── API Routes: Trading Accounts ────────────────────────────

@app.post("/api/accounts/add")
async def add_account(data: AccountAdd, request: Request):
    user = get_current_user(request)

    # Check plan limits
    current_count = db.execute_one(
        "SELECT COUNT(*) as cnt FROM trading_accounts WHERE user_id = ?",
        (user["id"],)
    )
    count = current_count["cnt"] if current_count else 0
    limit = PLAN_LIMITS.get(user["plan"], 1)

    if count >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"Account limit reached ({limit}) for plan '{user['plan']}'. Upgrade your plan."
        )

    # Validate platform
    if data.platform.upper() not in ("MT4", "MT5"):
        raise HTTPException(status_code=400, detail="Platform must be MT4 or MT5")

    # Try to connect
    if MT5_AVAILABLE:
        result = mt5_mgr.connect_account(data.login, data.password, data.server)
        is_connected = result.get("success", False)
    else:
        is_connected = False

    account_id = db.execute_insert(
        """INSERT INTO trading_accounts
           (user_id, platform, login, password_encrypted, server, nickname, is_connected)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user["id"], data.platform.upper(), data.login, data.password,
         data.server, data.nickname or f"Account {data.login}", 1 if is_connected else 0)
    )

    # If connected, fetch initial data
    if is_connected and MT5_AVAILABLE:
        info = mt5_mgr.get_account_info(data.login, data.password, data.server)
        if info:
            db.execute_insert(
                """INSERT INTO account_snapshots
                   (account_id, balance, equity, margin, free_margin,
                    floating_pnl, leverage, drawdown_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, info["balance"], info["equity"],
                 info["margin"], info["free_margin"],
                 info["floating_pnl"], info["leverage"], info["drawdown_pct"])
            )

        # Fetch and store trade history
        history = mt5_mgr.get_trade_history(data.login, data.password, data.server)
        if history:
            conn = db.get_connection()
            for trade in history:
                conn.execute(
                    """INSERT OR IGNORE INTO trade_history
                       (account_id, ticket, symbol, trade_type, lot_size,
                        entry_price, exit_price, profit, stop_loss, take_profit,
                        open_time, close_time, swap, commission, duration_seconds,
                        magic, comment)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (account_id, trade["ticket"], trade["symbol"],
                     trade["trade_type"], trade["lot_size"],
                     trade["entry_price"], trade.get("exit_price", 0),
                     trade["profit"], trade.get("stop_loss", 0),
                     trade.get("take_profit", 0), trade["open_time"],
                     trade.get("close_time", ""), trade["swap"],
                     trade["commission"], trade.get("duration_seconds", 0),
                     trade["magic"], trade["comment"])
                )
            conn.commit()
            conn.close()

        await telegram_bot.send_notification(
            f"✅ <b>New Account Connected</b>\n\n"
            f"Login: {data.login}\n"
            f"Server: {data.server}\n"
            f"Platform: {data.platform}\n"
            f"User: {user['username']}"
        )

    return {
        "success": True,
        "account_id": account_id,
        "is_connected": is_connected,
        "message": "Account added successfully" + (" and connected" if is_connected else " (will connect when MT5 is available)")
    }


@app.get("/api/accounts")
async def get_accounts(request: Request):
    user = get_current_user(request)

    if user["role"] == "owner":
        accounts = db.execute(
            """SELECT ta.*, u.username as owner_username FROM trading_accounts ta
               JOIN users u ON ta.user_id = u.id ORDER BY ta.id"""
        )
    else:
        accounts = db.execute(
            "SELECT * FROM trading_accounts WHERE user_id = ? ORDER BY id",
            (user["id"],)
        )

    result = []
    for acc in accounts:
        acc_dict = dict(acc)
        # Remove sensitive data
        acc_dict.pop("password_encrypted", None)

        # Get latest snapshot
        snapshot = db.execute_one(
            "SELECT * FROM account_snapshots WHERE account_id = ? ORDER BY id DESC LIMIT 1",
            (acc["id"],)
        )
        if snapshot:
            acc_dict["latest_snapshot"] = dict(snapshot)
        else:
            acc_dict["latest_snapshot"] = None

        # Count open positions
        pos_count = db.execute_one(
            "SELECT COUNT(*) as cnt FROM open_positions WHERE account_id = ?",
            (acc["id"],)
        )
        acc_dict["open_positions_count"] = pos_count["cnt"] if pos_count else 0

        result.append(acc_dict)

    return {"accounts": result}


@app.get("/api/accounts/{account_id}")
async def get_account_detail(account_id: int, request: Request):
    user = get_current_user(request)

    if user["role"] == "owner":
        account = db.execute_one("SELECT * FROM trading_accounts WHERE id = ?", (account_id,))
    else:
        account = db.execute_one(
            "SELECT * FROM trading_accounts WHERE id = ? AND user_id = ?",
            (account_id, user["id"])
        )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    acc_dict = dict(account)

    # Live data if MT5 available and account is connected
    if MT5_AVAILABLE and account["is_connected"]:
        live_info = mt5_mgr.get_account_info(
            account["login"], account["password_encrypted"], account["server"]
        )
        live_positions = mt5_mgr.get_open_positions(
            account["login"], account["password_encrypted"], account["server"]
        )
        acc_dict["live_info"] = live_info
        acc_dict["live_positions"] = live_positions
    else:
        # From database
        snapshot = db.execute_one(
            "SELECT * FROM account_snapshots WHERE account_id = ? ORDER BY id DESC LIMIT 1",
            (account_id,)
        )
        positions = db.execute(
            "SELECT * FROM open_positions WHERE account_id = ? ORDER BY open_time DESC",
            (account_id,)
        )
        acc_dict["live_info"] = dict(snapshot) if snapshot else None
        acc_dict["live_positions"] = [dict(p) for p in positions]

    acc_dict.pop("password_encrypted", None)
    return acc_dict


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int, request: Request):
    user = get_current_user(request)

    if user["role"] == "owner":
        account = db.execute_one("SELECT * FROM trading_accounts WHERE id = ?", (account_id,))
    else:
        account = db.execute_one(
            "SELECT * FROM trading_accounts WHERE id = ? AND user_id = ?",
            (account_id, user["id"])
        )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    db.execute_update("DELETE FROM trading_accounts WHERE id = ?", (account_id,))
    return {"success": True, "message": "Account deleted"}


@app.post("/api/accounts/{account_id}/reconnect")
async def reconnect_account(account_id: int, request: Request):
    user = get_current_user(request)

    if user["role"] == "owner":
        account = db.execute_one("SELECT * FROM trading_accounts WHERE id = ?", (account_id,))
    else:
        account = db.execute_one(
            "SELECT * FROM trading_accounts WHERE id = ? AND user_id = ?",
            (account_id, user["id"])
        )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if MT5_AVAILABLE:
        result = mt5_mgr.connect_account(
            account["login"], account["password_encrypted"], account["server"]
        )
        if result["success"]:
            db.execute_update(
                "UPDATE trading_accounts SET is_connected = 1, last_update = ? WHERE id = ?",
                (datetime.now().isoformat(), account_id)
            )
            return {"success": True, "message": "Account reconnected", "data": result}
        else:
            db.execute_update("UPDATE trading_accounts SET is_connected = 0 WHERE id = ?", (account_id,))
            return {"success": False, "message": result.get("error", "Connection failed")}
    else:
        return {"success": False, "message": "MT5 not available on this server"}


# ─── API Routes: Open Positions ──────────────────────────────

@app.get("/api/accounts/{account_id}/positions")
async def get_positions(account_id: int, request: Request):
    user = get_current_user(request)

    if user["role"] != "owner":
        account = db.execute_one(
            "SELECT id FROM trading_accounts WHERE id = ? AND user_id = ?",
            (account_id, user["id"])
        )
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

    # Try live data first
    account = db.execute_one("SELECT * FROM trading_accounts WHERE id = ?", (account_id,))
    if account and MT5_AVAILABLE and account["is_connected"]:
        positions = mt5_mgr.get_open_positions(
            account["login"], account["password_encrypted"], account["server"]
        )
        return {"positions": positions, "source": "live"}

    # Fallback to DB
    positions = db.execute(
        "SELECT * FROM open_positions WHERE account_id = ? ORDER BY open_time DESC",
        (account_id,)
    )
    return {"positions": [dict(p) for p in positions], "source": "database"}


# ─── API Routes: Trade History ────────────────────────────────

@app.get("/api/accounts/{account_id}/history")
async def get_trade_history(account_id: int, request: Request,
                            days: int = Query(90, ge=1, le=3650)):
    user = get_current_user(request)

    if user["role"] != "owner":
        account = db.execute_one(
            "SELECT id FROM trading_accounts WHERE id = ? AND user_id = ?",
            (account_id, user["id"])
        )
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

    # Try to fetch fresh from MT5
    account = db.execute_one("SELECT * FROM trading_accounts WHERE id = ?", (account_id,))
    if account and MT5_AVAILABLE and account["is_connected"]:
        history = mt5_mgr.get_trade_history(
            account["login"], account["password_encrypted"], account["server"],
            days_back=days
        )
        if history:
            return {"history": history, "source": "live", "count": len(history)}

    # Fallback to DB
    history = db.execute(
        "SELECT * FROM trade_history WHERE account_id = ? ORDER BY close_time DESC",
        (account_id,)
    )
    return {"history": [dict(h) for h in history], "source": "database", "count": len(history)}


# ─── API Routes: Analytics ───────────────────────────────────

@app.get("/api/accounts/{account_id}/analytics")
async def get_analytics(account_id: int, request: Request):
    user = get_current_user(request)

    if user["role"] != "owner":
        account = db.execute_one(
            "SELECT id FROM trading_accounts WHERE id = ? AND user_id = ?",
            (account_id, user["id"])
        )
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

    # Get trade history
    account = db.execute_one("SELECT * FROM trading_accounts WHERE id = ?", (account_id,))
    trades = []

    if account and MT5_AVAILABLE and account["is_connected"]:
        trades = mt5_mgr.get_trade_history(
            account["login"], account["password_encrypted"], account["server"]
        )

    if not trades:
        history = db.execute(
            "SELECT * FROM trade_history WHERE account_id = ? ORDER BY close_time",
            (account_id,)
        )
        trades = [dict(h) for h in history]

    stats = AnalyticsEngine.calculate_statistics(trades)

    # Get equity snapshots for chart
    snapshots = db.execute(
        """SELECT balance, equity, floating_pnl, drawdown_pct, timestamp
           FROM account_snapshots WHERE account_id = ?
           ORDER BY timestamp ASC""",
        (account_id,)
    )

    stats["equity_snapshots"] = [dict(s) for s in snapshots]

    return stats


@app.get("/api/analytics/overview")
async def get_analytics_overview(request: Request):
    user = get_current_user(request)

    if user["role"] == "owner":
        accounts = db.execute("SELECT * FROM trading_accounts")
    else:
        accounts = db.execute(
            "SELECT * FROM trading_accounts WHERE user_id = ?", (user["id"],)
        )

    overview = []
    total_balance = 0
    total_equity = 0
    total_profit = 0

    for acc in accounts:
        snapshot = db.execute_one(
            "SELECT * FROM account_snapshots WHERE account_id = ? ORDER BY id DESC LIMIT 1",
            (acc["id"],)
        )

        history = db.execute(
            "SELECT * FROM trade_history WHERE account_id = ?",
            (acc["id"],)
        )
        trades = [dict(h) for h in history]
        stats = AnalyticsEngine.calculate_statistics(trades)

        acc_data = {
            "id": acc["id"],
            "nickname": acc["nickname"],
            "login": acc["login"],
            "platform": acc["platform"],
            "server": acc["server"],
            "is_connected": acc["is_connected"],
            "balance": snapshot["balance"] if snapshot else 0,
            "equity": snapshot["equity"] if snapshot else 0,
            "drawdown_pct": snapshot["drawdown_pct"] if snapshot else 0,
            "floating_pnl": snapshot["floating_pnl"] if snapshot else 0,
            "total_profit": stats["total_profit"],
            "win_rate": stats["win_rate"],
            "total_trades": stats["total_trades"],
            "profit_factor": stats["profit_factor"]
        }

        if snapshot:
            total_balance += snapshot["balance"]
            total_equity += snapshot["equity"]
        total_profit += stats["total_profit"]

        overview.append(acc_data)

    return {
        "accounts": overview,
        "totals": {
            "balance": round(total_balance, 2),
            "equity": round(total_equity, 2),
            "profit": round(total_profit, 2),
            "account_count": len(overview)
        }
    }


# ─── API Routes: Charts / Symbol Data ────────────────────────

@app.get("/api/charts/candles")
async def get_candles(symbol: str = "EURUSD", timeframe: str = "H1",
                      count: int = 500, request: Request = None):
    if MT5_AVAILABLE:
        candles = mt5_mgr.get_symbol_data(symbol, timeframe, count)
        return {"candles": candles, "symbol": symbol, "timeframe": timeframe}
    return {"candles": [], "symbol": symbol, "timeframe": timeframe,
            "message": "MT5 not available"}


@app.get("/api/charts/symbols")
async def get_symbols(request: Request):
    if MT5_AVAILABLE:
        symbols = mt5_mgr.get_symbols()
        return {"symbols": symbols}
    return {"symbols": []}


# ─── API Routes: Admin (Owner Only) ──────────────────────────

@app.get("/api/admin/users")
async def admin_get_users(request: Request):
    user = get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    users = db.execute("SELECT id, username, role, plan, created_at, last_login, is_active FROM users ORDER BY id")
    return {"users": [dict(u) for u in users]}


@app.post("/api/admin/users/plan")
async def admin_update_plan(data: PlanUpdate, request: Request):
    user = get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    if data.plan not in PLAN_LIMITS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    db.execute_update(
        "UPDATE users SET plan = ? WHERE username = ?",
        (data.plan, data.username)
    )
    return {"success": True, "message": f"Plan updated to {data.plan} for {data.username}"}


@app.post("/api/admin/telegram/configure")
async def admin_configure_telegram(data: TelegramConfig, request: Request):
    user = get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    db.execute(
        "INSERT OR REPLACE INTO telegram_config (id, bot_token, is_active) VALUES (1, ?, 1)",
        (data.bot_token,)
    )

    # Start the bot
    success = await telegram_bot.start_bot(data.bot_token)

    return {
        "success": success,
        "message": "Telegram bot configured" + (" and started" if success else " but failed to start")
    }


@app.get("/api/admin/telegram/status")
async def admin_telegram_status(request: Request):
    user = get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    config = db.execute_one("SELECT * FROM telegram_config ORDER BY id DESC LIMIT 1")

    return {
        "configured": bool(config and config["bot_token"]),
        "is_running": telegram_bot.is_running,
        "owner_chat_id": telegram_bot.owner_chat_id,
        "has_token": bool(config and config["bot_token"])
    }


@app.post("/api/admin/backup")
async def admin_create_backup(request: Request):
    user = get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    backup_path = db.create_backup()
    return FileResponse(
        backup_path,
        filename=os.path.basename(backup_path),
        media_type="application/octet-stream"
    )


@app.get("/api/admin/system")
async def admin_system_info(request: Request):
    user = get_current_user(request)
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    users_count = db.execute_one("SELECT COUNT(*) as cnt FROM users")
    accounts_count = db.execute_one("SELECT COUNT(*) as cnt FROM trading_accounts")
    trades_count = db.execute_one("SELECT COUNT(*) as cnt FROM trade_history")
    snapshots_count = db.execute_one("SELECT COUNT(*) as cnt FROM account_snapshots")

    return {
        "platform": "PutraDev Trading Monitor",
        "version": "2.0.0",
        "mt5_available": MT5_AVAILABLE,
        "telegram_running": telegram_bot.is_running,
        "database_size_mb": round(os.path.getsize(DATABASE_PATH) / 1024 / 1024, 2) if os.path.exists(DATABASE_PATH) else 0,
        "users_count": users_count["cnt"] if users_count else 0,
        "accounts_count": accounts_count["cnt"] if accounts_count else 0,
        "trades_count": trades_count["cnt"] if trades_count else 0,
        "snapshots_count": snapshots_count["cnt"] if snapshots_count else 0,
        "server_time": datetime.now().isoformat(),
        "python_version": sys.version,
        "uptime": "Running"
    }


# ─── WebSocket Endpoint ──────────────────────────────────────

@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    payload = verify_token(token)
    if not payload:
        await websocket.close(code=4001)
        return

    user = db.execute_one("SELECT * FROM users WHERE username = ?", (payload.get("sub"),))
    if not user:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    user_key = f"user_{user['id']}"
    if user_key not in ws_connections:
        ws_connections[user_key] = set()
    ws_connections[user_key].add(websocket)

    logger.info(f"WebSocket connected: {user['username']}")

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "time": datetime.now().isoformat()}))

            elif msg.get("type") == "request_update":
                account_id = msg.get("account_id")
                if account_id:
                    account = db.execute_one(
                        "SELECT * FROM trading_accounts WHERE id = ?", (account_id,)
                    )
                    if account:
                        if MT5_AVAILABLE and account["is_connected"]:
                            info = mt5_mgr.get_account_info(
                                account["login"], account["password_encrypted"], account["server"]
                            )
                            positions = mt5_mgr.get_open_positions(
                                account["login"], account["password_encrypted"], account["server"]
                            )
                        else:
                            snapshot = db.execute_one(
                                "SELECT * FROM account_snapshots WHERE account_id = ? ORDER BY id DESC LIMIT 1",
                                (account_id,)
                            )
                            info = dict(snapshot) if snapshot else None
                            db_positions = db.execute(
                                "SELECT * FROM open_positions WHERE account_id = ?",
                                (account_id,)
                            )
                            positions = [dict(p) for p in db_positions]

                        await websocket.send_text(json.dumps({
                            "type": "account_update",
                            "account_id": account_id,
                            "info": info,
                            "positions": positions,
                            "timestamp": datetime.now().isoformat()
                        }))

    except WebSocketDisconnect:
        ws_connections[user_key].discard(websocket)
        logger.info(f"WebSocket disconnected: {user['username']}")
    except Exception as e:
        ws_connections[user_key].discard(websocket)
        logger.error(f"WebSocket error: {e}")


# ─── Serve Frontend ──────────────────────────────────────────

@app.get("/style.css")
async def serve_css():
    return FileResponse("style.css", media_type="text/css")


@app.get("/")
async def serve_index():
    return FileResponse("index.html", media_type="text/html")


@app.get("/{path:path}")
async def catch_all(path: str):
    if os.path.exists(path):
        return FileResponse(path)
    return FileResponse("index.html", media_type="text/html")


# ─── Run Server ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║              PutraDev Trading Monitor Platform               ║
    ║                                                              ║
    ║  © 2026 PutraDev. All rights reserved.                       ║
    ║  PutraDev – Don't Steal                                      ║
    ║                                                              ║
    ║  Starting server on http://localhost:8000                     ║
    ║                                                              ║
    ║  Default Login:                                              ║
    ║    Username: ZachOnly                                        ║
    ║    Password: lupi123                                         ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
