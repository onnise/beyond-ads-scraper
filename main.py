import logging
import os
import re
import urllib.parse
import platform
import time
import argparse
import random
import sys
import subprocess
from typing import List, Optional
from dataclasses import dataclass, asdict
from playwright.sync_api import sync_playwright, Page, TimeoutError, BrowserContext
import pandas as pd

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
    place_type: str = ""
    opens_at: str = ""

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

def clean_business_name(name: str) -> str:
    """
    Cleans business name by removing tagline or description after common delimiters.
    Example: "PBM : Real Estate in Lebanon" -> "PBM"
    """
    if not name:
        return ""
    
    # Common delimiters used to separate name from description
    delimiters = [':', '|', '–', ' - ', '•', ',', '.'] 
    
    cleaned_name = name
    
    for char in delimiters:
        if char in name:
            parts = name.split(char)
            candidate = parts[0].strip()
            # Heuristic: If the first part is substantial (e.g. > 2 chars), use it.
            if len(candidate) > 1:
                cleaned_name = candidate
                break
    
    # Remove common corporate suffixes to improve search relevance
    cleaned_name = re.sub(r'\s+(sarl|sal|inc|co|company|ltd|llc)\b.*', '', cleaned_name, flags=re.IGNORECASE).strip()

    # Extra cleanup: specific words that might indicate a tagline if no delimiter
    # e.g. "Matar Law Firm - Lawyers in Beirut" -> handled by delimiter
    # "AtaBuild Lebanon Luxury Real Estate" -> "AtaBuild"
    # Heuristic: If name is very long (> 5 words), take the first 2-3 words if they look like a name?
    # But be careful with "Law Firm of X and Y"
    
    words = cleaned_name.split()
    if len(words) > 6:
        # Take first 4 words as a guess for a long tagline-like name
        cleaned_name = " ".join(words[:4])
        
    return cleaned_name

def verify_instagram_match(business_name: str, url: str) -> bool:
    """
    Verifies if the Instagram URL is likely to belong to the business.
    """
    if not url or "instagram.com" not in url:
        return False
        
    # Extract username
    match = re.search(r"instagram\.com/([^/?#]+)", url)
    if not match:
        return False
    
    username = match.group(1).lower()
    
    # Normalize business name
    # Replace special chars with SPACE to preserve word boundaries (e.g. "All-ways" -> "All ways")
    name_clean = re.sub(r"[^a-zA-Z0-9\s]", " ", business_name.lower())
    tokens = name_clean.split()
    
    # Filter out weak tokens that might generate false positives
    weak_tokens = {
        "lebanon", "lb", "beirut", "company", "co", "ltd", "sarl", "sal", 
        "agency", "travel", "tourism", "real", "estate", "group", "holding",
        "shop", "store", "restaurant", "hotel", "cafe", "lounge", "bar",
        "services", "trading", "contracting", "engineering", "design", "media",
        "pharma", "pharmacy", "clinic", "dr", "center", "centre", "market",
        "supermarket", "gym", "spa", "beauty", "salon", "lounge", "boutique",
        "fashion", "style", "home", "house", "decor", "interiors", "furniture",
        "kitchen", "bakery", "pastry", "sweets", "roastery", "jewellery", "jewelry",
        "exchange", "transfer", "money", "bank", "insurance", "law", "legal",
        "firm", "associates", "consultancy", "consulting", "schools", "school",
        "university", "college", "academy", "institute", "education", "learning",
        "nursery", "kids", "child", "care", "health", "medical", "dental",
        "dentist", "doctor", "physio", "optical", "optics", "vision", "eye",
        "hospital", "laboratory", "lab", "imaging", "scan", "xray", "auto",
        "car", "cars", "rental", "rent", "drive", "motors", "motor", "cycle",
        "bike", "mechanic", "garage", "fix", "repair", "tech", "technology",
        "solutions", "systems", "soft", "software", "app", "mobile", "phone",
        "cell", "tel", "telecom", "net", "network", "online", "web", "digital",
        "marketing", "social", "events", "planning", "wedding", "party",
        "catering", "food", "drink", "beverage", "snack", "grill", "burger",
        "pizza", "sushi", "pasta", "seafood", "fish", "meat", "chicken",
        "taouk", "shawarma", "falafel", "manakish", "lebanese", "cuisine",
        "international", "diner", "bistro", "pub", "club", "resort", "beach",
        "pool", "view", "terrace", "garden", "park", "plaza", "mall", "city",
        "town", "village", "street", "road", "highway", "main", "branch",
        "holidays", "holiday", "tour", "tours", "trip", "trips", "booking",
        "reservation", "ticket", "tickets", "visa", "visas", "cargo", "freight",
        "the", "and", "for", "of", "in", "at", "by", "to"
    }
    
    strong_tokens = [t for t in tokens if t not in weak_tokens and len(t) > 2]
    
    # If no strong tokens (e.g. "The Travel Agency"), fall back to checking all tokens but require stricter match
    if not strong_tokens:
        # Fallback: if business name is short but specific (e.g. "ABC Travel")
        # and we stripped "Travel", we might be left with "ABC".
        # If the original token was short but not weak, maybe keep it?
        strong_tokens = [t for t in tokens if t not in weak_tokens]
        
    if not strong_tokens:
        return False # Name is too generic
        
    # Check if ANY strong token is present in the username
    # Normalize username to remove dots/underscores for easier matching
    # e.g. "all.ways.travel" -> "allwaystravel"
    username_clean = re.sub(r"[^a-zA-Z0-9]", "", username)
    
    # Improved Check:
    # 1. Exact match of a strong token
    # 2. Sequential match of tokens (e.g. "All-ways" -> "all" + "ways" in sequence)
    
    # Concatenate strong tokens to check for full name match
    strong_concat = "".join(strong_tokens)
    if strong_concat in username_clean:
        return True
        
    # Check individual strong tokens
    for token in strong_tokens:
        if token in username_clean:
            # If the token is very short (3 chars), ensure it's not part of a common suffix?
            # But for now, trust the strong list.
            return True
            
    return False

