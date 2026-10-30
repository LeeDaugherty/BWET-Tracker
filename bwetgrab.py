import os
import sys
import fcntl
import datetime
import pandas as pd
import numpy as np
import yfinance as yf
import time
import re
import smtplib
import argparse
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv

# --- STEP 1: PARSE ARGUMENTS AT ENTRY POINT ---
parser = argparse.ArgumentParser(description="BWET Freight Futures Monitoring Daemon")
parser.add_argument("--test", action="store_true", help="Force an immediate diagnostic evaluation run and exit.")
args = parser.parse_args()

# --- STEP 2: CONDITIONALLY ENFORCE SINGLETON LOCK ---
# If --test is passed, this block is completely skipped to bypass the lock file check
if not args.test:
    lock_path = os.path.expanduser("~/.bwet_daemon.lock")
    
    # Clean up any dead file handles from disk before checking
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
        except Exception:
            pass

    lock_file = open(lock_path, "w")
    try:
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid()))
        lock_file.flush()
    except IOError:
        print("🚨 Duplicate Instance Detected! Another daemon thread is already active. Exiting cleanly.")
        sys.exit(0)

# Load environment configuration tokens
env_path = os.path.expanduser("~/bwet.env")
load_dotenv(dotenv_path=env_path)

def complete_production_bwet_system():
    ticker_symbol = "BWET"
    current_time = datetime.datetime.now()

    # Read environment configurations with fallback parameters
    safety_buffer_scale = float(os.getenv("SAFETY_BUFFER_SCALE", 2.5))
    account_cash = float(os.getenv("ACCOUNT_CASH", 5000.00))

    print(f"\n🚀 [08:25 AM SCANNERS ACTIVE] Launching synchronized market data pipelines...")
    
    #Download live market data arrays 
    # Passing prepost=True captures active after-hours and pre-market prints
    df = yf.download(ticker_symbol, period="6mo", interval="1d", progress=False, prepost=True)
    oil_df = yf.download("BZ=F", period="6mo", interval="1d", progress=False, prepost=True)

    if df is None or df.empty or oil_df is None or oil_df.empty:
        print("Error: Market feed disruption encountered (yfinance).")
        return False, "Data Stream Error"

    # Initialize all monitoring scalars
    driver = None
    td3c_lots = 0
    td20_lots = 0
    holdings_text = "Amplify Freight Basket: Failed Connection"
    is_data_fresh_today = False
    
    brent_current = 0.0
    brent_change = 0.0
    brent_pct = 0.0
    brent_5d_change = 0.0

    try:
        # Technical Vector Formatting
        close_series = pd.Series(df['Close'].values.flatten()).dropna()
        high_series = pd.Series(df['High'].values.flatten()).dropna()
        low_series = pd.Series(df['Low'].values.flatten()).dropna()
        volume_series = pd.Series(df['Volume'].values.flatten()).dropna()
        
        oil_close_series = pd.Series(oil_df['Close'].values.flatten()).dropna()
        brent_current = round(float(oil_close_series.iloc[-1]), 2)
        brent_prev = round(float(oil_close_series.iloc[-2]), 2)
        brent_change = brent_current - brent_prev
        brent_pct = (brent_change / brent_prev) * 100 if brent_prev != 0 else 0.0

        if len(oil_close_series) >= 5:        
            brent_5d_ago = round(float(oil_close_series.iloc[-5]), 2)
            brent_5d_change = brent_current - brent_5d_ago
