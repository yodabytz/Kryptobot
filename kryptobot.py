#!/usr/bin/env python3
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import os
import platform
import time
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange
import krakenex
from pykrakenapi import KrakenAPI
from dotenv import load_dotenv
import logging
from colorama import init, Fore, Style
import yagmail
from datetime import datetime
from contextlib import contextmanager
import math
import sys
import json
import threading
import curses

# Initialize colorama for non-curses logging output
init(autoreset=True)

# Define color constants for logging/console output
TEAL = Fore.CYAN
BRIGHT_GREEN = Style.BRIGHT + Fore.GREEN
YELLOW = Fore.YELLOW
RESET = Style.RESET_ALL
SEPARATOR = "------------------------------------------------"

# Load environment variables from .env file
load_dotenv()
api_key = os.getenv('KRAKEN_API_KEY')
private_key = os.getenv('KRAKEN_PRIVATE_KEY')
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')

# FULL_NAMES dictionary: map full trading pair codes to proper crypto names.
FULL_NAMES = {
    "XXBTZUSD": "Bitcoin",
    "XETHZUSD": "Ethereum",
    "XXRPZUSD": "Ripple",
    "XLTCZUSD": "Litecoin",
    "BCHUSD": "Bitcoin Cash",
    "XDOGEZUSD": "Dogecoin",
    "ADAZUSD": "Cardano",
    "DOTZUSD": "Polkadot",
    "LINKZUSD": "Chainlink",
    "XXLMZUSD": "Stellar",
    "XMRZUSD": "Monero",
    "XTZZUSD": "Tezos",
    "EOSZUSD": "EOS",
    "XETCZUSD": "Ethereum Classic",
    "ATOMZUSD": "Cosmos",
    "ALGOZUSD": "Algorand",
    "PEPEZUSD": "Pepe"
}

# Global flags and shared data for UI and trading
exit_flag = False
logs = []                  # Global list to hold log messages for the UI
log_lock = threading.Lock()
dashboard_data_lock = threading.Lock()
latest_holdings = ""       # Holdings summary for the top pane
latest_funds = 0.0         # Available funds for the top pane

# ----------------------- Helper Sleep Function -----------------------
def sleep_with_exit(total_seconds, check_interval=1):
    """Sleep in small increments, checking for exit_flag to allow prompt shutdown."""
    global exit_flag
    elapsed = 0
    while elapsed < total_seconds and not exit_flag:
        time.sleep(check_interval)
        elapsed += check_interval

# ----------------------- Utility Functions -----------------------
def add_log(message):
    """Append a timestamped log message to the global logs list."""
    timestamped = f"{get_timestamp()} - {message}"
    with log_lock:
        logs.append(timestamped)
    logging.info(message)