def search_web_for_instagram(context: BrowserContext, name: str, address: str, should_stop_callback=None) -> str:
    """
    Robust fallback search using Yahoo and Brave.
    Bing and DuckDuckGo are currently blocking requests.
    """
    if should_stop_callback and should_stop_callback():
        return ""

    page = context.new_page()
    found_link = ""
    
    try:
        clean_name = clean_business_name(name)
        
        # Priority 1: Yahoo Search - Generally less strict
        # Priority 2: Brave Search - Good alternative
        # Priority 3: Bing - Backup (High block rate)
        
        queries = [
            (f"{clean_name} {address} instagram", "yahoo"),
            (f"{clean_name} Lebanon instagram", "yahoo"),
            (f"{clean_name} instagram", "brave"),
            (f"{clean_name} instagram", "bing")
        ]
        
        # Deduplicate based on query string
        unique_queries = []
        seen = set()
        for q, engine in queries:
            if q not in seen:
                unique_queries.append((q, engine))
                seen.add(q)
        
        for query, engine in unique_queries:
            if should_stop_callback and should_stop_callback():
                logging.info("Stopping fallback search due to user interrupt.")
                break

            # Add random delay to look human
            sleep_time = random.uniform(2.0, 5.0)
            # logging.info(f"Sleeping {sleep_time:.2f}s before {engine} search...")
            time.sleep(sleep_time)

            logging.info(f"Fallback Search ({engine}): {query}")
            
            try:
                encoded_query = urllib.parse.quote(query)
                search_url = ""
                
                if engine == "bing":
                    search_url = f"https://www.bing.com/search?q={encoded_query}"
                elif engine == "yahoo":
                    search_url = f"https://search.yahoo.com/search?p={encoded_query}"
                elif engine == "brave":
                    search_url = f"https://search.brave.com/search?q={encoded_query}"
                
                page.goto(search_url, timeout=15000)
                page.wait_for_timeout(2000)

                # Yahoo Consent
                if engine == "yahoo":
                    try:
                        if page.locator('button[name="agree"]').is_visible():
                             page.locator('button[name="agree"]').click()
                             page.wait_for_timeout(1000)
                    except: pass
                
                # Bing Consent
                if engine == "bing":
                    try:
                        if page.locator('#bnp_btn_accept').is_visible():
                            page.locator('#bnp_btn_accept').click()
                            page.wait_for_timeout(1000)
                    except: pass

                # Direct Search for Instagram links
                # Wait briefly for results to populate
                try:
                    page.wait_for_selector('a[href*="instagram.com"]', timeout=3000)
                except:
                    pass 
                
                links = page.locator('a[href*="instagram.com"]').all()
                
                for link in links:
                    if not link.is_visible():
                        continue
                    
                    href = link.get_attribute('href')
                    if not href:
                        continue
                    
                    if "instagram.com" in href:
                         # Filter noise
                         if any(x in href for x in ["google.com", "bing.com", "microsoft.com", "duckduckgo.com", "yahoo.com", "search.yahoo", "brave.com", "/search", "/url?", "y.gif"]):
                             continue
                             
                         # Validate profile
                         if "/p/" not in href and "/reel/" not in href and "/explore/" not in href and "/tags/" not in href:
                             # Ensure it's not just the root domain
                             if href.strip('/').endswith("instagram.com"):
                                 continue
                                 
                             # Verify match
                             if not verify_instagram_match(name, href):
                                 logging.info(f"Rejected mismatching Instagram: {href} for {name}")
                                 continue

                             found_link = href
                             logging.info(f"Found Instagram via {engine}: {found_link}")
                             return found_link
            
            except Exception as e:
                logging.warning(f"{engine} search error for '{query}': {e}")
            
    except Exception as e:
        logging.warning(f"Search failed for {name}: {e}")
    finally:
        page.close()
    
    return found_link

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

