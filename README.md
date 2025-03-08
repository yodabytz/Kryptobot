# Kryptobot
Kryptobot is an automated trading bot for Kraken’s cryptocurrency exchange. It monitors market data, executes trades based on customizable strategies, and displays real‑time information on a dynamic dashboard. Use at your own risk.

## Features
Real-time market monitoring via Kraken API
Customizable trading strategies
Dynamic UI with live logs and holdings dashboard
Prerequisites
Python 3.8+
Windows Users: Install windows-curses>=2.2.0

## Installation
* Clone the repository:

```
git clone https://github.com/yourusername/kryptobot.git
cd kryptobot
```
* Install dependencies:
```
pip install -r requirements.txt
```
### Set up your environment:
* Create a .env file with your credentials (see .env.example).

* Update your watchlist.txt with Kraken trading pair codes.
* Modify any other configuration as required.

## Usage
Run the bot with:
```
python kryptobot.py
Press q in the terminal UI to quit the bot gracefully.
```
## License
This project is licensed under the MIT License.
