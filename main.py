import logging
import os
from typing import List, Optional
from playwright.sync_api import sync_playwright, Page, TimeoutError
from dataclasses import dataclass, asdict
import pandas as pd
import argparse
import platform
import time
import pandas as pd
import re

@dataclass
class Place:
    name: str = ""
    address: str = ""
    website: str = ""
    phone_number: str = ""
    phone_clean: str = ""
    phone_type: str = "Unknown"
    is_valid_phone: bool = False
    instagram: str = ""
    reviews_count: Optional[int] = None
    reviews_average: Optional[float] = None
    store_shopping: str = "No"
    in_store_pickup: str = "No"
    store_delivery: str = "No"
    place_type: str = ""
    opens_at: str = ""
    introduction: str = ""

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )

def extract_text(page: Page, xpath: str) -> str:
    try:
        if page.locator(xpath).count() > 0:
            return page.locator(xpath).inner_text()
    except Exception as e:
        logging.warning(f"Failed to extract text for xpath {xpath}: {e}")
    return ""

def validate_lebanese_phone(phone_raw: str):
    """
    Validates and cleans a Lebanese phone number.
    Returns (cleaned_number, type, is_valid)
    """
    if not phone_raw:
        return "", "Missing", False
        
    # Remove non-digits
    digits = re.sub(r'\D', '', phone_raw)
    
    # Handle country code
    if digits.startswith('961'):
        digits = digits[3:]
    elif digits.startswith('00961'):
        digits = digits[5:]
        
    # Check length and prefixes
    # Landlines: 01, 04, 05, 06, 07, 08, 09 (followed by 6 digits) -> total 8 digits (with 0)
    # Mobiles: 03 (followed by 6 digits) -> total 8 digits (with 0)
    # Mobiles: 70, 71, 76, 78, 79, 81 (followed by 6 digits) -> total 8 digits
    # Sometimes 03 is written as 3xxxxxx (7 digits)
    
    # Standardize to local format (with leading 0) if possible
    
    # Case 1: 7 digits (e.g. 3xxxxxx or 1xxxxxx for Beirut landline without 0)
    if len(digits) == 7:
        if digits.startswith('3'):
            return '0' + digits, "Mobile", True
        elif digits.startswith(('1', '4', '5', '6', '7', '8', '9')): # Landline area codes
             # Note: 7 is usually 70/71 mobile, but 07 is south landline. 
             # 7xxxxxx is ambiguous without context, but usually 03 is the only 7-digit mobile widely used without 0.
             # Actually, 70/71 are 8 digits: 70xxxxxx.
             # So if it starts with 7 and is 7 digits, it might be 07 landline?
             return '0' + digits, "Landline", True
             
    # Case 2: 8 digits (Standard local format)
    if len(digits) == 8:
        prefix = digits[:2]
        if prefix in ['03', '70', '71', '76', '78', '79', '81']:
            return digits, "Mobile", True
        elif prefix in ['01', '04', '05', '06', '07', '08', '09']:
            return digits, "Landline", True
            
    return digits, "Unknown", False

