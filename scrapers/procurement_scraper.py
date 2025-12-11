"""
PPP MOF Platform Scraper - Cloud optimized version
Scrapes promotion participation platform data.
"""

import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager


class ProcurementScraper:
    """PPP MOF platform scraper for cloud execution."""
    
    BASE_URL = "https://ppp.mof.gov.tw/WWW/"
    ANNOUNCE_URL = f"{BASE_URL}ann_search4.aspx"
    REGISTERED_URL = f"{BASE_URL}case_search4.aspx"
    
    def __init__(self, headless: bool = True, wait_seconds: int = 15):
        self.headless = headless
        self.wait_seconds = wait_seconds
        self.driver = None
        self.wait = None
        self.current_list_url = None
        
    def setup_driver(self):
        """Initialize Chrome WebDriver with cloud-optimized settings."""
        print("Initializing Chrome WebDriver...")
        
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-infobars')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, self.wait_seconds)
        
        print("✓ Chrome WebDriver initialized")
        
    def close_driver(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
            print("✓ Browser closed")
    
    def find_data_table(self):
        """Find the data table on the page."""
        try:
            try:
                container = self.driver.find_element(By.ID, "ContentPlaceHolder1_ListView1")
                table = container.find_element(By.CSS_SELECTOR, "table.table-rwd")
                headers = table.find_elements(By.TAG_NAME, "th")
                header_texts = [h.text.strip() for h in headers]
                if any(keyword in "".join(header_texts) for keyword in ["案件名稱", "公告機關", "案件編號"]):
                    return table
            except:
                pass
            
            tables = self.driver.find_elements(By.TAG_NAME, 'table')
            for table in tables:
                table_class = table.get_attribute('class')
                if 'table-rwd' in str(table_class):
                    try:
                        headers = table.find_elements(By.TAG_NAME, "th")
                        header_texts = [h.text.strip() for h in headers]
                        if any(keyword in "".join(header_texts) for keyword in ["案件名稱", "公告機關", "案件編號"]):
                            return table
                    except:
                        continue
        except:
            pass
        return None

    def scrape_list_page(self, url: str, page_type: str, max_pages: int = 50) -> List[Dict]:
        """Scrape a list page (announce or registered)."""
        if not self.driver:
            raise RuntimeError("Driver not initialized")
            
        print(f"\nOpening {page_type} page: {url}")
        self.driver.get(url)
        self.current_list_url = url
        
        try:
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        except TimeoutException:
            print(f"  ⚠ Page load timeout for {page_type}")
            return []
        
        all_items = []
        page_index = 1
        
        while page_index <= max_pages:
            print(f"\n  📄 Parsing page {page_index}...")
            
            table = self.find_data_table()
            if not table:
                print("  ⚠ Data table not found")
                break
            
            rows = table.find_elements(By.TAG_NAME, "tr")
            page_items = []
            
            for row_index, row in enumerate(rows):
                if row_index == 0:  # Skip header
                    continue
                    
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) < 4:
                        continue
                    
                    # Extract basic info
                    item = self._parse_row(cells, page_type)
                    if item:
                        page_items.append(item)
                        
                except Exception as e:
                    continue
            
            if not page_items:
                print("  ⚠ No items found on this page")
                break
                
            all_items.extend(page_items)
            print(f"  ✓ Found {len(page_items)} items, total: {len(all_items)}")
            
            # Try to go to next page
            if not self._go_to_next_page():
                break
            page_index += 1
        
        return all_items
    
    def _parse_row(self, cells, page_type: str) -> Optional[Dict]:
        """Parse a single row from the table."""
        try:
            # Find the link element for case name
            link = None
            case_name = ""
            detail_url = ""
            
            for cell in cells:
                try:
                    link = cell.find_element(By.TAG_NAME, "a")
                    case_name = link.text.strip()
                    href = link.get_attribute("href")
                    if href:
                        detail_url = urljoin(self.BASE_URL, href)
                    break
                except NoSuchElementException:
                    continue
            
            if not case_name:
                case_name = cells[0].text.strip() if cells else ""
            
            # Extract other fields
            agency = cells[1].text.strip() if len(cells) > 1 else ""
            date_str = cells[2].text.strip() if len(cells) > 2 else ""
            
            return {
                "tenderName": case_name,
                "agency": agency,
                "date": date_str,
                "sourceUrl": detail_url,
                "pageType": page_type,
                "scrapedAt": datetime.now().isoformat(),
            }
        except Exception as e:
            return None
    
    def _go_to_next_page(self) -> bool:
        """Try to navigate to the next page."""
        try:
            # Look for next page link
            next_selectors = [
                "//a[contains(text(), '下一頁')]",
                "//a[contains(text(), '>')]",
                "//a[contains(@class, 'next')]",
            ]
            
            for selector in next_selectors:
                try:
                    next_link = self.driver.find_element(By.XPATH, selector)
                    if next_link.is_displayed():
                        next_link.click()
                        time.sleep(1)
                        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
                        return True
                except:
                    continue
            
            return False
        except:
            return False
    
    def scrape_all(self, max_pages: int = 50) -> Dict[str, Any]:
        """Scrape both announce and registered lists."""
        try:
            self.setup_driver()
            
            all_data = []
            
            # Scrape announce list
            print("\n" + "=" * 50)
            print("Scraping ANNOUNCE list...")
            print("=" * 50)
            announce_items = self.scrape_list_page(self.ANNOUNCE_URL, "announce", max_pages)
            all_data.extend(announce_items)
            
            # Scrape registered list
            print("\n" + "=" * 50)
            print("Scraping REGISTERED list...")
            print("=" * 50)
            registered_items = self.scrape_list_page(self.REGISTERED_URL, "registered", max_pages)
            all_data.extend(registered_items)
            
            return self._build_result(all_data)
            
        finally:
            self.close_driver()
    
    def _build_result(self, records: List[Dict]) -> Dict[str, Any]:
        """Build the final result structure."""
        unique_agencies = {item.get("agency") for item in records if item.get("agency")}
        
        return {
            "crawlerId": "ppp-mof",
            "runAt": datetime.now().isoformat(),
            "stats": {
                "totalRecords": len(records),
                "totalAgencies": len(unique_agencies),
            },
            "totalRecords": len(records),
            "data": records,
        }


def run_procurement_scraper(max_pages: int = 50) -> Dict[str, Any]:
    """Run the procurement scraper and return results."""
    scraper = ProcurementScraper(headless=True)
    return scraper.scrape_all(max_pages=max_pages)


if __name__ == "__main__":
    import json
    result = run_procurement_scraper()
    print(f"\nTotal records: {result['totalRecords']}")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1000])
