"""
Tender Announcement Scraper - Cloud optimized version
Scrapes tender announcements from government procurement website.
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


class TenderScraper:
    """Tender announcement scraper for cloud execution."""

    BASE_URL = "https://web.pcc.gov.tw"
    RESULT_URL = f"{BASE_URL}/prkms/tender/common/basic/readTenderBasic"

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

    def scrape_tender_announcements(
        self,
        max_pages: Optional[int] = None,
        unlimited: bool = True,
    ) -> List[Dict]:
        """
        Main flow: execute query and auto-paginate.
        """
        if not self.driver or not self.wait:
            raise RuntimeError("Please call setup_driver() first")

        self._trigger_search()

        all_items: List[Dict] = []
        page_index = 1
        if not unlimited:
            max_pages = max_pages or 100
        else:
            max_pages = max_pages or float('inf')

        consecutive_empty_pages = 0
        max_consecutive_empty = 3

        while page_index <= max_pages:
            print(f"\n📄 Parsing page {page_index}...")
            page_items = self._parse_current_page()

            if not page_items:
                consecutive_empty_pages += 1
                print(f"  ⚠ No data on this page (consecutive: {consecutive_empty_pages})")
                if consecutive_empty_pages >= max_consecutive_empty:
                    print(f"⚠ {max_consecutive_empty} consecutive empty pages, stopping.")
                    break
            else:
                consecutive_empty_pages = 0
                all_items.extend(page_items)
                print(f"  ✓ Found {len(page_items)} items, total: {len(all_items)}")

            if not unlimited and page_index >= max_pages:
                print(f"⚠ Reached max pages limit: {max_pages}")
                break

            if self._go_to_next_page(page_index):
                page_index += 1
            else:
                print("  ✓ Reached last page")
                break

        print(f"\n✅ Complete, total records: {len(all_items)}")
        return all_items

    def _trigger_search(self):
        """Navigate to search results page."""
        print("  → Executing search")

        # 重要調整：
        # 1. dateType=isSpdt（等標期內）- 抓取所有招標中的案件，而非只有當日
        # 2. pageSize=100 - 每頁顯示 100 筆，減少翻頁次數
        params = [
            "pageSize=100",
            "firstSearch=true",
            "searchType=basic",
            "isBinding=N",
            "isLogIn=N",
            "level_1=on",
            "orgName=",
            "orgId=",
            "tenderName=",
            "tenderId=",
            "tenderType=TENDER_DECLARATION",
            "tenderWay=TENDER_WAY_ALL_DECLARATION",
            "dateType=isSpdt",
            "tenderStartDate=",
            "tenderEndDate=",
            "radProctrgCate=",
            "policyAdvocacy="
        ]

        query_string = "&".join(params)
        result_url = f"{self.RESULT_URL}?{query_string}"

        print(f"  → Accessing: {result_url}")
        self.driver.get(result_url)

        try:
            self.wait.until(EC.url_contains("readTenderBasic"))
            print("  ✓ Entered results page")
        except TimeoutException:
            print("  ⚠ URL didn't change as expected")

        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpam tbody tr")))
            print("  ✓ Results table loaded")
        except TimeoutException:
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")))
                print("  ⚠ Using fallback selector for table")
            except TimeoutException:
                raise RuntimeError("Cannot find results table")

    def _parse_current_page(self) -> List[Dict]:
        """Parse current page data."""
        rows = self.driver.find_elements(By.CSS_SELECTOR, "#tpam tbody tr")
        results: List[Dict] = []

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 10:
                continue

            seq = cols[0].text.strip()
            agency = cols[1].text.strip()

            case_info = cols[2].text.strip()
            case_number = ""
            case_name = case_info
            if "\n" in case_info:
                parts = case_info.split("\n", 1)
                case_number = parts[0].strip()
                case_name = parts[1].strip()

            transmission_count = cols[3].text.strip()
            tender_method = cols[4].text.strip()
            procurement_type = cols[5].text.strip()
            announcement_date = cols[6].text.strip()
            deadline = cols[7].text.strip()
            budget = cols[8].text.strip()

            detail_url = self._extract_detail_link(cols[9])

            if not case_name:
                continue

            basic_info = {
                "serial_no": seq,
                "agency": agency,
                "tenderId": case_number,
                "tenderName": case_name,
                "transmission_count": transmission_count,
                "tender_method": tender_method,
                "procurement_type": procurement_type,
                "announcement_date": announcement_date,
                "deadline": deadline,
                "budget_amount": budget,
                "sourceUrl": detail_url,
                "scrapedAt": datetime.now().isoformat(),
            }

            results.append(basic_info)

        return results

    def _go_to_next_page(self, current_page: int) -> bool:
        """Navigate to next page by modifying URL."""
        try:
            next_page = current_page + 1
            current_url = self.driver.current_url

            if "d-49738-p=" in current_url:
                new_url = current_url.replace(f"d-49738-p={current_page}", f"d-49738-p={next_page}")
            else:
                if "?" in current_url:
                    new_url = current_url + f"&d-49738-p={next_page}"
                else:
                    new_url = current_url + f"?d-49738-p={next_page}"

            print(f"  → Going to page {next_page}")
            self.driver.get(new_url)

            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpam tbody tr")))
                return True
            except TimeoutException:
                rows = self.driver.find_elements(By.CSS_SELECTOR, "#tpam tbody tr")
                return len(rows) > 0

        except Exception as exc:
            print(f"  ✗ Page navigation failed: {exc}")
            return False

    def _extract_detail_link(self, cell) -> Optional[str]:
        """Extract detail page link from cell."""
        try:
            links = cell.find_elements(By.TAG_NAME, "a")
            for link in links:
                link_text = link.text.strip()
                if "檢視" in link_text:
                    href = link.get_attribute("href")
                    if href and not href.lower().startswith("javascript"):
                        return urljoin(self.BASE_URL, href)
        except:
            pass
        return None

    def scrape_all(self, max_pages: Optional[int] = None) -> Dict[str, Any]:
        """Run the scraper and return structured results."""
        try:
            self.setup_driver()
            records = self.scrape_tender_announcements(max_pages=max_pages)
            return self._build_result(records)
        finally:
            self.close_driver()

    def _build_result(self, records: List[Dict]) -> Dict[str, Any]:
        """Build final result structure."""
        unique_agencies = {item.get("agency") for item in records if item.get("agency")}
        return {
            "crawlerId": "tender-announcement",
            "runAt": datetime.now().isoformat(),
            "stats": {
                "totalRecords": len(records),
                "totalAgencies": len(unique_agencies),
            },
            "totalRecords": len(records),
            "data": records,
        }


def run_tender_scraper(max_pages: Optional[int] = None) -> Dict[str, Any]:
    """Run the tender scraper and return results."""
    scraper = TenderScraper(headless=True)
    return scraper.scrape_all(max_pages=max_pages)


if __name__ == "__main__":
    result = run_tender_scraper(max_pages=5)
    print(f"\nTotal records: {result['totalRecords']}")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1000])