def extract_place(page: Page) -> Place:
    # XPaths
    name_xpath = '//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]'
    address_xpath = '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]'
    website_xpath = '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]'
    phone_number_xpath = '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]'
    reviews_count_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span//span//span[@aria-label]'
    reviews_average_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span[@aria-hidden]'
    info1 = '//div[@class="LTs0Rc"][1]'
    info2 = '//div[@class="LTs0Rc"][2]'
    info3 = '//div[@class="LTs0Rc"][3]'
    opens_at_xpath = '//button[contains(@data-item-id, "oh")]//div[contains(@class, "fontBodyMedium")]'
    opens_at_xpath2 = '//div[@class="MkV9"]//span[@class="ZDu9vd"]//span[2]'
    place_type_xpath = '//div[@class="LBgpqf"]//button[@class="DkEaL "]'
    intro_xpath = '//div[@class="WeS02d fontBodyMedium"]//div[@class="PYvSYb "]'

    place = Place()
    place.name = extract_text(page, name_xpath)
    place.address = extract_text(page, address_xpath)
    
    # Extract website href
    try:
        if page.locator('//a[@data-item-id="authority"]').count() > 0:
            url = page.locator('//a[@data-item-id="authority"]').get_attribute('href') or ""
            if "instagram.com" in url:
                place.instagram = url
                place.website = "invalid"
            elif "facebook.com" in url:
                place.website = "invalid"
            else:
                place.website = url
        else:
            place.website = "invalid"
    except Exception as e:
        logging.warning(f"Failed to extract website href: {e}")
        place.website = extract_text(page, website_xpath) or "invalid"

    # Double check if fallback extraction got a social link
    if "instagram.com" in place.website:
        place.instagram = place.website
        place.website = "invalid"
    elif "facebook.com" in place.website:
        place.website = "invalid"

    place.phone_number = extract_text(page, phone_number_xpath)
    
    # Phone Validation
    clean, p_type, valid = validate_lebanese_phone(place.phone_number)
    place.phone_clean = clean
    place.phone_type = p_type
    place.is_valid_phone = valid
    
    place.place_type = extract_text(page, place_type_xpath)
    place.introduction = extract_text(page, intro_xpath) or "None Found"

    # Reviews Count
    reviews_count_raw = extract_text(page, reviews_count_xpath)
    if reviews_count_raw:
        try:
            temp = reviews_count_raw.replace('\xa0', '').replace('(','').replace(')','').replace(',','')
            place.reviews_count = int(temp)
        except Exception as e:
            logging.warning(f"Failed to parse reviews count: {e}")
    # Reviews Average
    reviews_avg_raw = extract_text(page, reviews_average_xpath)
    if reviews_avg_raw:
        try:
            temp = reviews_avg_raw.replace(' ','').replace(',','.')
            place.reviews_average = float(temp)
        except Exception as e:
            logging.warning(f"Failed to parse reviews average: {e}")
    # Store Info
    for idx, info_xpath in enumerate([info1, info2, info3]):
        info_raw = extract_text(page, info_xpath)
        if info_raw:
            temp = info_raw.split('·')
            if len(temp) > 1:
                check = temp[1].replace("\n", "").lower()
                if 'shop' in check:
                    place.store_shopping = "Yes"
                if 'pickup' in check:
                    place.in_store_pickup = "Yes"
                if 'delivery' in check:
                    place.store_delivery = "Yes"
    # Opens At
    opens_at_raw = extract_text(page, opens_at_xpath)
    if opens_at_raw:
        opens = opens_at_raw.split('⋅')
        if len(opens) > 1:
            place.opens_at = opens[1].replace("\u202f","")
        else:
            place.opens_at = opens_at_raw.replace("\u202f","")
    else:
        opens_at2_raw = extract_text(page, opens_at_xpath2)
        if opens_at2_raw:
            opens = opens_at2_raw.split('⋅')
            if len(opens) > 1:
                place.opens_at = opens[1].replace("\u202f","")
            else:
                place.opens_at = opens_at2_raw.replace("\u202f","")
    return place

def handle_consent(page: Page):
    try:
        # Common consent button selectors
        consent_selectors = [
            '//button[contains(@aria-label, "Accept all")]',
            '//button//span[contains(text(), "Accept all")]',
            '//button//div[contains(text(), "Accept all")]',
            '//button//span[contains(text(), "I agree")]',
            'form[action*="consent"] button'
        ]
        
        for selector in consent_selectors:
            if page.locator(selector).count() > 0 and page.locator(selector).first.is_visible():
                logging.info(f"Clicking consent button: {selector}")
                page.locator(selector).first.click()
                time.sleep(2)
                return
    except Exception as e:
        logging.warning(f"Consent handling failed: {e}")