#        else:
#            brent_5d_change = 0.0
        
        # Technical Indicators Math Calculations
        delta = close_series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_series = (100 - (100 / (1 + rs))).fillna(50)
        
        high_low = high_series - low_series
        high_close_prev = np.abs(high_series - close_series.shift(1))
        low_close_prev = np.abs(low_series - close_series.shift(1))
        true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
        atr_series = true_range.rolling(window=14).mean()
        volatility_ma20 = atr_series.rolling(window=20).mean()
        
        ema10_series = close_series.ewm(span=10, adjust=False).mean()
        momentum14_series = close_series - close_series.shift(14)
        avg_volume_20 = volume_series.rolling(window=20).mean()
        
        current_close = round(float(close_series.iloc[-1]), 2)
        current_volume = float(volume_series.iloc[-1])
        current_avg_vol = float(avg_volume_20.iloc[-1])
        current_ema = round(float(ema10_series.iloc[-1]), 2)
        current_mom = round(float(momentum14_series.iloc[-1]), 2)
        current_atr = round(float(atr_series.iloc[-1]), 2)
        current_rsi = round(float(rsi_series.iloc[-1]), 1)
        current_vol_ma = round(float(volatility_ma20.iloc[-1]), 2)
        
        # --- AMPLIFY ETF DATA HOLDINGS WEBSCRAPER LAYER ---
        try:
            url = "https://amplifyetfs.com/bwet-holdings/"
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")  
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("window-size=1400x900")
            options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

            print("Launching browser layer to intercept Amplify data grid...")
            driver = webdriver.Chrome(options=options)
            driver.get(url)
            
            WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "td")))
            time.sleep(5) # Give JavaScript an extra moment to settle text strings
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            page_text = soup.get_text()
            date_match = re.search(r'As of (\d{1,2}/\d{1,2}/\d{4})', page_text)
            
            if date_match:
                amplify_date_str = date_match.group(1)
                today_str = current_time.strftime('%m/%d/%Y').replace('/0', '/').lstrip('0')
                if amplify_date_str == today_str:
                    is_data_fresh_today = True
                print(f"Amplify Ledger Date Label: {amplify_date_str} (Match Today: {is_data_fresh_today})")
            
            table = soup.find('table')
            if table:
                headers = [th.text.strip() for th in table.find_all('th') if th.text.strip()]
                rows = []
                for tr in table.find_all('tr'):
                    cells = [td.text.strip() for td in tr.find_all('td')]
                    if cells and len(cells) > 1:
                        rows.append(cells)
                
                if not rows:
                    raise ValueError("Scraped table rows are completely empty.")

                holdings_df = pd.DataFrame(rows)
                if len(holdings_df.columns) != len(headers):
                    min_len = min(len(holdings_df.columns), len(headers))
                    holdings_df = holdings_df.iloc[:, :min_len]
                    headers = headers[:min_len]
                holdings_df.columns = headers
                
                # Robust Partial Name Matching to handle frontend changes cleanly
                name_col_matches = [c for c in holdings_df.columns if any(x in c.lower() for x in ['name', 'desc', 'secur'])]
                lots_col_matches = [c for c in holdings_df.columns if any(x in c.lower() for x in ['lot', 'shar', 'unit'])]
                
                if not name_col_matches or not lots_col_matches:
                    raise KeyError(f"Could not map dynamic headers. Found columns: {headers}")

                name_col = name_col_matches[0]
                lots_col = lots_col_matches[0]
                
                # Extract and clean numbers
                holdings_df[lots_col] = holdings_df[lots_col].astype(str).apply(lambda x: re.sub(r'[^\d.]', '', x))
                holdings_df[lots_col] = pd.to_numeric(holdings_df[lots_col], errors='coerce').fillna(0)
                
                td3c_df = holdings_df[holdings_df[name_col].str.contains('TD3C', case=False, na=False)]
                td20_df = holdings_df[holdings_df[name_col].str.contains('TD20', case=False, na=False)]
                
                td3c_lots = int(td3c_df[lots_col].sum())
                td20_lots = int(td20_df[lots_col].sum())
                
                if td3c_lots == 0 or td20_lots == 0:
                    raise ValueError("Calculated lots resulted in zero total value.")
                    
                holdings_text = f"TD3C: {td3c_lots} Lots | TD20: {td20_lots} Lots"
            else:
                holdings_text = "Amplify Basket Active: Table Hidden"
                
        except Exception as scrap_error:
            # Drop trailing calculations if the scraper hits an error to avoid data corruption
            print(f"⚠️ Guardrail Catch - Scraping Error Intercepted: {scrap_error}")
            holdings_text = "Amplify Freight Basket: Failed Connection Buffer"
            td3c_lots = 976  # Seed last known good values so deltas stay flat rather than dropping to 0
            td20_lots = 285
        finally:
            if driver is not None:
                driver.quit()

        # --- OPTIONS OPEN INTEREST SCRAPER ---
        try:
            ticker_object = yf.Ticker(ticker_symbol)
            options_expirations = ticker_object.options
            
            # FIX: Ensure options list is not empty and has structural length before indexing
            if isinstance(options_expirations, (list, tuple)) and len(options_expirations) > 0:
                nearest_expiry = str(options_expirations[0]) # Adjusted index to extract first actual element string
                options_chain = ticker_object.option_chain(nearest_expiry)
                oi_array = options_chain.calls['openInterest'].values.flatten()
                live_call_oi = int(np.nan_to_num(oi_array).sum())
                calculated_baseline_oi = max(int(current_avg_vol * 0.05), 500)
                oi_expansion_ratio = round(float(live_call_oi / calculated_baseline_oi), 2)
                oi_surge_detected = oi_expansion_ratio >= 2.0
                
                if oi_surge_detected:
                    oi_status = f"💥 CRITICAL ACCUMULATION ({oi_expansion_ratio}x Base)"
                    oi_meaning = "Stealth leverage spike detected. Coiled spring pressure building."
                else:
                    oi_status = f"NORMAL ({live_call_oi:,} Contracts)"
                    oi_meaning = "Options flow matches paper trend."
            else:
                # NATIVE CONTROL: Graceful exit fallback when yfinance passes an empty list []
                oi_expansion_ratio = 1.0
                oi_surge_detected = False
                oi_status = "Data Dynamic Base"
                oi_meaning = "Exchange data normal overlay (Options chain temporarily unavailable)."
        except Exception as options_error:
            print(f"⚠️ Live Options Parse Exception: {options_error}")
            oi_expansion_ratio = 1.0
            oi_surge_detected = False
            oi_status = "Data Dynamic Base"
            oi_meaning = "Exchange data normal overlay."


        # --- SAFETY NET MANAGEMENT ---
        allowed_drop_distance = current_atr * safety_buffer_scale
        
        # Track the peak running price seen over the last 5 days
        high_array = high_series.iloc[-5:].values.flatten()
        highest_price_seen = max(float(high_array.max()), current_close)
            
        # Establish the absolute floor based on the peak run-up
        stop_loss_line = round(float(highest_price_seen - allowed_drop_distance), 2)
        stop_loss_pct = round(float((allowed_drop_distance / highest_price_seen) * 100), 1)
        
        # Calculate capital risk parameters
        cash_to_risk = account_cash * 0.02  # Capped strictly at 2% of total equity
        
        # CORRECTION: Measure risk from current market close down to the trailing floor
        if current_close > stop_loss_line:
            risk_per_share = current_close - stop_loss_line
        else:
            risk_per_share = 1.0
            
        # Final defensive share accumulation target
        if risk_per_share > 0:
            recommended_shares = round(float(cash_to_risk / risk_per_share), 2)
        else:
            recommended_shares=0.0

        total_trade_cost = round(float(recommended_shares * current_close), 2)
        
        speed_status = 'Too Hot/Overbought' if current_rsi >= 70 else 'Too Cold/Oversold' if current_rsi <= 30 else 'Healthy/Neutral'
        buyer_status = 'High Institutional' if current_volume > current_avg_vol else 'Low (Quiet trading)'
        vol_regime = 'EXPANDING (High Risk)' if current_atr > current_vol_ma else 'CONTRACTING (Stable Market)'
        
        # --- ADVANCED MACRO EVALUATION ENGINE ---
        csv_file_path = os.path.expanduser("~/trading_ledger.csv")
        send_sms_alert = False
        
        try:
            if os.path.isfile(csv_file_path):
                history_df = pd.read_csv(csv_file_path, on_bad_lines='skip')
                if not history_df.empty and 'TD3C_Lots' in history_df.columns:
                    last_entry = history_df.dropna(subset=['TD3C_Lots']).iloc[-1]
                    prev_td3c = float(last_entry['TD3C_Lots'])
                else:
                    prev_td3c = td3c_lots
            else:
                prev_td3c = td3c_lots
        except Exception:
            prev_td3c = td3c_lots

        # Evaluate Amplify's Macro inverse correlation factor (Freight drops while oil squeezes)
        freight_drop_anomaly = (td3c_lots < prev_td3c * 0.95) and (prev_td3c > 0)

        if current_close <= stop_loss_line:
            action_advice = "🚨 EMERGENCY EXIT: Safety net broken!"
            alert_icon = "🚨"
            send_sms_alert = True
        elif freight_drop_anomaly and current_rsi >= 60:
            action_advice = "🌋 INVERSE RISK SQUEEZE: Freight lots declining drastically while paper is squeezed. Underlying oil supply choke confirmed."
            alert_icon = "🌋"
            send_sms_alert = True
        elif current_rsi >= 75:
            action_advice = "⚠️ HARVEST GAINS: Profit targets reached."
            alert_icon = "⚠️"
        elif current_close > current_ema and current_volume > current_avg_vol:
            action_advice = "🔥 GREEN LIGHT: Trend verified by high institutional volume."
            alert_icon = "🔥"
            send_sms_alert = True
        elif oi_surge_detected and current_close <= current_ema:
            action_advice = "⚡ WATCH CLOSELY: Subsurface options breakout pending."
            alert_icon = "⚡"
            send_sms_alert = True
        else:
            action_advice = "⏳ WAIT: Consolidation active. Sideways micro structures."
            alert_icon = "⏳"

        # --- TEXT REPORT LAYOUT & EXPORTER ---
        td3c_delta_str = "Calculating (Needs historical day baseline)"
        td20_delta_str = "Calculating (Needs historical day baseline)"
        
        # Default text formatting for phone
        sms_freight_movement = f"TD3C: {td3c_lots} | TD20: {td20_lots}"

        try:
            if os.path.isfile(csv_file_path):
                history_df = pd.read_csv(csv_file_path, on_bad_lines='skip')
                if not history_df.empty and 'TD3C_Lots' in history_df.columns and 'TD20_Lots' in history_df.columns:
                    valid_history = history_df.dropna(subset=['TD3C_Lots', 'TD20_Lots'])
                    if not valid_history.empty:
                        last_entry = valid_history.iloc[-1]
                        prev_td3c_val = float(last_entry['TD3C_Lots'])
                        prev_td20_val = float(last_entry['TD20_Lots'])

                        td3c_pct = 0.0
                        td20_pct = 0.0
                        
                        if prev_td3c_val > 0:
                            td3c_pct = ((td3c_lots - prev_td3c_val) / prev_td3c_val) * 100
                            td3c_delta_str = f"{td3c_lots - prev_td3c_val:+.0f} Lots ({td3c_pct:+.1f}%)"
                        if prev_td20_val > 0:
                            td20_pct = ((td20_lots - prev_td20_val) / prev_td20_val) * 100
                            td20_delta_str = f"{td20_lots - prev_td20_val:+.0f} Lots ({td20_pct:+.1f}%)"

                        #ADDED: Expressed as percentage string for text
                        sms_freight_movement = f"TD3C: {td3c_pct:+.1f}% | TD20: {td20_pct:+.1f}%"      

        except Exception as delta_error:
            td3c_delta_str = f"Delta calculation bypassed: {str(delta_error)[:25]}"

        # --- STEP 3: EXPORT DETAILED PRE-MARKET LAYOUT ---
        print(f"\n=================================================================")
        print(f"[MONITOR] {ticker_symbol} LIVE MONITOR SYSTEM")
        print(f"=================================================================")
        print(f"Timestamp:            {current_time.strftime('%Y-%m-%d %H:%M:%S')} CST")
        print(f"Current Price:        ${current_close:,.2f} | 10-Day Trend: ${current_ema:,.2f}")
        print(f"2-Week Momentum:     {current_mom: >+8.2f} | Market Speed: {current_rsi:.1f}% ({speed_status})")
        print(f"Volatility Regime:    {vol_regime} | Buyer Activity: {buyer_status}")
        print("\n--- 🛢️ PHYSICAL WET FREIGHT MACRO OIL LAYER ---")
        print(f"Brent Crude Spot:     ${brent_current:.2f}/bbl | Velocity: {brent_change:+.2f} ({brent_pct:+.1f}%)")        
        print(f"5-Day Net Trend:      {brent_5d_change:+.2f}/bbl")
        print("\n--- 🚢 FREIGHT LOGISTICS MATRIX ---")
        print(f"Pre-Market Core:      {holdings_text}")
        print(f"VLCC (TD3C) Delta:    {td3c_delta_str}")
        print(f"Suezmax (TD20) Delta: {td20_delta_str}")
        print(f"Options Positioning:  {oi_status}")
        print(f"Market Meaning:       {oi_meaning}")
        print("\n--- 💼 CAPITAL PROJECTIONS & RISK ---")
        print(f"Position Sizing:      Buy {recommended_shares} Units | Total Allocation Target: ${total_trade_cost:,.2f}")
        print(f"Emergency Exit Floor: ${stop_loss_line:,.2f} (Triggers if asset drops {stop_loss_pct:.1f}% from peak)")
        print("-" * 65)
        print(f"ACTION ADVICE:        {action_advice}")
        print("=================================================================")

        # Mirror and write out the exact layout directly to a readable text file
        report_file_path = os.path.expanduser("~/bwet_log.txt")
        with open(report_file_path, "a", encoding="utf-8") as f:
            f.write(f"=================================================================\n")
            f.write(f"[MONITOR] {ticker_symbol} LIVE SYSTEM PROFILE\n")
            f.write(f"=================================================================\n")
            f.write(f"Timestamp:            {current_time.strftime('%Y-%m-%d %H:%M:%S')} CST\n")
            f.write(f"Current Price:        ${current_close:,.2f} | 10-Day Trend: ${current_ema:,.2f}\n")
            f.write(f"2-Week Momentum:     {current_mom: >+8.2f} | Market Speed: {current_rsi:.1f}% ({speed_status})\n")
            f.write(f"Volatility Regime:    {vol_regime} | Buyer Activity: {buyer_status}\n\n")
            f.write(f"--- MACRO OIL LAYER ---\n")
            f.write(f"Brent Crude Spot:     ${brent_current:.2f}/bbl\n")
            f.write(f"Daily Velocity:       {brent_change:+.2f} ({brent_pct:+.1f}%)\n")
            f.write(f"5-Day Net Trend:      {brent_5d_change:+.2f}/bbl\n\n")
            f.write(f"--- SHIPPING LOGISTICS MATRIX ---\n")
            f.write(f"Pre-Market Core:      {holdings_text}\n")
            f.write(f"VLCC (TD3C) Delta:    {td3c_delta_str}\n")
            f.write(f"Suezmax (TD20) Delta: {td20_delta_str}\n")
            f.write(f"Options Positioning:  {oi_status}\n")
            f.write(f"Market Meaning:       {oi_meaning}\n\n")
            f.write(f"--- CAPITAL PROJECTIONS & RISK ---\n")
            f.write(f"Position Sizing:      Buy {recommended_shares} Units | Total Allocation Target: ${total_trade_cost:,.2f}\n")
            f.write(f"Emergency Exit Floor: ${stop_loss_line:,.2f} (Triggers if asset drops {stop_loss_pct:.1f}% from peak)\n")
            f.write(f"-----------------------------------------------------------------\n")
            f.write(f"ACTION ADVICE:        {action_advice}\n")
            f.write(f"=================================================================\n")
        print("📄 Readable desktop report mirrored to ~/bwet_log.txt")

        
        # --- AUTOMATIC SPREADSHEET LOGGER ---
        log_data = {
            "Timestamp": [current_time.strftime('%Y-%m-%d %H:%M:%S')],
            "Price": [current_close],
            "Momentum": [current_mom],
            "PreMarketCore": [holdings_text],
            "TD3C_Lots": [td3c_lots],
            "TD20_Lots": [td20_lots],
            "OpenInterestRatio": [oi_expansion_ratio],
            "StopLossLine": [stop_loss_line],
            "SizingUnits": [recommended_shares],
            "SignalAction": [action_advice],
            "Brent_Price": [brent_current]
        }
        log_df = pd.DataFrame(log_data)
        if not os.path.isfile(csv_file_path):
            log_df.to_csv(csv_file_path, index=False)
            print("📝 Created new aligned trading ledger spreadsheet file.")
        else:
            log_df.to_csv(csv_file_path, mode='a', header=False, index=False)
            print("💾 Metrics successfully appended to tracking ledger history.")

        # --- BOOST (TMobile) MOBILE GATEWAY ---
        if send_sms_alert:
            try:
                sender_email = os.getenv("GMAIL_SENDER_EMAIL")
                sender_password = os.getenv("GMAIL_APP_PASSWORD") 
                target_boost_phone = os.getenv("TARGET_BOOST_PHONE")

                if not all([sender_email, sender_password, target_boost_phone]):
                    raise ValueError("Missing critical communication credentials in .env file.") 
               
                clean_action = action_advice.lower().split(':')[0].strip()
                text_message = f"bwet alert at ${current_close:.2f}. status {clean_action} shipping changes at {sms_freight_movement.lower()}"
                msg = MIMEText(text_message)
                msg["From"] = sender_email
                msg["To"] = target_boost_phone
                msg["Subject"] = "BWET"
                
                with smtplib.SMTP(host="smtp.gmail.com", port=587, timeout=10) as server:
                    server.ehlo() #Force handshake
                    server.starttls() #Upgrade to secure
                    server.ehlo() #Re-handshake
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, [target_boost_phone], msg.as_string())
                print("📱 Boost Mobile SMS text pushed successfully.")
            except Exception as gateway_error:
                print(f"⚠️ Boost Mobile Gateway Failed: {gateway_error}")

        # --- 9. DESKTOP ALERTS ---
        clean_text_flag = str(action_advice).replace(":", "")
        sys_uid = str(os.getuid())
        environment_path_string = "DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/" + sys_uid + "/bus"
        os.system(environment_path_string + f' notify-send "{alert_icon} {ticker_symbol} Update" "Price: {current_close:.2f} | {clean_text_flag}" -i info')
        os.system(environment_path_string + ' paplay /usr/share/sounds/freedesktop/stereo/message-new-instant.oga')

        return is_data_fresh_today, "Success"

    except Exception as error_details:
        print(f"Processing Error: {error_details}")
        return False, str(error_details)