def extract_place(page: Page, context: BrowserContext = None, should_stop_callback=None) -> Place:
    # XPaths
    name_xpath = '//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]'
    address_xpath = '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]'
    website_xpath = '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]'
    phone_number_xpath = '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]'
    reviews_count_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span//span//span[@aria-label]'
    reviews_average_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span[@aria-hidden]'
    opens_at_xpath = '//button[contains(@data-item-id, "oh")]//div[contains(@class, "fontBodyMedium")]'
    opens_at_xpath2 = '//div[@class="MkV9"]//span[@class="ZDu9vd"]//span[2]'
    place_type_xpath = '//div[@class="LBgpqf"]//button[@class="DkEaL "]'

    place = Place()
    place.name = extract_text(page, name_xpath)
    
    if should_stop_callback and should_stop_callback():
        return place
        
    place.address = extract_text(page, address_xpath)
    
    # Extract website href
    try:
        if page.locator('//a[@data-item-id="authority"]').count() > 0:
            url = page.locator('//a[@data-item-id="authority"]').get_attribute('href') or ""
            if "instagram.com" in url:
                if verify_instagram_match(place.name, url):
                    place.instagram = url
                    place.website = "invalid"
                else:
                    place.website = "invalid"
                    logging.info(f"Rejected website mismatch: {url} for {place.name}")
            elif "facebook.com" in url:
                place.website = "invalid"
            else:
                place.website = url
        else:
            place.website = "invalid"
    except Exception as e:
        logging.warning(f"Failed to extract website href: {e}")
        place.website = extract_text(page, website_xpath) or "invalid"

    if should_stop_callback and should_stop_callback():
        return place

    # Scroll the details panel to ensure lazy-loaded elements (like Social Profiles) are rendered
    try:
        # Try to focus on the main panel
        # The panel usually has role="main" and contains the place name
        main_panel = page.locator('div[role="main"]').first
        if main_panel.count() > 0:
            main_panel.hover()
            # Scroll down significantly
            page.mouse.wheel(0, 3000)
            time.sleep(1.0)
            page.mouse.wheel(0, 3000)
            time.sleep(1.0)
        else:
             # Fallback to keyboard
            header_el = page.locator(name_xpath).first
            if header_el.count() > 0:
                header_el.click() # Focus
                for _ in range(10): # Increased scroll amount
                    page.keyboard.press("PageDown")
                    time.sleep(0.1)
    except Exception as e:
        logging.warning(f"Failed to scroll details panel: {e}")

    # Deep Scan for Instagram in the details panel (Social Profiles, Descriptions, etc.)
    # We look for any link containing instagram.com that is visible
    try:
        # Use the main panel as scope to avoid picking up links from the results list (sidebar)
        main_panel = page.locator('div[role="main"]').first
        if main_panel.count() > 0:
            scope = main_panel
        else:
            scope = page # Fallback, though risky
            
        # Strategy 1: Look for aria-labels (common in Google Maps for social icons)
        social_aria = scope.locator('a[aria-label*="Instagram"], button[aria-label*="Instagram"]').all()
        for el in social_aria:
            href = el.get_attribute('href')
            if href and "instagram.com" in href:
                if verify_instagram_match(place.name, href):
                    place.instagram = href
                    logging.info(f"Found Instagram via Aria Label: {href}")
                    break
                else:
                    logging.info(f"Rejected Aria Label mismatch: {href} for {place.name}")
        
        if not place.instagram:
            # Strategy 2: Scan all links within the scope
            # Use CSS selector 'a' to ensure we only find descendants of the scope
            social_links = scope.locator('a').all()
            for link in social_links:
                if not link.is_visible():
                    continue
                href = link.get_attribute('href')
                if href and "instagram.com" in href:
                    if "google.com" not in href:
                         if verify_instagram_match(place.name, href):
                             place.instagram = href
                             logging.info(f"Found Instagram via Deep Scan: {href}")
                             break
                         else:
                             logging.info(f"Rejected Deep Scan mismatch: {href} for {place.name}") 
    except Exception as e:
        logging.warning(f"Deep scan for Instagram failed: {e}")

    # Double check if fallback extraction got a social link
    if "instagram.com" in place.website:
        if verify_instagram_match(place.name, place.website):
            place.instagram = place.website
            place.website = "invalid"
        else:
            place.website = "invalid"
    elif "facebook.com" in place.website:
        place.website = "invalid"

    if should_stop_callback and should_stop_callback():
        return place

    # Fallback: Google Search if Instagram is still missing and context is provided
    if not place.instagram and context and place.name:
        # Only search if we have a name
        place.instagram = search_web_for_instagram(context, place.name, place.address, should_stop_callback)

    place.phone_number = extract_text(page, phone_number_xpath)
    
    # Phone Validation
    clean, p_type, valid = validate_lebanese_phone(place.phone_number)
    place.phone_clean = clean
    place.phone_type = p_type
    place.is_valid_phone = valid
    
    place.place_type = extract_text(page, place_type_xpath)

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