def scrape_places(search_for: str, total: int, callback=None, required_area: str = None) -> dict:
    setup_logging()
    places: List[Place] = []
    seen_places = set()
    stats = {
        "total_found": 0,
        "filtered_count": 0,
        "places": []
    }
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            logging.warning(f"Could not launch browser directly: {e}")
            logging.info("Attempting to install Playwright browsers...")
            import subprocess
            subprocess.run(["python", "-m", "playwright", "install", "chromium"])
            browser = p.chromium.launch(headless=True)
            
        # Create a context with specific user agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            # Navigate directly to the search results
            import urllib.parse
            encoded_query = urllib.parse.quote(search_for)
            url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"
            
            logging.info(f"Navigating to {url}")
            page.goto(url, timeout=60000)
            page.wait_for_timeout(5000)
            
            handle_consent(page)

            # Wait for results to appear
            logging.info("Waiting for results...")
            try:
                page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]', timeout=30000)
            except TimeoutError:
                logging.warning("No results found or page took too long to load.")
                # Dump HTML for debugging
                with open("debug_no_results.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                return stats
            
            page.hover('//a[contains(@href, "https://www.google.com/maps/place")]')
            
            processed_count = 0
            while len(places) < total:
                # Scroll to load more if needed
                page.mouse.wheel(0, 10000)
                # Wait a bit for scroll to trigger load
                page.wait_for_timeout(2000)
                
                # Get current count of listings
                listings_locator = page.locator('//a[contains(@href, "https://www.google.com/maps/place")]')
                current_count = listings_locator.count()
                logging.info(f"Available listings: {current_count}, Processed: {processed_count}, Collected: {len(places)}")
                
                # If we've processed everything available so far
                if processed_count >= current_count:
                    logging.info("Reached end of current list. Waiting for more...")
                    # Try to scroll again harder/wait longer
                    page.mouse.wheel(0, 10000)
                    page.wait_for_timeout(3000)
                    
                    new_count = listings_locator.count()
                    if new_count <= current_count:
                        logging.info("No new results loaded. Stopping.")
                        break
                    current_count = new_count

                # Process new listings
                # We can't loop from processed_count to current_count directly with `all()` because `all()` fetches everything.
                # Instead, we use `nth(i)` to access specific elements without refetching the whole list as a Python list yet,
                # OR we fetch all and slice. Fetching all is safer for references.
                
                # Re-fetch all to get fresh handles
                all_listings = listings_locator.all()
                
                # Only iterate over what we haven't processed
                # Note: If the list grew, indices 0..processed_count-1 should be the same items (Google Maps appends).
                for i in range(processed_count, len(all_listings)):
                    if len(places) >= total:
                        break
                        
                    processed_count += 1
                    
                    try:
                        listing = all_listings[i].locator("xpath=..")
                        
                        # Scroll into view to make sure it's clickable
                        listing.scroll_into_view_if_needed()
                        
                        listing.click()
                        # Wait for details to load
                        try:
                            page.wait_for_selector('//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]', timeout=5000)
                        except TimeoutError:
                            logging.warning(f"Timeout waiting for details of listing {i+1}")
                            continue

                        time.sleep(1.0) 
                        place = extract_place(page)
                        
                        # Deduplication
                        unique_id = (place.name, place.address)
                        if unique_id in seen_places:
                            logging.info(f"Skipping duplicate: {place.name}")
                            if callback:
                                callback(len(places), total, f"Skipping duplicate: {place.name}")
                            continue
                        seen_places.add(unique_id)
                        
                        # Update stats
                        stats["total_found"] = processed_count # Track how many we checked

                        # Strict Area Filtering
                        if required_area:
                            if required_area.lower() not in place.address.lower():
                                logging.info(f"Skipping {place.name}: Address '{place.address}' does not contain '{required_area}'")
                                stats["filtered_count"] += 1
                                if callback:
                                     callback(len(places), total, f"Checking {processed_count}... (Filtered: {place.name})")
                                continue

                        if place.name:
                            places.append(place)
                            logging.info(f"Added {place.name}. Total collected: {len(places)}")
                            if callback:
                                callback(len(places), total, f"Found: {place.name}")
                        else:
                            logging.warning(f"No name found for listing {i+1}, skipping.")
                            
                    except Exception as e:
                        logging.warning(f"Failed to extract listing {i+1}: {e}")
                        
                # End of inner loop (processed up to current_count or collected enough)
                if len(places) >= total:
                    break

        except Exception as e:
            logging.error(f"An error occurred: {e}")
            page.screenshot(path="error_screenshot.png")
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise e
        finally:
            browser.close()
            
    stats["places"] = places
    return stats

def save_places_to_csv(places: List[Place], output_path: str = "result.csv", append: bool = False):
    df = pd.DataFrame([asdict(place) for place in places])
    if not df.empty:
        # Check if we should drop columns with all same values (optional, but in original script)
        # for column in df.columns:
        #     if df[column].nunique() == 1:
        #         df.drop(column, axis=1, inplace=True)
        
        file_exists = os.path.isfile(output_path)
        mode = "a" if append else "w"
        header = not (append and file_exists)
        df.to_csv(output_path, index=False, mode=mode, header=header, encoding="utf-8-sig")
        logging.info(f"Saved {len(df)} places to {output_path} (append={append})")
    else:
        logging.warning("No data to save. DataFrame is empty.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--search", type=str, help="Search query for Google Maps")
    parser.add_argument("-t", "--total", type=int, help="Total number of results to scrape")
    parser.add_argument("-o", "--output", type=str, default="result.csv", help="Output CSV file path")
    parser.add_argument("--append", action="store_true", help="Append results to the output file instead of overwriting")
    args = parser.parse_args()
    
    search_for = args.search or "real estate companies in Beirut"
    total = args.total or 5
    output_path = args.output
    append = args.append
    
    places = scrape_places(search_for, total)["places"]
    save_places_to_csv(places, output_path, append=append)

if __name__ == "__main__":
    main()
