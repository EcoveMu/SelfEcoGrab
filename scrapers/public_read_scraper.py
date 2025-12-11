"""
Public Read Scraper - Cloud optimized version
Scrapes public read tender data from government procurement website.
"""

import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


class PublicReadScraper:
    """Public read tender scraper for cloud execution."""

    BASE_URL = "https://web.pcc.gov.tw"
    LIST_URL = f"{BASE_URL}/pis/"

    def __init__(self, headless: bool = True, wait_seconds: int = 20):
        self.headless = headless
        self.wait_seconds = wait_seconds
        self.driver = None
        self.wait = None

    def setup_driver(self):
        """Initialize Chrome WebDriver."""
        print("Initializing Chrome WebDriver...")
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--lang=zh-TW")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, self.wait_seconds)
        print("✓ Chrome WebDriver initialized")

    def close_driver(self):
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            self.driver = None
        print("✓ Browser closed")

    def scrape_public_read(
        self,
        max_pages: Optional[int] = None,
    ) -> List[Dict]:
        """
        Main flow: execute query and auto-paginate.
        """
        if not self.driver or not self.wait:
            raise RuntimeError("Please call setup_driver() first")

        self._open_search_page()
        self._prepare_filters()
        self._trigger_search()

        all_items: List[Dict] = []
        page_index = 1
        max_pages = max_pages or 100

        while page_index <= max_pages:
            print(f"\n📄 Parsing page {page_index}...")
            page_items = self._parse_current_page()
            
            if not page_items:
                print("  ⚠ No data on this page, stopping.")
                break

            all_items.extend(page_items)
            print(f"  ✓ Found {len(page_items)} items, total: {len(all_items)}")

            if page_index >= max_pages:
                print(f"⚠ Reached max pages limit: {max_pages}")
                break

            if self._go_to_next_page():
                page_index += 1
            else:
                print("  ✓ Reached last page")
                break

        print(f"\n✅ Complete, total records: {len(all_items)}")
        return all_items

    def _open_search_page(self):
        """Open the search page."""
        print(f"Opening search page: {self.LIST_URL}")
        self.driver.get(self.LIST_URL)
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, "tenderTypeSelect")))
        except TimeoutException:
            try:
                self.wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "select[id*='tenderType']")
                ))
            except TimeoutException:
                raise RuntimeError("Cannot load search page")

    def _prepare_filters(self):
        """Set up search filters."""
        tender_type_select = Select(self.driver.find_element(By.ID, "tenderTypeSelect"))
        tender_type_select.select_by_value("PUBLIC_READ")
        print("  ✓ Set tender type to PUBLIC_READ")

        try:
            self.driver.find_element(By.ID, "basicIsNowDateTypeId").click()
        except NoSuchElementException:
            pass

    def _trigger_search(self):
        """Submit the search."""
        print("  → Submitting search")
        search_clicked = False

        search_locators = [
            (By.ID, "basicTenderSearchId"),
            (By.CSS_SELECTOR, "#basicTenderSearchForm a[onclick*='basicTenderSearch']"),
            (By.XPATH, "//form[@id='basicTenderSearchForm']//a[@title='查詢']"),
        ]

        initial_handles = set(self.driver.window_handles)

        for by, locator in search_locators:
            try:
                element = self.driver.find_element(by, locator)
                self.driver.execute_script("arguments[0].click();", element)
                search_clicked = True
                break
            except NoSuchElementException:
                continue

        if not search_clicked:
            raise RuntimeError("Cannot find search button")

        try:
            self.wait.until(lambda d: len(d.window_handles) > len(initial_handles))
            new_handle = next(iter(set(self.driver.window_handles) - initial_handles))
            self.driver.switch_to.window(new_handle)
        except TimeoutException:
            pass

        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpRead tbody tr")))
        except TimeoutException:
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")))
            except TimeoutException:
                raise RuntimeError("Cannot find results table")

        print("  ✓ Search results loaded")

    def _parse_current_page(self) -> List[Dict]:
        """Parse current page data."""
        rows = self.driver.find_elements(By.CSS_SELECTOR, "#tpRead tbody tr")
        results: List[Dict] = []

        for row in rows:
            try:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 7:
                    continue

                seq = cols[0].text.strip()
                agency = cols[1].text.strip()
                tender_id = cols[2].text.strip()
                tender_name = cols[3].text.strip()
                announcement_count = cols[4].text.strip()
                period_text = cols[5].text.strip()
                period_start, period_end = self._parse_period(period_text)

                detail_url = self._extract_link_from_cell(cols[6]) or self._extract_link_from_cell(cols[2])

                basic_info = {
                    "serial_no": seq,
                    "agency": agency,
                    "tenderId": tender_id,
                    "tenderName": tender_name,
                    "announcement_count": announcement_count,
                    "public_read_start": period_start,
                    "public_read_end": period_end,
                    "period_raw": period_text,
                    "sourceUrl": detail_url,
                    "scrapedAt": datetime.now().isoformat(),
                }

                results.append(basic_info)

            except Exception as e:
                continue

        return results

    def _go_to_next_page(self) -> bool:
        """Navigate to next page."""
        try:
            table = self.driver.find_element(By.ID, "tpRead")
        except NoSuchElementException:
            return False

        try:
            next_link = self.driver.find_element(
                By.XPATH, "//div[@id='pagelinks']//a[contains(text(),'下一頁')]"
            )
            if not next_link.is_displayed():
                return False

            self.driver.execute_script("arguments[0].click();", next_link)
            self.wait.until(EC.staleness_of(table))
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpRead tbody tr")))
            return True
        except (NoSuchElementException, TimeoutException):
            return False

    def _extract_link_from_cell(self, cell) -> Optional[str]:
        """Extract link from cell."""
        try:
            link = cell.find_element(By.TAG_NAME, "a")
            href = link.get_attribute("href")
            if href and not href.lower().startswith("javascript"):
                return urljoin(self.BASE_URL, href)
        except NoSuchElementException:
            return None
        return None

    @staticmethod
    def _parse_period(period_text: str) -> tuple:
        """Parse period text into start and end dates."""
        if not period_text:
            return None, None
        normalized = period_text.replace("－", "-").replace("─", "-").replace("~", "-")
        normalized = re.sub(r"\s+", "", normalized)
        parts = re.split(r"[-至]+", normalized)
        if len(parts) >= 2:
            return parts[0] or None, parts[1] or None
        return normalized or None, None

    def scrape_all(self, max_pages: Optional[int] = None) -> Dict[str, Any]:
        """Run the scraper and return structured results."""
        try:
            self.setup_driver()
            records = self.scrape_public_read(max_pages=max_pages)
            return self._build_result(records)
        finally:
            self.close_driver()

    def _build_result(self, records: List[Dict]) -> Dict[str, Any]:
        """Build final result structure."""
        unique_agencies = {item.get("agency") for item in records if item.get("agency")}
        return {
            "crawlerId": "public-read",
            "runAt": datetime.now().isoformat(),
            "stats": {
                "totalRecords": len(records),
                "totalAgencies": len(unique_agencies),
            },
            "totalRecords": len(records),
            "data": records,
        }


def run_public_read_scraper(max_pages: Optional[int] = None) -> Dict[str, Any]:
    """Run the public read scraper and return results."""
    scraper = PublicReadScraper(headless=True)
    return scraper.scrape_all(max_pages=max_pages)


if __name__ == "__main__":
    result = run_public_read_scraper(max_pages=5)
    print(f"\nTotal records: {result['totalRecords']}")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1000])
