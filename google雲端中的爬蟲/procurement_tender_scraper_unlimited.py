"""
政府電子採購網 - 招標公告爬蟲
參考 `procurement_scraper_autopagination.py` 和 `public_read_scraper.py` 的結構，
針對 https://web.pcc.gov.tw/prkms/tender/common/basic/indexTenderBasic 的招標查詢。
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


class ProcurementTenderScraper:
    """招標公告爬蟲，負責列表查詢、翻頁與資料解析。"""

    BASE_URL = "https://web.pcc.gov.tw"
    QUERY_URL = f"{BASE_URL}/prkms/tender/common/basic/indexTenderBasic"
    RESULT_URL_PATTERN = f"{BASE_URL}/prkms/tender/common/basic/readTenderBasic"

    def __init__(self, headless: bool = False, wait_seconds: int = 20):
        self.headless = headless
        self.wait_seconds = wait_seconds
        self.driver = None
        self.wait: WebDriverWait | None = None

    # ------------------------------------------------------------------ #
    # Driver lifecycle
    # ------------------------------------------------------------------ #
    def setup_driver(self):
        """初始化 Chrome WebDriver。"""
        print("正在初始化 Chrome WebDriver ...")
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--lang=zh-TW")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36"
        )

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, self.wait_seconds)
        print("✓ Chrome WebDriver 初始化完成")

    def close_driver(self):
        """關閉瀏覽器。"""
        if self.driver:
            self.driver.quit()
            self.driver = None
        print("✓ 瀏覽器已關閉")

    # ------------------------------------------------------------------ #
    # 高階流程
    # ------------------------------------------------------------------ #
    def scrape_tender_announcements(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        date_mode: str = "isNow",
        keywords: list[str] | None = None,
        max_pages: int | None = None,
        tender_type: str = "TENDER_DECLARATION",
        tender_way: str = "TENDER_WAY_ALL_DECLARATION",
        unlimited: bool = False,
        batch_size: int = 1000,
        output_prefix: str | None = None,
    ) -> list[dict]:
        """
        主流程：執行查詢並自動翻頁，回傳所有招標資料。

        :param start_date: 民國年格式 (YYY/MM/DD)，需搭配 date_mode='isDate'
        :param end_date: 民國年格式 (YYY/MM/DD)，需搭配 date_mode='isDate'
        :param date_mode: isNow / isSpdt / isDate
        :param keywords: 若指定則以關鍵字過濾（機關名稱 + 標案名稱）
        :param max_pages: 限制最大頁數，None 則持續至最後一頁
        :param tender_type: 招標類型，預設 TENDER_DECLARATION
        :param tender_way: 招標方式，預設 TENDER_WAY_ALL_DECLARATION
        :param unlimited: True 時無頁數限制，持續爬取至最後一頁
        :param batch_size: 每批次存檔的筆數，預設 1000 筆
        :param output_prefix: 輸出檔案前綴，若指定則啟用分批存檔
        """
        if not self.driver or not self.wait:
            raise RuntimeError("請先呼叫 setup_driver() 初始化 WebDriver")

        # 直接觸發搜尋（訪問結果頁面），不需要先訪問查詢頁面
        self._trigger_search()

        all_items: list[dict] = []
        batch_items: list[dict] = []  # 當前批次的資料
        batch_number = 1  # 批次序號
        total_saved = 0  # 已存檔的總筆數
        
        page_index = 1
        if not unlimited:
            max_pages = max_pages or 100  # 安全停損，避免無窮迴圈
        else:
            max_pages = max_pages or float('inf')  # 無限制模式

        consecutive_empty_pages = 0
        max_consecutive_empty = 3  # 連續3頁空白就停止，避免無限迴圈

        while page_index <= max_pages:
            print(f"\n📄 解析第 {page_index} 頁 ...")
            page_items = self._parse_current_page(keywords=keywords)

            if not page_items:
                consecutive_empty_pages += 1
                print(f"  ⚠ 本頁沒有可解析的資料（連續 {consecutive_empty_pages} 頁空白）")
                if consecutive_empty_pages >= max_consecutive_empty:
                    print(f"⚠ 連續 {max_consecutive_empty} 頁都沒有資料，停止爬取。")
                    break
            else:
                consecutive_empty_pages = 0  # 重置計數器
                all_items.extend(page_items)
                batch_items.extend(page_items)
                print(f"  ✓ 本頁擷取 {len(page_items)} 筆，累計 {len(all_items)} 筆")
                
                # 分批存檔：當 batch_items 達到 batch_size 時存檔
                if output_prefix and len(batch_items) >= batch_size:
                    self._save_batch(batch_items[:batch_size], output_prefix, batch_number)
                    total_saved += batch_size
                    batch_items = batch_items[batch_size:]  # 保留超過的部分
                    batch_number += 1
                    print(f"  📦 已存檔 {total_saved} 筆（批次 {batch_number - 1}）")

            # 檢查是否達到頁數上限（僅在非無限制模式）
            if not unlimited and page_index >= max_pages:
                print(f"⚠ 達到預設安全上限 {max_pages} 頁，停止爬取。")
                break

            # 嘗試翻到下一頁
            if self._go_to_next_page(page_index):
                page_index += 1
                # _go_to_next_page 內部已使用顯式等待，無需額外 sleep
            else:
                print("  ✓ 已到最後一頁")
                break

        # 存檔剩餘的資料
        if output_prefix and batch_items:
            self._save_batch(batch_items, output_prefix, batch_number)
            total_saved += len(batch_items)
            print(f"  📦 已存檔最後 {len(batch_items)} 筆（批次 {batch_number}）")

        print(f"\n✅ 完成，共擷取 {len(all_items)} 筆招標公告資料")
        if output_prefix:
            print(f"📁 共輸出 {batch_number} 個檔案，總計 {total_saved} 筆")
        return all_items
    
    def _save_batch(self, items: list[dict], prefix: str, batch_num: int):
        """存檔單一批次的資料"""
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"{prefix}_{timestamp}_batch{batch_num:03d}.json"
        payload = {
            "crawlerId": "tender-announcement",
            "runAt": datetime.now().isoformat(),
            "batchNumber": batch_num,
            "totalRecords": len(items),
            "data": items,
        }
        self.save_to_json(payload, filename)

    # ------------------------------------------------------------------ #
    # 查詢頁面操作
    # ------------------------------------------------------------------ #
    def _open_query_page(self):
        assert self.driver and self.wait
        print(f"開啟查詢頁面：{self.QUERY_URL}")
        self.driver.get(self.QUERY_URL)
        # 等待查詢頁面載入，使用核心元素等待
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, "tenderTypeSelect")))
        except TimeoutException:
            # 嘗試使用更寬鬆的選擇器
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select[id*='tenderType'], select[name*='tenderType']")))
                print("  ⚠ 使用備用選擇器找到招標類型選擇器")
            except TimeoutException:
                raise RuntimeError("無法載入查詢頁面，找不到招標類型選擇器，請檢查頁面結構是否有變動")

    def _prepare_filters(
        self,
        start_date: str | None,
        end_date: str | None,
        date_mode: str,
        tender_type: str,
        tender_way: str
    ):
        assert self.driver and self.wait

        # 選擇招標類型
        tender_type_select = Select(self.driver.find_element(By.ID, "tenderTypeSelect"))
        tender_type_select.select_by_value(tender_type)
        print(f"  ✓ 招標類型已設定為：{tender_type}")

        # 選擇招標方式
        tender_way_select = Select(self.driver.find_element(By.ID, "declarationSelect"))
        tender_way_select.select_by_value(tender_way)
        print(f"  ✓ 招標方式已設定為：{tender_way}")

        # 日期區間
        if date_mode == "isDate" and start_date and end_date:
            try:
                date_radio = self.driver.find_element(By.ID, "level_23")  # isDate radio button
                date_radio.click()
                start_input = self.driver.find_element(By.CSS_SELECTOR, "#tenderStartDateArea input.form-date")
                end_input = self.driver.find_element(By.CSS_SELECTOR, "#tenderEndDateArea input.form-date")
                self.driver.execute_script("arguments[0].value = arguments[1];", start_input, start_date)
                self.driver.execute_script("arguments[0].value = arguments[1];", end_input, end_date)
                print(f"  ✓ 已設定日期區間：{start_date} ~ {end_date}")
            except NoSuchElementException:
                print("  ⚠ 找不到日期欄位，改用預設『即時』條件")
        elif date_mode == "isSpdt":
            try:
                self.driver.find_element(By.ID, "level_22").click()  # isSpdt radio button
                print("  ✓ 已切換為『特定日期』模式")
            except NoSuchElementException:
                print("  ⚠ 找不到『特定日期』選項，改用預設『即時』條件")
        else:
            try:
                self.driver.find_element(By.ID, "level_21").click()  # isNow radio button
            except NoSuchElementException:
                pass  # 若沒有該 radio，維持預設狀態即可

    def _trigger_search(self):
        assert self.driver and self.wait
        print("  → 執行查詢")

        # 直接訪問結果頁面 URL，這是最可靠的方法
        # 重要調整：
        # 1. dateType=isSpdt（等標期內）- 抓取所有招標中的案件，而非只有當日
        # 2. pageSize=100 - 每頁顯示 100 筆，減少翻頁次數
        params = [
            "pageSize=100",  # 每頁 100 筆（最大值），減少翻頁次數
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
            "dateType=isSpdt",  # 等標期內（抓取所有招標中的案件）
            "tenderStartDate=",
            "tenderEndDate=",
            "radProctrgCate=",
            "policyAdvocacy="
        ]

        query_string = "&".join(params)
        result_url = f"{self.RESULT_URL_PATTERN}?{query_string}"

        print(f"  → 訪問結果頁面: {result_url}")
        self.driver.get(result_url)

        # 等待頁面載入完成
        try:
            self.wait.until(EC.url_contains("readTenderBasic"))
            print("  ✓ 已進入結果頁面")
        except TimeoutException:
            print("  ⚠ URL 未如預期改變，可能有問題")

        # 等待結果表格出現
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpam tbody tr")))
            print("  ✓ 查詢結果表格載入完成")
        except TimeoutException:
            # 如果找不到 tpam，嘗試尋找其他可能的表格結構
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")))
                print("  ⚠ 使用備用選擇器找到表格")
            except TimeoutException:
                raise RuntimeError("找不到查詢結果表格，請檢查頁面結構是否有變動")

        print("  ✓ 查詢完成，準備開始擷取資料")

    # ------------------------------------------------------------------ #
    # 翻頁與解析
    # ------------------------------------------------------------------ #
    def _parse_current_page(self, keywords: list[str] | None = None) -> list[dict]:
        """
        從搜尋結果頁面直接解析招標資料。
        不進入詳細頁面，直接從列表中提取所有可用資訊。
        """
        assert self.driver
        rows = self.driver.find_elements(By.CSS_SELECTOR, "#tpam tbody tr")
        results: list[dict] = []

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 10:  # 確保有足夠的欄位
                continue

            # 解析各欄位
            seq = cols[0].text.strip()  # 項次
            agency = cols[1].text.strip()  # 機關名稱

            # 標案案號和名稱（在同一欄）
            case_info = cols[2].text.strip()
            case_number = ""
            case_name = case_info
            if "\n" in case_info:
                parts = case_info.split("\n", 1)
                case_number = parts[0].strip()
                case_name = parts[1].strip()

            transmission_count = cols[3].text.strip()  # 傳輸次數
            tender_method = cols[4].text.strip()  # 招標方式
            procurement_type = cols[5].text.strip()  # 採購性質
            announcement_date = cols[6].text.strip()  # 公告日期
            deadline = cols[7].text.strip()  # 截止投標
            budget = cols[8].text.strip()  # 預算金額

            # 取得「檢視」連結作為 sourceUrl（從功能選項欄位）
            source_url = self._extract_detail_link(cols[9])

            # 驗證必要欄位
            if not case_name:
                continue

            # 關鍵字過濾
            if keywords and not self._match_keywords(f"{agency}{case_name}", keywords):
                continue

            # 直接從搜尋結果頁面擷取所有資料，不進入詳細頁面
            record = {
                "serial_no": seq,
                "agency": agency,
                "tenderId": case_number,  # 統一使用 camelCase
                "tenderName": case_name,  # 統一使用 camelCase
                "transmission_count": transmission_count,
                "tender_method": tender_method,
                "procurement_type": procurement_type,
                "announcement_date": announcement_date,
                "deadline": deadline,
                "budget_amount": budget,
                "sourceUrl": source_url,  # 從「檢視」連結取得
            }

            results.append(record)

        return results

    def _go_to_next_page(self, current_page: int) -> bool:
        assert self.driver and self.wait
        """
        通過修改 URL 參數來翻頁，而不是點擊連結。
        政府電子採購網使用 d-49738-p 參數控制分頁。
        """
        try:
            next_page = current_page + 1
            current_url = self.driver.current_url

            # 解析當前 URL 並更新分頁參數
            if "d-49738-p=" in current_url:
                # 替換現有的分頁參數
                new_url = current_url.replace(f"d-49738-p={current_page}", f"d-49738-p={next_page}")
            else:
                # 如果沒有分頁參數，添加它（通常第一頁沒有）
                if "?" in current_url:
                    new_url = current_url + f"&d-49738-p={next_page}"
                else:
                    new_url = current_url + f"?d-49738-p={next_page}"

            print(f"  → 翻到第 {next_page} 頁: {new_url}")
            self.driver.get(new_url)

            # 等待頁面載入
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpam tbody tr")))
                print("  ✓ 新頁面載入完成")
                return True
            except TimeoutException:
                # 檢查是否真的沒有資料（可能是最後一頁）
                try:
                    # 檢查是否有表格行
                    rows = self.driver.find_elements(By.CSS_SELECTOR, "#tpam tbody tr")
                    if not rows:
                        print("  ✓ 已到最後一頁（無資料）")
                        return False
                    else:
                        print("  ⚠ 新頁面載入逾時，但有資料")
                        return True
                except:
                    print("  ⚠ 無法確認頁面內容")
                    return False

        except Exception as exc:
            print(f"  ✗ 翻頁失敗：{exc}")
            return False

    # ------------------------------------------------------------------ #
    # 輔助工具
    # ------------------------------------------------------------------ #
    def _extract_detail_link(self, cell) -> str | None:
        """從功能選項欄位提取詳細頁面連結"""
        try:
            # 尋找包含 "檢視" 的連結
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

    @staticmethod
    def _match_keywords(text: str, keywords: list[str]) -> bool:
        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in keywords)

    # ------------------------------------------------------------------ #
    # 輸出
    # ------------------------------------------------------------------ #
    @staticmethod
    def save_to_json(data: list[dict], filename: str):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 JSON 已儲存：{filename}")


def main():
    print("\n" + "=" * 70)
    print("🏢 招標公告自動化爬蟲")
    print("    針對政府電子採購網招標查詢")
    print("    📦 每 1000 筆自動存檔一次")
    print("=" * 70 + "\n")

    scraper = ProcurementTenderScraper(headless=False)
    keywords = None  # 例如：["資訊", "電腦", "污水"]
    records: list[dict] = []

    try:
        print("🚀 初始化瀏覽器...")
        scraper.setup_driver()

        print("🔍 開始爬取招標公告...")
        # 啟用分批存檔：每 1000 筆輸出一個檔案
        records = scraper.scrape_tender_announcements(
            keywords=keywords, 
            unlimited=True,
            batch_size=1000,
            output_prefix="tender_batch"  # 輸出檔案：tender_batch_YYYYMMDD_batch001.json
        )

        print(f"\n📝 總計擷取 {len(records)} 筆資料")

        if records:
            unique_agencies = {item.get("agency") for item in records if item.get("agency")}
            print("\n" + "=" * 70)
            print("📊 擷取統計")
            print("=" * 70)
            print(f"  總筆數：{len(records)}")
            print(f"  機關數：{len(unique_agencies)}")
            print("=" * 70 + "\n")
        else:
            print("⚠️  未擷取到任何資料")

    except Exception as exc:
        print(f"\n✗ 執行失敗：{exc}")
        import traceback
        traceback.print_exc()
    finally:
        scraper.close_driver()
        print("🛑 瀏覽器已關閉")
        if records:
            print("✅ 輸出檔案已完成，請於專案目錄檢視。")
        else:
            print("❌ 未產生任何資料檔案。")


def _build_tender_payload(
    records: List[Dict[str, Any]],
    *,
    keywords: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_mode: str = "isNow",
    tender_type: str = "TENDER_DECLARATION",
    tender_way: str = "TENDER_WAY_ALL_DECLARATION",
) -> Dict[str, Any]:
    """統一輸出格式，與其他爬蟲保持一致的外層結構"""
    timestamp = datetime.now()
    unique_agencies = {item.get("agency") for item in records if item.get("agency")}
    return {
        "crawlerId": "tender-announcement",
        "runAt": timestamp.isoformat(),
        "filters": {
            "keywords": keywords or [],
            "dateMode": date_mode,
            "startDate": start_date,
            "endDate": end_date,
            "tenderType": tender_type,
            "tenderWay": tender_way,
        },
        "stats": {
            "totalRecords": len(records),
            "totalAgencies": len(unique_agencies),
        },
        "totalRecords": len(records),
        "data": records,
    }


def run_tender_announcement(
    *,
    headless: bool = True,
    keywords: Optional[List[str]] = None,
    max_pages: Optional[int] = None,
    date_mode: str = "isNow",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tender_type: str = "TENDER_DECLARATION",
    tender_way: str = "TENDER_WAY_ALL_DECLARATION",
    output_dir: Optional[Path] = None,
    unlimited: bool = False
) -> Dict[str, Any]:
    """
    供外部呼叫的封裝函式，便於整合與自動化。

    :return: dict，包含統計資訊與資料列表
    """
    scraper = ProcurementTenderScraper(headless=headless)
    try:
        scraper.setup_driver()
        records = scraper.scrape_tender_announcements(
            start_date=start_date,
            end_date=end_date,
            date_mode=date_mode,
            keywords=keywords,
            max_pages=max_pages,
            tender_type=tender_type,
            tender_way=tender_way,
            unlimited=unlimited,
        )
        result = _build_tender_payload(
            records,
            keywords=keywords,
            start_date=start_date,
            end_date=end_date,
            date_mode=date_mode,
            tender_type=tender_type,
            tender_way=tender_way,
        )

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = output_dir / f"tender_announcement_{datetime.now():%Y%m%d_%H%M%S}.json"
            ProcurementTenderScraper.save_to_json(result, str(filename))

        return result
    finally:
        scraper.close_driver()


if __name__ == "__main__":
    main()
