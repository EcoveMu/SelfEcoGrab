"""
政府電子採購網 - 公開閱覽標案資料爬蟲
參考 `procurement_scraper_autopagination.py` 的結構，改為針對
https://web.pcc.gov.tw/pis/ 的「公開閱覽」查詢。
"""

import json
import re
import time
import warnings
from pathlib import Path
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

warnings.simplefilter("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)  # type: ignore[attr-defined]


class PublicReadScraper:
    """公開閱覽標案爬蟲，負責列表抓取、翻頁與細節解析。"""

    BASE_URL = "https://web.pcc.gov.tw"
    LIST_URL = f"{BASE_URL}/pis/"

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
    def scrape_public_read(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        date_mode: str = "isNow",
        keywords: list[str] | None = None,
        max_pages: int | None = None,
    ) -> list[dict]:
        """
        主流程：執行查詢並自動翻頁，回傳所有標案資料。

        :param start_date: 民國年格式 (YYY/MM/DD)，需搭配 date_mode='isDate'
        :param end_date: 民國年格式 (YYY/MM/DD)，需搭配 date_mode='isDate'
        :param date_mode: isNow / isSpdt / isDate
        :param keywords: 若指定則以關鍵字過濾（機關名稱 + 標案名稱）
        :param max_pages: 限制最大頁數，None 則持續至最後一頁
        """
        if not self.driver or not self.wait:
            raise RuntimeError("請先呼叫 setup_driver() 初始化 WebDriver")

        self._open_search_page()
        self._prepare_filters(start_date, end_date, date_mode)
        self._trigger_search()

        all_items: list[dict] = []
        page_index = 1
        max_pages = max_pages or 100  # 安全停損，避免無窮迴圈

        while page_index <= max_pages:
            print(f"\n📄 解析第 {page_index} 頁 ...")
            page_items = self._parse_current_page(keywords=keywords)
            if not page_items:
                print("  ⚠ 本頁沒有可解析的資料，結束。")
                break

            all_items.extend(page_items)
            print(f"  ✓ 本頁擷取 {len(page_items)} 筆，累計 {len(all_items)} 筆")

            if page_index >= max_pages:
                print(f"⚠ 達到預設安全上限 {max_pages} 頁，停止爬取。")
                break

            if self._go_to_next_page():
                page_index += 1
                # _go_to_next_page 內部已使用顯式等待，無需額外 sleep
            else:
                print("  ✓ 已到最後一頁")
                break

        print(f"\n✅ 完成，共擷取 {len(all_items)} 筆公開閱覽資料")
        return all_items

    # ------------------------------------------------------------------ #
    # 查詢頁面操作
    # ------------------------------------------------------------------ #
    def _open_search_page(self):
        assert self.driver and self.wait
        print(f"開啟查詢頁面：{self.LIST_URL}")
        self.driver.get(self.LIST_URL)
        # 等待查詢頁面載入，使用 ID 等待（這是頁面核心元素，應該穩定存在）
        # 如果找不到，後續操作會失敗，所以這裡的等待是必要的
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, "tenderTypeSelect")))
        except TimeoutException:
            # 嘗試使用更寬鬆的選擇器
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select[id*='tenderType'], select[name*='tenderType']")))
                print("  ⚠ 使用備用選擇器找到招標類型選擇器")
            except TimeoutException:
                raise RuntimeError("無法載入查詢頁面，找不到招標類型選擇器，請檢查頁面結構是否有變動")

    def _prepare_filters(self, start_date: str | None, end_date: str | None, date_mode: str):
        assert self.driver and self.wait

        # 選擇「公開閱覽」
        tender_type_select = Select(self.driver.find_element(By.ID, "tenderTypeSelect"))
        tender_type_select.select_by_value("PUBLIC_READ")
        print("  ✓ 招標類型已切換為「公開閱覽」")

        # 日期區間
        if date_mode == "isDate" and start_date and end_date:
            try:
                date_radio = self.driver.find_element(By.ID, "basicIsDateDateTypeId")
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
                self.driver.find_element(By.ID, "basicIsSpdtDateTypeId").click()
                print("  ✓ 已切換為『特定日期』模式")
            except NoSuchElementException:
                print("  ⚠ 找不到『特定日期』選項，改用預設『即時』條件")
        else:
            try:
                self.driver.find_element(By.ID, "basicIsNowDateTypeId").click()
            except NoSuchElementException:
                pass  # 若沒有該 radio，維持預設狀態即可

    def _trigger_search(self):
        assert self.driver and self.wait
        print("  → 送出查詢")
        search_clicked = False

        search_locators = [
            (By.ID, "basicTenderSearchId"),
            (By.CSS_SELECTOR, "#basicTenderSearchForm a[onclick*='basicTenderSearch']"),
            (By.XPATH, "//form[@id='basicTenderSearchForm']//a[@title='查詢']"),
            (By.XPATH, "(//form[@id='basicTenderSearchForm']//button[contains(text(),'查詢')])[1]"),
        ]

        initial_handles = set(self.driver.window_handles)
        initial_url = self.driver.current_url

        for by, locator in search_locators:
            try:
                element = self.driver.find_element(by, locator)
                self.driver.execute_script("arguments[0].click();", element)
                search_clicked = True
                break
            except NoSuchElementException:
                continue

        if not search_clicked:
            raise RuntimeError("找不到查詢按鈕，請檢查頁面結構是否有變動")

        try:
            self.wait.until(lambda d: len(d.window_handles) > len(initial_handles))
            new_handle = next(iter(set(self.driver.window_handles) - initial_handles))
            self.driver.switch_to.window(new_handle)
        except TimeoutException:
            pass

        try:
            self.wait.until(EC.url_contains("readTenderBasic"))
        except TimeoutException:
            pass

        # 使用 CSS selector 等待結果表格，比直接等待 ID 更穩健
        # 如果 tpRead ID 不存在或命名不同，CSS selector 仍可能找到表格
        # 直接等待表格行出現，這樣即使 ID 有變化也能正常工作
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpRead tbody tr")))
        except TimeoutException:
            # 如果找不到 tpRead，嘗試尋找其他可能的表格結構
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")))
                print("  ⚠ 使用備用選擇器找到表格")
            except TimeoutException:
                raise RuntimeError("找不到查詢結果表格，請檢查頁面結構是否有變動")
        # 使用顯式等待，無需額外 sleep
        print("  ✓ 查詢結果載入完成")

    # ------------------------------------------------------------------ #
    # 翻頁與解析
    # ------------------------------------------------------------------ #
    def _parse_current_page(self, keywords: list[str] | None = None) -> list[dict]:
        assert self.driver
        rows = self.driver.find_elements(By.CSS_SELECTOR, "#tpRead tbody tr")
        results: list[dict] = []
        total_rows = len(rows)
        print(f"  📄 發現 {total_rows} 筆公開閱覽案件")

        # 逐一處理每一行，每次都重新獲取表格以避免 stale element 問題
        for row_index in range(1, total_rows + 1):
            try:
                # 每次迭代都重新獲取表格和行，以避免 stale element 問題
                table = self.driver.find_element(By.ID, "tpRead")
                tbody = table.find_element(By.TAG_NAME, "tbody")
                current_rows = tbody.find_elements(By.TAG_NAME, "tr")

                # 確保行索引有效
                if row_index > len(current_rows):
                    print(f"    ⚠️ 第 {row_index} 行已不存在，跳過")
                    continue

                row = current_rows[row_index - 1]  # -1 因為列表索引從 0 開始
                cols = row.find_elements(By.TAG_NAME, "td")

                if len(cols) < 7:
                    continue

                seq = cols[0].text.strip()
                agency = cols[1].text.strip()

                tender_id = cols[2].text.strip()
                tender_id_link = self._extract_link_from_cell(cols[2])

                tender_name = cols[3].text.strip()
                announcement_count = cols[4].text.strip()

                period_text = cols[5].text.strip()
                period_start, period_end = self._parse_period(period_text)

                detail_url = self._extract_link_from_cell(cols[6]) or tender_id_link

                if keywords and not self._match_keywords(f"{agency}{tender_name}", keywords):
                    continue

                basic_info = {
                    "serial_no": seq,
                    "agency": agency,
                    "tenderId": tender_id,  # 統一使用 camelCase
                    "tenderName": tender_name,  # 統一使用 camelCase（與促參一致）
                    "announcement_count": announcement_count,
                    "public_read_start": period_start,
                    "public_read_end": period_end,
                    "period_raw": period_text,
                    "sourceUrl": detail_url,  # 統一使用 sourceUrl（與促參一致）
                }

                # 解析詳細頁面資訊
                if detail_url:
                    print(f"    📋 解析第 {row_index}/{total_rows} 筆案件詳細資訊...")
                    print(f"      🔗 詳細頁面連結：{detail_url}")
                    detail_info = self._fetch_detail(detail_url)
                    if detail_info and not detail_info.get('detail_error'):
                        detail_basic = detail_info.get('detail_basic', {})
                        print(f"      ✅ 取得詳細資訊：{len(detail_basic)} 個欄位")
                        if detail_basic.get('預算金額'):
                            print(f"      💰 預算金額：{detail_basic['預算金額']}")
                        else:
                            print(f"      ⚠️ 未找到預算金額欄位")
                    else:
                        error_msg = detail_info.get('detail_error', '未知錯誤') if detail_info else '無詳細資訊'
                        print(f"      ❌ 取得詳細資訊失敗：{error_msg}")
                else:
                    detail_info = {}
                    print(f"      ⚠️ 第 {row_index}/{total_rows} 筆案件沒有詳細頁面連結")

                basic_info.update(detail_info)
                results.append(basic_info)

            except Exception as e:
                print(f"    ❌ 處理第 {row_index} 行時發生錯誤：{e}")
                continue

        return results

    def _go_to_next_page(self) -> bool:
        assert self.driver and self.wait
        # 嘗試找到表格，使用更寬鬆的選擇器
        table = None
        try:
            table = self.driver.find_element(By.ID, "tpRead")
        except NoSuchElementException:
            # 如果找不到 tpRead ID，嘗試使用 CSS selector
            try:
                table = self.driver.find_element(By.CSS_SELECTOR, "#tpRead")
            except NoSuchElementException:
                # 如果還是找不到，嘗試找任何包含 tbody 的表格
                try:
                    tables = self.driver.find_elements(By.CSS_SELECTOR, "table tbody")
                    if tables:
                        # 使用第一個找到的表格的父元素（table）
                        table = tables[0].find_element(By.XPATH, "./..")
                except:
                    return False
        
        if not table:
            return False

        try:
            next_link = self.driver.find_element(By.XPATH, "//div[@id='pagelinks']//a[contains(text(),'下一頁')]")
            if not next_link.is_displayed():
                return False

            self.driver.execute_script("arguments[0].click();", next_link)
            self.wait.until(EC.staleness_of(table))
            # 等待新表格出現，使用更寬鬆的選擇器
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpRead tbody tr")))
            except TimeoutException:
                # 如果找不到 tpRead，嘗試等待任何表格行
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")))
            return True
        except NoSuchElementException:
            return False
        except TimeoutException:
            print("  ⚠ 翻頁逾時，停止操作")
            return False

    # ------------------------------------------------------------------ #
    # 細節頁面解析
    # ------------------------------------------------------------------ #
    def _fetch_detail(self, detail_url: str | None) -> dict:
        if not detail_url:
            return {}

        if not self.driver or not self.wait:
            print(f"      ❌ 無法取得詳細資訊：WebDriver 未初始化")
            return {"detail_url": detail_url, "detail_error": "WebDriver not initialized"}

        # 記錄當前頁面 URL，以便之後返回
        current_url = self.driver.current_url

        try:
            print(f"      🌐 訪問詳細頁面：{detail_url}")

            # 使用 Selenium 訪問詳細頁面
            self.driver.get(detail_url)

            # 等待頁面載入 - 嘗試多種可能的等待條件
            try:
                # 等待主要內容區域出現
                self.wait.until(
                    lambda d: d.find_element(By.CSS_SELECTOR, "table") or
                             d.find_element(By.ID, "printRange") or
                             len(d.find_elements(By.TAG_NAME, "table")) > 0
                )
            except TimeoutException:
                print(f"      ⚠️ 頁面載入逾時，但繼續嘗試解析")

            # 檢查是否成功載入詳細頁面
            page_title = self.driver.title
            print(f"      📄 頁面標題：{page_title}")

            # 如果頁面標題顯示錯誤或未找到，嘗試重新載入
            if "404" in page_title or "錯誤" in page_title or "Error" in page_title.lower():
                print(f"      ⚠️ 頁面載入異常，嘗試重新整理")
                self.driver.refresh()
                self.wait.until(
                    lambda d: d.find_element(By.CSS_SELECTOR, "table") or
                             len(d.find_elements(By.TAG_NAME, "table")) > 0
                )

            # 取得頁面原始碼
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, "html.parser")

            detail_basic = self._parse_basic_detail_table(soup)
            attachments = self._parse_attachment_table(soup, detail_url)

            print(f"      📄 解析到 {len(detail_basic)} 個基本欄位，{len(attachments)} 個附件")

            # 從各個欄位中提取預算金額
            budget_amount = None
            budget_source = ""
            description = detail_basic.get("附加說明", "")

            # 1. 優先檢查是否有專門的預算金額欄位
            if detail_basic.get("預算金額", "").strip():
                budget_amount = detail_basic["預算金額"].strip()
                budget_source = "預算金額欄位"
                print(f"      💰 從預算金額欄位取得：{budget_amount}")

            # 2. 如果沒有，檢查附加說明
            if not budget_amount:
                if description:
                    extracted = self._extract_budget_from_description(description)
                    if extracted:
                        budget_amount = extracted
                        budget_source = "附加說明"
                        print(f"      💰 從附加說明提取：{budget_amount}")
                    else:
                        print(f"      📝 附加說明長度：{len(description)} 字，未找到預算金額")

            # 3. 檢查其他可能的欄位
            if not budget_amount:
                possible_fields = ["採購金額級距", "預算金額是否公開", "決標金額", "預算價金", "契約金額"]
                for field in possible_fields:
                    if detail_basic.get(field, "").strip():
                        value = detail_basic[field].strip()
                        # 檢查是否包含金額模式
                        if "元" in value or any(char.isdigit() for char in value):
                            budget_amount = value
                            budget_source = f"{field}欄位"
                            print(f"      💰 從{field}欄位取得：{budget_amount}")
                            break

            # 更新或新增預算金額欄位
            if budget_amount:
                detail_basic["預算金額"] = budget_amount
                detail_basic["預算金額來源"] = budget_source
                print(f"      ✅ 預算金額來源：{budget_source}")
            else:
                print(f"      ⚠️ 未找到任何預算金額資訊")

            return {
                "detail_url": detail_url,
                "detail_basic": detail_basic,
                "detail_description": description,
                "attachments": attachments,
            }

        except Exception as exc:
            print(f"      ❌ 解析詳細頁面失敗：{exc}")
            return {"detail_url": detail_url, "detail_error": str(exc)}

        finally:
            # 無論成功或失敗，都要返回列表頁面
            try:
                print(f"      🔙 返回列表頁面")
                # 使用 back() 返回上一頁，而不是直接訪問 URL
                self.driver.back()

                # 等待頁面載入完成
                self.wait.until(lambda d: "tpRead" in d.current_url or "readTpRead" in d.current_url)

                # 確保表格存在
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#tpRead tbody tr")))

                print(f"      ✅ 成功返回列表頁面")
            except Exception as e:
                print(f"      ⚠️ 返回列表頁面失敗：{e}")
                # 如果返回失敗，嘗試重新載入列表頁面
                try:
                    print(f"      🔄 嘗試重新載入列表頁面")
                    # 重新執行查詢來恢復列表頁面
                    self._trigger_search()
                    print(f"      ✅ 重新載入列表頁面成功")
                except Exception as e2:
                    print(f"      ❌ 重新載入列表頁面也失敗：{e2}")

    @staticmethod
    def _parse_basic_detail_table(soup: BeautifulSoup) -> dict:
        detail_info: dict[str, str] = {}

        # 首先嘗試找到 printRange 區域（如果存在）
        print_range = soup.find("div", id="printRange")
        if print_range:
            print("      📋 發現 printRange 區域，使用優先解析")
            tables = print_range.find_all("table")
        else:
            print("      📋 未發現 printRange 區域，使用全頁面表格解析")
            tables = soup.find_all("table")

        # 解析所有表格
        for table_idx, table in enumerate(tables):
            print(f"      📊 解析第 {table_idx + 1} 個表格")

            for row_idx, tr in enumerate(table.find_all("tr")):
                cells = tr.find_all("td")
                if len(cells) >= 2:
                    # 取得標籤和值
                    label_cell = cells[0]
                    value_cell = cells[1]

                    # 處理標籤
                    label = label_cell.get_text(strip=True)
                    if not label:
                        # 嘗試從其他元素取得標籤
                        label_elem = label_cell.find(["span", "strong", "b", "label"])
                        if label_elem:
                            label = label_elem.get_text(strip=True)

                    # 處理值
                    value = value_cell.get_text("\n", strip=True)

                    # 如果標籤存在，儲存資訊
                    if label:
                        detail_info[label] = value
                        print(f"        ✓ {label}: {value[:50]}{'...' if len(value) > 50 else ''}")

        # 如果沒有找到任何資訊，嘗試其他解析方式
        if not detail_info:
            print("      ⚠️ 表格解析未找到資訊，嘗試其他解析方式")

            # 嘗試查找所有包含關鍵字的元素
            keywords = ["金額", "預算", "契約", "採購", "標案", "機關", "聯絡"]
            for keyword in keywords:
                elements = soup.find_all(text=lambda text: text and keyword in text.strip())
                for elem in elements:
                    parent = elem.parent
                    if parent and parent.name in ["td", "div", "span"]:
                        text = parent.get_text(strip=True)
                        if text and len(text) > len(keyword):
                            detail_info[f"包含{keyword}的欄位"] = text
                            print(f"        ✓ 包含{keyword}: {text[:50]}{'...' if len(text) > 50 else ''}")

        print(f"      📊 總共解析到 {len(detail_info)} 個欄位")
        return detail_info

    def _parse_attachment_table(self, soup: BeautifulSoup, detail_url: str) -> list[dict]:
        attachments: list[dict] = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            if not headers:
                continue
            if "檔案名稱" in headers and "下載" in headers:
                for tr in table.find_all("tr")[1:]:
                    cells = tr.find_all("td")
                    if len(cells) < 4:
                        continue
                    name = cells[1].get_text(strip=True)
                    size = cells[2].get_text(strip=True)
                    link = cells[3].find("a")
                    href = link["href"] if link and link.has_attr("href") else None
                    if not name:
                        continue
                    attachments.append(
                        {
                            "name": name,
                            "size": size,
                            "url": urljoin(detail_url, href) if href else None,
                        }
                    )
                break
        return attachments

    # ------------------------------------------------------------------ #
    # 輔助工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_link_from_cell(cell) -> str | None:
        try:
            link = cell.find_element(By.TAG_NAME, "a")
            href = link.get_attribute("href")
            if href and not href.lower().startswith("javascript"):
                return urljoin(PublicReadScraper.BASE_URL, href)
        except NoSuchElementException:
            return None
        return None

    @staticmethod
    def _parse_period(period_text: str) -> tuple[str | None, str | None]:
        if not period_text:
            return None, None
        normalized = period_text.replace("－", "-").replace("─", "-").replace("~", "-")
        normalized = re.sub(r"\s+", "", normalized)
        parts = re.split(r"[-至]+", normalized)
        if len(parts) >= 2:
            return parts[0] or None, parts[1] or None
        return normalized or None, None

    @staticmethod
    def _extract_budget_from_description(description: str) -> str | None:
        """從附加說明中提取預算金額"""
        import re

        # 匹配 [預算金額]: XXX元 或類似格式
        patterns = [
            r'\[預算金額\]:\s*([^\[\]\n]+)',
            r'預算金額[：:]\s*([^\n\r]+)',
            r'\[預算金額\]([^(]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                budget = match.group(1).strip()
                # 清理常見的後綴和括號內容
                # 先移除包含"元"的括號內容
                budget = re.sub(r'\([^)]*元[^)]*\)', '', budget)
                budget = re.sub(r'（[^）]*元[^）]*）', '', budget)
                # 再移除其他括號內容
                budget = re.sub(r'\([^)]*\)', '', budget)
                budget = re.sub(r'（[^）]*）', '', budget)
                # 移除結尾的"元"和空白
                budget = re.sub(r'元?\s*$', '', budget)
                return budget.strip()

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
    print("🏢 公開閱覽標案自動化爬蟲")
    print("    會自動切換至「公開閱覽」並持續翻頁直到結束")
    print("=" * 70 + "\n")

    scraper = PublicReadScraper(headless=False)
    keywords = None  # 例如：["資訊", "電腦"]
    records: list[dict] = []
    run_result: dict[str, Any] = {}

    try:
        scraper.setup_driver()
        records = scraper.scrape_public_read(keywords=keywords, max_pages=None)
        run_result = _build_public_read_payload(records, keywords=keywords)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = f"public_read_{timestamp}.json"

        scraper.save_to_json(run_result, json_filename)

        print("\n" + "=" * 70)
        print("📊 擷取統計")
        print("=" * 70)
        print(f"  筆數：{run_result.get('totalRecords', 0)}")
        unique_agencies = {item.get("agency") for item in records if item.get("agency")}
        print(f"  機關數：{len(unique_agencies)}")
        print("=" * 70 + "\n")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"\n✗ 執行失敗：{exc}")
    finally:
        scraper.close_driver()
        if records:
            print("輸出檔案已完成，請於專案目錄檢視。")
        else:
            print("未產生任何資料檔案。")