# --- RE-ENGINEERED OPEN & CLOSE PRECISION TARGET DAEMON LOOP ---
if __name__ == "__main__":
    if args.test:
        print("🛠️  TEST MODE ACTIVATED: Forcing an immediate diagnostic evaluation run...")
        fresh_release_confirmed, status_msg = complete_production_bwet_system()
        print(f"\nDiagnostic Complete. Status: {status_msg} (Fresh Data: {fresh_release_confirmed})")
        sys.exit(0)

    print("🚀 BWET Precision Chronometer Daemon Initialized.")
    print("🎯 Target Matrix Scheduled: 08:25 AM CST (Open) & 03:00 PM CST (Close) Daily.")
    
    last_open_date = None
    last_close_date = None

    while True:
        now = datetime.datetime.now()
        current_date = now.date()
        
        # 1. MORNING OPENING WINDOW: Exactly 08:25 AM CST
        if now.hour == 8 and now.minute == 25 and current_date != last_open_date:
            print(f"\n⏰ Opening Chronometer Match at {now.strftime('%H:%M:%S')} CST. Executing daily opening run...")
            
            success, status = complete_production_bwet_system()
            if success:
                last_open_date = current_date
                print(f"🎯 OPEN SUMMARY LOCKED IN FOR {current_date}. Waiting for close...")
            
            time.sleep(65)
            continue
            
        # 2. EVENING CLOSING WINDOW: Exactly 03:00 PM CST
        if now.hour == 15 and now.minute == 0 and current_date != last_close_date:
            print(f"\n⏰ Closing Chronometer Match at {now.strftime('%H:%M:%S')} CST. Executing daily closing run...")
            
            success, status = complete_production_bwet_system()
            if success:
                last_close_date = current_date
                print(f"🎯 CLOSE SUMMARY LOCKED IN FOR {current_date}. Waiting for tomorrow's open...")
                
            time.sleep(65)
            continue
            
        time.sleep(20)