def get_timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def send_email_notification(subject, contents):
    try:
        yag = yagmail.SMTP(user=EMAIL_USER, password=EMAIL_PASSWORD)
        yag.send(to=RECIPIENT_EMAIL, subject=subject, contents=contents)
        logging.info(f"Email sent: {subject}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

def login_kraken():
    if not api_key or not private_key:
        add_log("API keys not found. Please set them in the .env file.")
        logging.error("API keys not found.")
        sys.exit(1)
    kraken_api = krakenex.API(key=api_key, secret=private_key)
    kraken = KrakenAPI(kraken_api)
    logging.info("Logged into Kraken successfully.")
    return kraken, kraken_api

def clear_screen():
    if platform.system() == 'Windows':
        os.system('cls')
    else:
        os.system('clear')

def compute_indicators(ohlc):
    close_prices = ohlc['close']
    rsi_indicator = RSIIndicator(close=close_prices, window=14)
    rsi_series = rsi_indicator.rsi()
    rsi = rsi_series.iloc[-1]
    logging.debug(f"RSI Series for latest data: {rsi_series.tail()}")
    return rsi

def compute_macd_indicator(ohlc):
    macd_indicator = MACD(close=ohlc['close'])
    macd_diff = macd_indicator.macd_diff().iloc[-1]
    macd_signal = macd_indicator.macd_signal().iloc[-1]
    logging.debug(f"MACD Diff: {macd_diff}, Signal: {macd_signal}")
    return macd_diff, macd_signal

def compute_moving_averages(ohlc, short_window=50, long_window=200):
    short_sma = ohlc['close'].rolling(window=short_window).mean().iloc[-1]
    long_sma = ohlc['close'].rolling(window=long_window).mean().iloc[-1]
    logging.debug(f"Short SMA ({short_window}): {short_sma}, Long SMA ({long_window}): {long_sma}")
    return short_sma, long_sma

def compute_atr(ohlc, window=14):
    atr_indicator = AverageTrueRange(high=ohlc['high'], low=ohlc['low'], close=ohlc['close'], window=window)
    atr = atr_indicator.average_true_range().iloc[-1]
    logging.debug(f"ATR ({window}): {atr}")
    return atr

def get_account_balances(kraken):
    sleep_with_exit(2.5)
    try:
        balance = kraken.get_account_balance()
        sleep_with_exit(2.5)
        balance_tradable = kraken.get_trade_balance()
        logging.debug(f"Fetched account balances:\n{balance}")
        logging.debug(f"Fetched tradable account balances:\n{balance_tradable}")
        return balance, balance_tradable
    except Exception as e:
        logging.error(f"Error fetching account balances: {e}")
        return pd.DataFrame(), pd.DataFrame()

def get_buying_power(balance, balance_tradable):
    try:
        balance.columns = [col.lower() for col in balance.columns]
        balance_tradable.columns = [col.lower() for col in balance_tradable.columns]
        balance.index = [idx.upper().strip() for idx in balance.index]
        balance_tradable.index = [idx.upper().strip() for idx in balance_tradable.index]
        if "ZUSD" in balance_tradable.index and "vol" in balance_tradable.columns:
            zusd_balance = float(balance_tradable.loc["ZUSD", "vol"])
            logging.debug(f"Retrieved ZUSD from tradable balance: {zusd_balance}")
        elif "ZUSD" in balance.index and "vol" in balance.columns:
            zusd_balance = float(balance.loc["ZUSD", "vol"])
            logging.debug(f"Retrieved ZUSD from total balance: {zusd_balance}")
        else:
            logging.warning("ZUSD balance not found.")
            return 0.0
        return zusd_balance
    except Exception as e:
        logging.error(f"Error retrieving ZUSD balance: {e}")
        return 0.0

def get_min_order_size(pair, kraken):
    sleep_with_exit(2.5)
    try:
        asset_pairs = kraken.get_tradable_asset_pairs()
        min_order = asset_pairs.loc[pair, 'lot']
        min_order_float = float(min_order)
        logging.debug(f"Minimum order size for {pair}: {min_order_float}")
        return min_order_float
    except Exception as e:
        logging.error(f"Error fetching minimum order size for {pair}: {e}")
        return 0.0

def place_order(kraken_api, pair, action, volume, stop_loss=None, take_profit=None):
    try:
        order_type = 'buy' if action == 'buy' else 'sell'
        orderdata = {
            'pair': pair,
            'type': order_type,
            'ordertype': 'market',
            'volume': str(volume),
            'validate': False
        }
        response = kraken_api.query_private('AddOrder', orderdata)
        if response['error']:
            logging.error(f"Order placement error for {pair}: {response['error']}")
            logging.debug(f"Full response: {json.dumps(response, indent=2)}")
            return False, None
        order_result = response['result']
        order_id = order_result.get('txid', [])[0] if 'txid' in order_result else None
        if order_id:
            msg = f"Placed {action} order for {volume} {pair} (Order ID: {order_id})"
            logging.info(msg)
            send_email_notification(
                subject=f"Kraken Bot: {action.capitalize()} Order Executed",
                contents=f"Placed {action} order for {volume} {pair} at {get_timestamp()}.\nOrder ID: {order_id}"
            )
            is_filled = check_order_filled(kraken_api, order_id)
            if is_filled:
                add_log(f"{BRIGHT_GREEN}{action.capitalize()} order filled for {volume} {pair} (Order ID: {order_id}){RESET}")
                logging.info(f"Order {order_id} for {pair} has been filled.")
                return True, order_id
            else:
                add_log(f"{YELLOW}{action.capitalize()} order for {volume} {pair} (Order ID: {order_id}) is not yet filled.{RESET}")
                logging.warning(f"Order {order_id} for {pair} is not yet filled.")
                return False, order_id
        else:
            logging.error(f"No Order ID returned for {pair} {action} order.")
            return False, None
    except Exception as e:
        logging.error(f"Failed to place {action} order for {pair}: {e}")
        send_email_notification(
            subject=f"Kraken Bot: Failed to Place {action.capitalize()} Order",
            contents=f"Failed to place {action} order for {pair} at {get_timestamp()}.\nError: {e}"
        )
        return False, None

def check_order_filled(kraken_api, order_id):
    try:
        sleep_with_exit(2.5)
        response = kraken_api.query_private('QueryOrders', {'txid': order_id})
        if response['error']:
            logging.error(f"Error querying order status for {order_id}: {response['error']}")
            return False
        order_info = response['result'].get(order_id, {})
        status = order_info.get('status', '')
        filled = (status == 'closed')
        logging.debug(f"Order {order_id} status: {status}")
        return filled
    except Exception as e:
        logging.error(f"Failed to query order status for {order_id}: {e}")
        return False

def track_holdings(kraken):
    try:
        balance, balance_tradable = get_account_balances(kraken)
        holdings = {}
        for asset in balance.index:
            total_vol = float(balance.loc[asset, 'vol']) if 'vol' in balance.columns else 0.0
            tradable_vol = float(balance_tradable.loc[asset, 'vol']) if (asset in balance_tradable.index and 'vol' in balance_tradable.columns) else 0.0
            holdings[asset] = {'total': total_vol, 'tradable': tradable_vol}
        return holdings
    except Exception as e:
        logging.error(f"Error tracking holdings: {e}")
        return {}

@contextmanager
def handle_exceptions():
    try:
        yield
    except Exception as e:
        add_log(f"Warning: Unexpected error: {e}")
        logging.error(f"Unexpected error: {e}")
        send_email_notification(
            subject="Kraken Bot: Unexpected Error",
            contents=f"An unexpected error occurred at {get_timestamp()}.\nError: {e}"
        )
        sleep_with_exit(60)

# ----------------------- Watchlist Helper -----------------------
def read_watchlist():
    """Reads trading pair codes from watchlist.txt (one per line) and returns a list."""
    try:
        with open("watchlist.txt", "r") as f:
            lines = f.readlines()
        watchlist = [line.strip() for line in lines if line.strip() != ""]
        add_log(f"Loaded watchlist with {len(watchlist)} assets.")
        return watchlist
    except Exception as e:
        add_log(f"Error reading watchlist.txt: {e}")
        return []

# ----------------------- Dashboard Helper -----------------------
def format_holdings(holdings):
    """Convert holdings dictionary into a list of strings (one per holding)."""
    parts = []
    for asset, info in holdings.items():
        if info['total'] > 0:
            parts.append(f"{asset}: Total={info['total']} | Tradable={info['tradable']}")
    return parts if parts else ["No Holdings"]

# ----------------------- Curses UI Functions -----------------------
def ui_loop(stdscr):
    global exit_flag
    curses.start_color()
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)

    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)    # Dashboard header
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)   # Funds display
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Log messages
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)   # Holdings list

    max_y, max_x = stdscr.getmaxyx()
    top_height = max(7, max_y // 4)
    bottom_height = max_y - top_height - 2

    top_win = curses.newwin(top_height, max_x, 0, 0)
    bottom_win = curses.newwin(bottom_height, max_x, top_height + 1, 0)
    bottom_win.scrollok(True)

    scroll_offset = 0

    while not exit_flag:
        top_win.erase()
        top_win.border()
        top_win.addstr(1, 2, "Kraken Bot Dashboard", curses.color_pair(1) | curses.A_BOLD)
        with dashboard_data_lock:
            funds = latest_funds
            holdings_list = latest_holdings if isinstance(latest_holdings, list) else latest_holdings.split(" | ")
        top_win.addstr(2, 2, f"Available Funds: ${funds:.2f}", curses.color_pair(2))
        top_win.addstr(3, 2, "Holdings:", curses.color_pair(1) | curses.A_BOLD)
        for idx, holding in enumerate(holdings_list):
            if 4 + idx < top_height - 1:
                top_win.addstr(4 + idx, 4, holding, curses.color_pair(4))
        top_win.refresh()

        bottom_win.erase()
        bottom_win.border()
        with log_lock:
            displayable_logs = logs[max(0, len(logs) - (bottom_height - 2 + scroll_offset)) : len(logs) - scroll_offset]
        for idx, log_line in enumerate(displayable_logs):
            if idx >= bottom_height - 2:
                break
            try:
                bottom_win.addstr(idx+1, 2, log_line[:max_x-4], curses.color_pair(3))
            except curses.error:
                pass
        bottom_win.refresh()

        try:
            key = stdscr.getch()
            if key == curses.KEY_UP:
                if scroll_offset < max(0, len(logs) - (bottom_height - 2)):
                    scroll_offset += 1
            elif key == curses.KEY_DOWN:
                scroll_offset = max(0, scroll_offset - 1)
            elif key == ord('q'):
                add_log("Q key pressed. Shutting down.")
                exit_flag = True
        except Exception:
            pass

        time.sleep(0.5)

# ----------------------- Trading Loop -----------------------
def trading_loop():
    global exit_flag, latest_holdings, latest_funds
    with handle_exceptions():
        kraken, kraken_api = login_kraken()
        while not exit_flag:
            watchlist = read_watchlist()
            if not watchlist:
                add_log("Watchlist is empty. Sleeping for 5 minutes.")
                sleep_with_exit(300)
                continue

            balance, balance_tradable = get_account_balances(kraken)
            buying_power = get_buying_power(balance, balance_tradable)
            add_log(f"Available buying power: ${buying_power:.2f}")
            holdings = track_holdings(kraken)
            formatted_holdings = format_holdings(holdings)
            add_log(f"Current Holdings: {' | '.join(formatted_holdings)}")

            with dashboard_data_lock:
                latest_funds = buying_power
                latest_holdings = formatted_holdings

            if buying_power <= 0:
                add_log("No available buying power. Please fund your account.")
                sleep_with_exit(300)
                continue

            total_allocated = 0.0
            trades = []

            for pair in watchlist:
                if exit_flag:
                    break

                full_name = FULL_NAMES.get(pair, pair)
                add_log(f"Checking {full_name}")
                sleep_with_exit(2.5)
                try:
                    # Fetch OHLC data (daily timeframe)
                    ohlc, last = kraken.get_ohlc_data(pair, interval=1440, ascending=True)
                    if ohlc.empty or ohlc['close'].iloc[-1] == 0.0:
                        raise ValueError("Invalid OHLC data received.")
                    current_price = ohlc['close'].iloc[-1]
                    previous_close = ohlc['close'].iloc[-2]
                except Exception as e:
                    add_log(f"Skipping {pair}: {e}")
                    continue

                if not (0 < current_price < 1e10):
                    add_log(f"Invalid price ${current_price:.2f} for {pair}. Skipping.")
                    continue

                # Compute indicators
                rsi = compute_indicators(ohlc)  # RSI (14)
                macd_diff, macd_signal = compute_macd_indicator(ohlc)  # MACD (unused here but available)
                short_sma, long_sma = compute_moving_averages(ohlc, 50, 200)  # 50/200-day SMA
                atr = compute_atr(ohlc, 14)  # ATR for volatility

                # Dynamic thresholds based on ATR
                buy_threshold = previous_close * (1 - 0.15 - atr / previous_close)  # 15% + ATR adjustment
                sell_loss_threshold = previous_close * (1 - 0.07 - atr / previous_close)  # 7% + ATR
                sell_profit_threshold = previous_close * (1 + 0.25 + atr / previous_close)  # 25% + ATR

                # Trend filter: Only trade in direction of 50/200 SMA trend
                is_uptrend = short_sma > long_sma

                # Buy logic: Oversold RSI, price dip, and uptrend confirmation
                if rsi < 30 and current_price <= buy_threshold and is_uptrend:
                    # Risk-adjusted position sizing (1% risk per trade)
                    risk_per_trade = buying_power * 0.01  # 1% of account
                    stop_loss = current_price - 2 * atr
                    if stop_loss >= current_price:  # Prevent invalid stop-loss
                        add_log(f"Invalid stop-loss for {pair}. Skipping.")
                        continue
                    position_size = risk_per_trade / (current_price - stop_loss)
                    volume = min(position_size, (buying_power * 0.20 - total_allocated) / current_price)
                    volume = round(volume, 8)
                    min_order = get_min_order_size(pair, kraken)
                    if volume < min_order:
                        add_log(f"Volume {volume} for {pair} below min order {min_order}. Skipping.")
                        continue
                    success, order_id = place_order(kraken_api, pair, 'buy', volume)
                    if success:
                        trades.append({'Type': 'Buy', 'Symbol': pair, 'Price': current_price, 'Date': datetime.now(), 'StopLoss': stop_loss})
                        total_allocated += volume * current_price

                # Sell logic: Overbought RSI or significant price move
                asset_code = pair[:4]
                tradable_vol = float(balance_tradable.loc[asset_code, 'vol']) if (asset_code in balance_tradable.index and 'vol' in balance_tradable.columns) else 0.0
                if tradable_vol > 0 and (rsi > 70 or current_price <= sell_loss_threshold or current_price >= sell_profit_threshold):
                    volume = round(tradable_vol, 8)
                    success, order_id = place_order(kraken_api, pair, 'sell', volume)
                    if success:
                        trades.append({'Type': 'Sell', 'Symbol': pair, 'Price': current_price, 'Date': datetime.now()})

            if trades:
                for trade in trades:
                    trade_type = trade['Type']
                    trade_symbol = trade['Symbol']
                    trade_price = trade['Price']
                    trade_date = trade['Date'].strftime('%Y-%m-%d %H:%M:%S')
                    if trade_type == 'Buy':
                        add_log(f"{BRIGHT_GREEN}Buy {trade_symbol} at ${trade_price:.2f} on {trade_date} (SL: ${trade['StopLoss']:.2f}){RESET}")
                    elif trade_type == 'Sell':
                        add_log(f"{BRIGHT_GREEN}Sell {trade_symbol} at ${trade_price:.2f} on {trade_date}{RESET}")
            else:
                add_log(SEPARATOR)
                add_log("No trades executed in this iteration.")

            sleep_with_exit(300)

        add_log(f"{TEAL}Script terminated gracefully.{RESET}")
        logging.info("Script terminated gracefully.")

# ----------------------- Main Function -----------------------
def main():
    global exit_flag
    trading_thread = threading.Thread(target=trading_loop, daemon=True)
    trading_thread.start()

    # Run curses UI in the main thread; this blocks until exit_flag is set.
    curses.wrapper(ui_loop)

    exit_flag = True
    trading_thread.join()

if __name__ == "__main__":
    main()
