This is a blueprint and structural architecture overview for the $BWET Tracking Daemon.
Below is an analytical overview of the code's structural dependencies, operational modes, and execution lifecycle.

🔩 System Dependencies & Prerequisites

Before executing the daemon for bwetgrab.py, ensure the following environment configuration and system dependencies are fully initialized:
• Python Libraries: PIP install the following in a virtual environment: pandas, numpy, BeautifulSoup, and Selenium with their respected dependecies.
• Environment Configuration File (bwet.env): Must contain valid entries for keys like SAFETY_BUFFER_SCALE, ACCOUNT_CASH, GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD, and TARGET_BOOST_PHONE.
• Operating System Layers: The daemon relies on a Linux desktop environment (DISPLAY=:0) with notify-send and paplay installed for native audio-visual notifications.
• Headless Browser Drivers: Selenium requires a locally compatible version of Google Chrome and chromedriver mapped to the system path.

🗺️ Core Architecture & Operational Lifecycle

The logic flow of complete_production_bwet_system() is divided into 9 critical architectural stages:
[yfinance Feed] ------> [Technical Math] ------> [Selenium Scraper] -----> [Options Chain]
($BWET & Brent Oil)      (RSI, ATR, EMA10)       (Amplify Holdings)       (Open Interest)
                                                                                  |
[System Actions] <----- [Alert Gateways] <----- [Macro Evaluation] <----- [Risk Sizing]
(Desktop/Audio)         (SMS / Ledger File)       (Action Signals)        (Trailing Floor)

1. Data Ingestion Pipeline: Pulls 6 months of daily historical data for $BWET and Brent Crude Futures (BZ=F), enabling prepost=True to include extended hours trading prints.
2. Technical Indicator Layer: Computes rolling 14-day RSI, 14-day ATR, a 20-period moving average of volatility, 10-day EMA, and 14-day momentum vectors.
3. Physical Basket Monitor: Runs a headless Selenium instance to scrape the official Amplify ETF holdings page, determining whether the published data matches today's date and parsing the raw table for TD3C (VLCC) and TD20 (Suezmax) asset lots.
4. Options Open Interest (OI) Scraper: Pulls the nearest options contract chain to identify call open interest expansions against a calculated baseline volume.
5. Capital Risk Engine: Extrapolates a trailing stop-loss line based on the 5-day peak price minus a scaled ATR buffer, capping transaction risk strictly at 2% of equity capital.
6. Macro Evaluation Engine: Examines historical ledger deltas to spot anomalies, such as a drop in physical freight lots combined with elevated paper prices.
7. Telemetry Spreadsheet Logging: Appends 11 financial metrics into a local tracking history file (trading_ledger.csv).
8. Boost Mobile Email-to-SMS Gateway: Forwards critical network alerts to the target mobile device using secure Google SMTP handshakes when an actionable risk trigger occurs.
9. Insulated Desktop Routing: Pushes immediate system notifications to the user's desktop display bus alongside instant message audio cues.

⏱️ Daemon Control Loop Execution Policy

When launched as a persistent script, the daemon implements strict daily gating across a 7-day week using the following timing constraints:

Target Window	Hour Range (CST)	Lockout Behavior
Morning Window	07:00 – 08:30	Suspends checking once a fresh basket date match is found.
Afternoon Window	15:30 – 16:00	Suspends checking after a successful tracking pass is logged.
Passive Deep-Sleep	Outside Active Hours	Throttles background processing to a 15-minute sleep cycle.

🛠️ Execution Manual

To run a temporary, immediate diagnostic verification scan to test your connection layers, web scrapers, and local directories without entering the looping background state, execute the script with the test flag:
bash
python3 /home/ldaugherty/bwetgrab.py --test
Use code with caution.

For continuous 24/7 autonomous production monitoring, run the script detached as a background process or system service:
bash
nohup python3 /home/ldaugherty/bwetgrab.py > ~/bwet_daemon.log 2>&1 &
Use code with caution.

Enjoy!