def _build_public_read_payload(
    records: List[Dict[str, Any]],
    *,
    keywords: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_mode: str = "isNow"
) -> Dict[str, Any]:
    """統一輸出格式，與促參爬蟲保持一致的外層結構"""
    timestamp = datetime.now()
    unique_agencies = {item.get("agency") for item in records if item.get("agency")}
    return {
        "crawlerId": "public-read",
        "runAt": timestamp.isoformat(),
        "filters": {
            "keywords": keywords or [],
            "dateMode": date_mode,
            "startDate": start_date,
            "endDate": end_date,
        },
        "stats": {
            "totalRecords": len(records),
            "totalAgencies": len(unique_agencies),
        },
        "totalRecords": len(records),
        "data": records,
    }


def run_public_read(
    *,
    headless: bool = True,
    keywords: Optional[List[str]] = None,
    max_pages: Optional[int] = None,
    date_mode: str = "isNow",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    output_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    供外部呼叫的封裝函式，便於整合與自動化。

    :return: dict，包含統計資訊與資料列表
    """
    scraper = PublicReadScraper(headless=headless)
    try:
        scraper.setup_driver()
        records = scraper.scrape_public_read(
            start_date=start_date,
            end_date=end_date,
            date_mode=date_mode,
            keywords=keywords,
            max_pages=max_pages,
        )
        result = _build_public_read_payload(
            records,
            keywords=keywords,
            start_date=start_date,
            end_date=end_date,
            date_mode=date_mode,
        )

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = output_dir / f"public_read_{datetime.now():%Y%m%d_%H%M%S}.json"
            PublicReadScraper.save_to_json(result, str(filename))

        return result
    finally:
        scraper.close_driver()


if __name__ == "__main__":
    main()


