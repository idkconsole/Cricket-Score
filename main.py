from bs4 import BeautifulSoup
import time
import requests
import yaml
import re
from concurrent.futures import ThreadPoolExecutor
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_config():
    try:
        with open('d.yaml', 'r') as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        logger.warning("Config file not found")
        return {"discord": {"enabled": False, "token": "", "channel_ids": []}}

def send_to_discord(message, token, channel_ids):
    if not token or not channel_ids:
        logger.warning("Discord integration not configured. Skipping Discord message.")
        return False
    if isinstance(channel_ids, str):
        channel_ids = [channel_ids]
    headers = {
        "Authorization": f"{token}",
        "Content-Type": "application/json"
    }
    payload = {
        "content": message
    }
    success = False
    for channel_id in channel_ids:
        try:
            response = requests.post(
                f"https://discord.com/api/v10/channels/{channel_id}/messages", 
                headers=headers, 
                json=payload
            )
            if response.status_code in [200, 201]:
                logger.info(f"Successfully sent message to Discord channel {channel_id}")
                success = True
            else:
                logger.error(f"Failed to send message to Discord channel {channel_id}. Status code: {response.status_code}")
                logger.error(f"Response: {response.text}")
        except Exception as e:
            logger.error(f"Error sending message to Discord channel {channel_id}: {str(e)}")
    return success

def extract_result(commentary_text):
    text = commentary_text.lower()
    if "wicket" in text or "out" in text:
        return "wicket"
    elif "no run" in text:
        return "dot"
    elif "1 run" in text:
        return "1 run"
    elif "2 run" in text:
        return "2 runs"
    elif "3 run" in text:
        return "3 runs"
    elif "four" in text or "4 runs" in text:
        return "4"
    elif "six" in text or "6 runs" in text:
        return "6"
    elif "wide" in text:
        return "wide"
    elif "no ball" in text:
        return "no ball"
    elif "bye" in text:
        return "bye"
    elif "leg bye" in text:
        return "leg bye"
    else:
        return "event"

def over_to_float(over_num):
    try:
        return float(over_num)
    except (ValueError, TypeError):
        return -1

def fetch_page(url, headers=None):
    max_retries = 3
    retry_delay = 2
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed (attempt {attempt+1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2 
            else:
                logger.error(f"Failed to fetch page after {max_retries} attempts")
                return None

def main():
    config = load_config()
    discord_enabled = config.get("discord", {}).get("enabled", False)
    discord_token = config.get("discord", {}).get("token", "")
    discord_channel_ids = config.get("discord", {}).get("channel_ids", [])
    url = "https://www.cricbuzz.com/live-cricket-scores/112469/nz-vs-ind-final-icc-champions-trophy-2025"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0'
    }
    seen_commentaries = set()
    highest_over_seen = -1
    last_sent_over = None
    last_fetch_time = 0
    min_fetch_interval = 3 
    try:
        while True:
            current_time = time.time()
            time_since_last_fetch = current_time - last_fetch_time
            if time_since_last_fetch < min_fetch_interval:
                time.sleep(min_fetch_interval - time_since_last_fetch)
            last_fetch_time = time.time()
            logger.info("Fetching page content...")
            html_content = fetch_page(url, headers)
            if not html_content:
                logger.error("Failed to fetch page content. Retrying in 5 seconds...")
                time.sleep(5)
                continue
            soup = BeautifulSoup(html_content, "html.parser")
            current_score = "Score not found"
            score_pattern = r'NZ\s+\d+/\d+\s+\(\d+\.?\d*\)'
            score_matches = re.findall(score_pattern, html_content)
            if score_matches:
                current_score = score_matches[0].strip()
            if current_score == "Score not found":
                score_elements = soup.select("h2.cb-font-20.text-bold.inline-block.ng-binding")
                for element in score_elements:
                    text = element.get_text(strip=True)
                    if "NZ" in text and "/" in text and "(" in text:
                        current_score = text
                        break
            if current_score == "Score not found":
                min_bat_divs = soup.select("div.cb-min-bat-rw")
                for div in min_bat_divs:
                    h2_element = div.find("h2")
                    if h2_element:
                        text = h2_element.get_text(strip=True)
                        if "NZ" in text:
                            current_score = text
                            break
            if current_score == "Score not found":
                all_text = soup.get_text()
                score_matches = re.findall(r'NZ\s+\d+/\d+\s+\(\d+\.?\d*\)', all_text)
                if score_matches:
                    current_score = score_matches[0].strip()
            commentary_sections = soup.find_all("div", class_="cb-col cb-col-100")
            new_commentaries = []
            new_commentary_found = False
            for section in commentary_sections:
                over_divs = section.find_all("div", class_="cb-col cb-col-8 text-bold")
                commentary_divs = section.find_all("p", class_="cb-com-ln")
                if over_divs and commentary_divs:
                    for over_div, comm_div in zip(over_divs, commentary_divs):
                        over_element = over_div.find("div", class_="cb-mat-mnu-wrp cb-ovr-num")
                        if not over_element:
                            continue
                        over_num = over_element.get_text(strip=True)
                        commentary_text = comm_div.get_text(strip=True)
                        commentary_id = f"{over_num} - {commentary_text[:50]}"
                        if commentary_id in seen_commentaries:
                            continue
                        result = extract_result(commentary_text)
                        if result == "event" or over_num == "N/A":
                            continue
                        over_float = over_to_float(over_num)
                        if over_float > highest_over_seen:
                            highest_over_seen = over_float
                        if over_float < highest_over_seen:
                            continue
                        new_commentaries.append({
                            "over": over_num,
                            "commentary": commentary_text,
                            "result": result,
                            "score": current_score
                        })
                        seen_commentaries.add(commentary_id)
                        new_commentary_found = True
            if new_commentary_found and new_commentaries:
                latest_commentary = max(new_commentaries, key=lambda x: over_to_float(x["over"]))
                current_over = latest_commentary["over"]
                logger.info(f"Over: {latest_commentary['over']} - {latest_commentary['commentary']}")
                logger.info(f"Score: {latest_commentary['score']}")
                logger.info("-" * 50)
                if last_sent_over != current_over:
                    if discord_enabled:
                        discord_message = f"Over: {latest_commentary['over']} | Result: {latest_commentary['result']} | Score: {latest_commentary['score']}"
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            executor.submit(send_to_discord, discord_message, discord_token, discord_channel_ids)
                    last_sent_over = current_over
            if not new_commentary_found:
                logger.info("No new commentary found. Waiting for updates...")
            if len(seen_commentaries) > 1000:
                seen_commentaries = set(list(seen_commentaries)[-500:])
    except KeyboardInterrupt:
        logger.info("Stopping the scraper...")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
    finally:
        logger.info("Scraper stopped")

if __name__ == "__main__":
    main()