class GoogleMapsScraper:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.places = []
        self.processed_count = 0
        self.stats = {"total_found": 0, "filtered_count": 0, "places": []}
        self.is_running = False
        self.search_for = ""
        self.total_target = 0
        self.required_area = None
        self.allowed_areas = []
        self.excluded_areas = []
        
    def start(self, search_for: str, total: int, required_area: str = None, excluded_areas: List[str] = None, allowed_areas: List[str] = None):
        setup_logging()
        self.search_for = search_for
        self.total_target = total
        self.required_area = required_area
        self.allowed_areas = allowed_areas or []
        self.excluded_areas = excluded_areas or []
        self.places = []
        self.processed_count = 0
        self.stats = {"total_found": 0, "filtered_count": 0, "places": []}
        
        self.playwright = sync_playwright().start()
        
        try:
            self.browser = self.playwright.chromium.launch(headless=True)
        except Exception:
            # Fallback for installation issues
            import subprocess
            import sys
            logging.info("Browser launch failed. Attempting to install Playwright Chromium...")
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                self.browser = self.playwright.chromium.launch(headless=True)
            except Exception as e:
                logging.error(f"Failed to install/launch browser: {e}")
                raise e
            
        self.context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = self.context.new_page()
        
        # Navigate
        import urllib.parse
        encoded_query = urllib.parse.quote(search_for)
        url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"
        
        logging.info(f"Navigating to {url}")
        self.page.goto(url, timeout=60000)
        self.page.wait_for_timeout(5000)
        
        handle_consent(self.page)
        
        # Initial wait for results
        try:
            self.page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]', timeout=30000)
        except TimeoutError:
            logging.warning("No results found.")
            return False
            
        self.page.hover('//a[contains(@href, "https://www.google.com/maps/place")]')
        self.is_running = True
        return True

    def stop(self):
        """
        Stops the scraper and closes the browser.
        """
        self.is_running = False
        if self.context:
            try:
                self.context.close()
            except:
                pass
        if self.browser:
            try:
                self.browser.close()
            except:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except:
                pass
        logging.info("Scraper stopped.")

    def step(self, should_stop_callback=None) -> Optional[Place]:
        """
        Performs one step of scraping:
        - Checks if we need to scroll
        - Processes the next available listing
        - Returns the Place object if found, or None if just scrolling/waiting
        """
        if not self.is_running or len(self.places) >= self.total_target:
            return None
        
        if should_stop_callback and should_stop_callback():
             logging.info("Step interrupted by user stop request.")
             return None

        # Get current listings
        listings_locator = self.page.locator('//a[contains(@href, "https://www.google.com/maps/place")]')
        current_count = listings_locator.count()
        
        # If we need more listings and have processed all current ones
        if self.processed_count >= current_count:
            logging.info("Scrolling for more results...")
            self.page.mouse.wheel(0, 10000)
            self.page.wait_for_timeout(3000)
            
            # Check if count increased
            new_count = listings_locator.count()
            if new_count <= current_count:
                # End of list or load failed
                logging.info("No new results after scroll.")
                # We return None to indicate no place found this step, 
                # but we might want to try scrolling again or stop.
                # For now, let's try one more wait or just return None.
                return None
            return None # Just scrolled, return to let loop continue

        # Process the next listing
        try:
            listing = listings_locator.nth(self.processed_count)
            listing.click()
            self.page.wait_for_timeout(2000)
            
            if should_stop_callback and should_stop_callback():
                logging.info("Step interrupted by user stop request during processing.")
                return None
            
            place = extract_place(self.page, self.context, should_stop_callback)
            self.processed_count += 1
            
            # Filter Logic
            self.stats["total_found"] += 1
            
            # 1. Area Filter
            if self.allowed_areas:
                # If we have a specific list of allowed sub-areas (including the main area)
                # Check if ANY of them are in the address
                matched_area = False
                for area in self.allowed_areas:
                    if area.lower() in place.address.lower():
                        matched_area = True
                        break
                
                if not matched_area:
                    self.stats["filtered_count"] += 1
                    logging.info(f"Skipped {place.name}: Address '{place.address}' not in allowed areas {self.allowed_areas}")
                    return None
            
            elif self.required_area:
                # Legacy single area check
                if self.required_area.lower() not in place.address.lower():
                    self.stats["filtered_count"] += 1
                    logging.info(f"Skipped {place.name}: Address '{place.address}' missing '{self.required_area}'")
                    return None # Filtered out
            
            # 2. Excluded Areas Filter
            if self.excluded_areas:
                for excluded in self.excluded_areas:
                    if excluded.lower() in place.address.lower():
                        self.stats["filtered_count"] += 1
                        logging.info(f"Skipped {place.name}: Address '{place.address}' contains excluded '{excluded}'")
                        return None # Filtered out
            
            # Valid Place
            self.places.append(place)
            self.stats["places"].append(place)
            return place
            
        except Exception as e:
            logging.error(f"Error processing listing {self.processed_count}: {e}")
            self.processed_count += 1
            return None

    def stop(self):
        self.is_running = False
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

# Keep the original function for backward compatibility if needed, 
# or redirect it to use the class (simplified).
def scrape_places(search_for: str, total: int, callback=None, required_area: str = None, excluded_areas: List[str] = None) -> dict:
    scraper = GoogleMapsScraper()
    success = scraper.start(search_for, total, required_area, excluded_areas)
    if not success:
        scraper.stop()
        return scraper.stats
        
    while len(scraper.places) < total:
        place = scraper.step()
        if place:
            if callback:
                callback(len(scraper.places), total, f"Found {place.name}")
        
        # Check if we are stuck (processed all but no new places) - simplistic check
        listings_count = scraper.page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').count()
        if scraper.processed_count >= listings_count:
             # Try scroll
             scraper.page.mouse.wheel(0, 10000)
             scraper.page.wait_for_timeout(2000)
             if scraper.page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').count() <= listings_count:
                 break

    scraper.stop()
    return scraper.stats



def save_places_to_csv(places: List[Place], output_path: str = "result.csv", append: bool = False):
    df = pd.DataFrame([asdict(place) for place in places])
    if not df.empty:
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
