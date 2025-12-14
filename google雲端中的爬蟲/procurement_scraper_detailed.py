#相關依賴
#pip install -U pip
#pip install selenium webdriver-manager

"""
政府标案资讯收集系统 - 詳細版（點進詳情頁抓取完整資訊）
會點進每筆案件的詳情頁，取得真正的網址和更多資訊
"""

import time
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

class ProcurementScraperDetailed:
    def __init__(self, headless=False):
        self.headless = headless
        self.driver = None
        self.wait = None
        # 記住目前正在抓的列表頁網址（公告中 / 已登載）
        self.current_list_url = None
        
    def setup_driver(self):
        """设定 Chrome WebDriver"""
        print("正在初始化 Chrome WebDriver...")
        
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, 10)  # 減少等待時間從20秒到10秒
        
        print("✓ Chrome WebDriver 初始化完成")
        
    def close_driver(self):
        if self.driver:
            self.driver.quit()
            print("✓ 浏览器已关闭")
    
    def find_data_table(self):
        """寻找促参平台的资料表格"""
        try:
            # 優先使用更具體的選擇器
            try:
                # 嘗試使用固定的上層 div ID
                container = self.driver.find_element(By.ID, "ContentPlaceHolder1_ListView1")
                table = container.find_element(By.CSS_SELECTOR, "table.table-rwd")
                # 驗證表頭是否包含預期的欄位
                headers = table.find_elements(By.TAG_NAME, "th")
                header_texts = [h.text.strip() for h in headers]
                if any(keyword in "".join(header_texts) for keyword in ["案件名稱", "公告機關", "案件編號"]):
                    return table
            except:
                pass
            
            # 備用方案：遍歷所有表格並驗證表頭
            tables = self.driver.find_elements(By.TAG_NAME, 'table')
            for table in tables:
                table_class = table.get_attribute('class')
                if 'table-rwd' in str(table_class):
                    # 加一層判斷：檢查表頭文字
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

    def get_detail_url_from_row(self, row_index: int) -> str:
        """
        從目前列表頁指定列，使用新分頁開啟詳情頁取得官方深連結。
        主頁面保持在原位置，不需要重新翻頁。
        """
        list_url = self.current_list_url or self.driver.current_url

        table = self.find_data_table()
        if not table:
            return list_url

        rows = table.find_elements(By.TAG_NAME, "tr")
        if row_index >= len(rows):
            return list_url

        row = rows[row_index]

        try:
            link_elem = row.find_element(By.TAG_NAME, "a")
        except NoSuchElementException:
            return list_url

        # 從連結元素提取URL
        try:
            detail_page_url = link_elem.get_attribute("href")
            if not detail_page_url:
                print(f"    ❌ 連結元素沒有 href 屬性")
                return list_url

            # 確保是完整的URL
            if not detail_page_url.startswith('http'):
                detail_page_url = urljoin("https://ppp.mof.gov.tw/WWW/", detail_page_url)

        except Exception as e:
            print(f"    ❌ 取得連結URL失敗: {str(e)}")
            return list_url

        # 使用新分頁取得詳情頁URL
        original_window = self.driver.current_window_handle
        detail_url = list_url  # 預設值

        try:
            # 開啟新分頁
            self.driver.execute_script("window.open('', '_blank');")
            self.wait.until(lambda d: len(d.window_handles) > 1)
            windows = self.driver.window_handles
            new_window = windows[-1]  # 最新的分頁

            # 切換到新分頁
            self.driver.switch_to.window(new_window)

            # 在新分頁中訪問詳情頁
            self.driver.get(detail_page_url)

            # 等待頁面載入完成
            self.wait.until(lambda d: d.find_element(By.TAG_NAME, "body"))

            # 取得最終URL（可能有重新導向）
            detail_url = self.driver.current_url

            # 檢查是否已經在正確的詳情頁面
            try:
                # 檢查是否包含案件名稱或其他標識，確認這是詳情頁面
                case_title_elem = self.driver.find_element(By.XPATH, "//td[contains(text(), '案件名稱')]/following-sibling::td")
                if case_title_elem and case_title_elem.text.strip():
                    # 如果已經在詳情頁面，直接使用當前 URL 作為專屬連結
                    print(f"    ✓ 已進入詳情頁面，使用當前 URL 作為專屬連結: {detail_url}")
                else:
                    # 如果不在詳情頁面，嘗試尋找 oid 或構造 URL
                    if "oid=" not in detail_url:
                        html = self.driver.page_source
                        # 優先嘗試從 HTML 中搜尋 oid 模式
                        m = re.search(r"(inv_(?:ann|case)\.aspx\?oid=[0-9A-F]+)", html, re.I)
                        if m:
                            detail_url = urljoin("https://ppp.mof.gov.tw/WWW/", m.group(1))
                            print(f"    ✓ 從 HTML 找到 oid 連結: {detail_url}")
                        else:
                            # 如果找不到 oid，嘗試從案件編號構造 URL
                            try:
                                case_number_elem = self.driver.find_element(By.XPATH, "//td[contains(text(), '已簽約案號') or contains(text(), '案號')]/following-sibling::td")
                                case_number = case_number_elem.text.strip()
                                if case_number and case_number != "":
                                    # 構造 URL（嘗試不同的參數名稱）
                                    detail_url = f"https://ppp.mof.gov.tw/WWW/inv_case.aspx?case_no={case_number}"
                                    print(f"    構造案件專屬連結: {detail_url}")
                                else:
                                    print(f"    無法取得專屬連結，使用當前頁面: {detail_url}")
                            except:
                                print(f"    無法取得專屬連結，使用當前頁面: {detail_url}")
            except:
                # 如果檢查失敗，使用當前 URL
                print(f"    詳情頁面檢查失敗，使用當前 URL: {detail_url}")

        except Exception as e:
            print(f"    ❌ 新分頁處理失敗: {str(e)}")
            detail_url = list_url

        finally:
            # 關閉新分頁並切回主分頁
            try:
                if len(self.driver.window_handles) > 1:
                    self.driver.close()  # 關閉當前分頁（新分頁）
            except Exception as e:
                print(f"    ⚠️ 關閉新分頁失敗: {str(e)}")

            # 切回主分頁
            try:
                self.driver.switch_to.window(original_window)
            except Exception as e:
                print(f"    ⚠️ 切回主分頁失敗: {str(e)}")

        return detail_url

    def get_page_type(self) -> str:
        """判斷當前詳情頁面類型（公告中/已登載）"""
        try:
            current_url = self.driver.current_url
            if 'inv_ann.aspx' in current_url:
                return 'announce'  # 公告中
            elif 'inv_case.aspx' in current_url:
                return 'registered'  # 已登載
            else:
                # 嘗試從頁面內容判斷
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                if '公告' in page_text and '截止' in page_text:
                    return 'announce'
                elif '已登載' in page_text or '簽約' in page_text:
                    return 'registered'
        except:
            pass
        return 'unknown'

    def get_direct_link_from_copy_button(self) -> str:
        """
        點擊'複製連結'按鈕並嘗試獲取正確的直連連結
        專注於公告中頁面的直連連結獲取
        """
        direct_link = ""
        try:
            # 尋找複製連結按鈕
            copy_button_selectors = [
                "//button[contains(text(), '複製連結')]",
                "//button[contains(@onclick, 'copy')]",
                "/html/body/form/div[4]/div/div/div[2]/div[9]/button",  # 從用戶提供的 xpath
                "//div[contains(@class, 'pro-met')]//button"  # 更通用的選擇器
            ]

            copy_button = None
            for selector in copy_button_selectors:
                try:
                    copy_button = self.driver.find_element(By.XPATH, selector)
                    if copy_button and copy_button.is_displayed():
                        print(f"    📍 找到複製連結按鈕: {selector}")
                        break
                except:
                    continue

            if copy_button:
                # 檢查按鈕的 onclick 屬性，了解複製邏輯
                onclick_attr = copy_button.get_attribute("onclick") or ""
                print(f"    📋 按鈕 onclick 屬性: {onclick_attr[:100]}...")

                # 記錄點擊前的 URL
                url_before_click = self.driver.current_url
                print(f"    🔗 點擊前 URL: {url_before_click}")

                    # 點擊前先詳細檢查按鈕屬性
                print(f"    📋 按鈕詳細資訊: tag={copy_button.tag_name}, type={copy_button.get_attribute('type')}")
                print(f"    📋 按鈕onclick: {onclick_attr[:200]}...")

                # 檢查是否能通過 JavaScript 直接執行 onclick 程式碼
                if onclick_attr:
                    try:
                        print("    🔬 嘗試分析 onclick 程式碼...")
                        # 移除 onclick=" 包裝
                        js_code = onclick_attr.strip()
                        if js_code.startswith('onclick="'):
                            js_code = js_code[9:]
                        if js_code.endswith('"'):
                            js_code = js_code[:-1]

                        print(f"    📝 提取的 JS 程式碼: {js_code[:100]}...")

                        # 檢查是否包含常見的複製函數
                        if 'copyToClipboard' in js_code or 'clipboard' in js_code.lower():
                            print("    🎯 檢測到剪貼簿操作，準備深入分析...")
                    except Exception as e:
                        print(f"    ⚠️ 分析 onclick 程式碼失敗: {e}")

                # 對於公告中頁面，注入更全面的攔截腳本
                page_type = self.get_page_type()
                if page_type == 'announce':
                    try:
                        # 注入全面的 JavaScript 攔截腳本
                        intercept_script = """
                        // 攔截 clipboard API
                        var copiedText = '';
                        var originalWriteText = navigator.clipboard.writeText;
                        navigator.clipboard.writeText = function(text) {
                            copiedText = text;
                            console.log('Clipboard API - 複製內容:', text);
                            window.copiedText = text;
                            return originalWriteText.call(this, text);
                        };

                        // 攔截 document.execCommand
                        var originalExecCommand = document.execCommand;
                        document.execCommand = function(command, showUI, value) {
                            if (command === 'copy') {
                                console.log('execCommand copy - 值:', value);
                                window.execCommandValue = value;
                            }
                            return originalExecCommand.call(this, command, showUI, value);
                        };

                        // 監聽 alert
                        var originalAlert = window.alert;
                        window.alert = function(message) {
                            console.log('Alert 訊息:', message);
                            window.alertMessage = message;
                            return originalAlert.call(this, message);
                        };

                        // 提供取得複製內容的函數
                        window.getCopiedText = function() {
                            return copiedText || window.copiedText || window.execCommandValue || window.alertMessage || '';
                        };

                        // 監聽頁面變化
                        window.beforeClickUrl = window.location.href;
                        """
                        self.driver.execute_script(intercept_script)
                        print("    🛡️ 已注入全面攔截腳本")
                    except Exception as e:
                        print(f"    ⚠️ 注入攔截腳本失敗: {e}")

                # 點擊複製連結按鈕
                copy_button.click()
                print("    ✓ 已點擊複製連結按鈕")

                # 等待一下，讓複製操作完成
                import time
                time.sleep(0.8)  # 稍微延長等待時間

                # 檢查點擊後的各種變化
                try:
                    # 檢查 URL 是否變化
                    url_after_click = self.driver.current_url
                    print(f"    🔗 點擊後 URL: {url_after_click}")

                    # 檢查是否有 alert 出現
                    try:
                        alert = self.driver.switch_to.alert
                        alert_text = alert.text
                        print(f"    🚨 檢測到 Alert: {alert_text}")
                        if 'http' in alert_text:
                            direct_link = alert_text
                            alert.accept()
                            print(f"    ✓ 從 Alert 獲取連結: {direct_link}")
                            return direct_link
                    except:
                        pass

                    # 檢查攔截到的內容
                    if page_type == 'announce':
                        try:
                            copied_text = self.driver.execute_script("return window.getCopiedText();")
                            print(f"    📋 攔截到的內容: '{copied_text}'")
                            if copied_text and copied_text.strip():
                                # 處理複製的內容，即使沒有 http 開頭
                                if copied_text.startswith('http'):
                                    direct_link = copied_text
                                elif copied_text.startswith('//'):
                                    direct_link = 'https:' + copied_text
                                elif copied_text.startswith('ppp.mof.gov.tw'):
                                    direct_link = 'https://' + copied_text
                                elif 'inv_ann.aspx?oid=' in copied_text or 'inv_case.aspx?oid=' in copied_text:
                                    # 如果是相對路徑，添加完整 URL
                                    if not copied_text.startswith('http'):
                                        direct_link = urljoin("https://ppp.mof.gov.tw/WWW/", copied_text)
                                    else:
                                        direct_link = copied_text
                                else:
                                    # 其他情況，嘗試添加 https 協議
                                    direct_link = 'https://' + copied_text if not copied_text.startswith('http') else copied_text

                                print(f"    ✓ 從攔截內容獲取連結: {direct_link}")
                                return direct_link
                        except Exception as e:
                            print(f"    ⚠️ 檢查攔截內容失敗: {e}")

                        # 檢查是否有新元素出現（比如臨時顯示連結的元素）
                        try:
                            # 搜尋所有可能顯示連結的元素
                            link_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'http') or contains(@value, 'http')]")
                            for elem in link_elements:
                                text_content = elem.text
                                value_content = elem.get_attribute("value") or ""
                                if ('inv_ann.aspx?oid=' in text_content or 'inv_ann.aspx?oid=' in value_content):
                                    direct_link = text_content if 'http' in text_content else value_content
                                    if not direct_link.startswith('http'):
                                        direct_link = urljoin("https://ppp.mof.gov.tw/WWW/", direct_link)
                                    print(f"    ✓ 從頁面元素找到連結: {direct_link}")
                                    return direct_link
                        except Exception as e:
                            print(f"    ⚠️ 檢查頁面元素失敗: {e}")

                except Exception as e:
                    print(f"    ⚠️ 檢查點擊後變化失敗: {e}")

                # 等待一下讓頁面更新
                import time
                time.sleep(0.8)  # 稍微增加等待時間

                # 檢查是否有 alert 彈出
                try:
                    alert = self.driver.switch_to.alert
                    alert_text = alert.text
                    if 'http' in alert_text:
                        direct_link = alert_text
                        alert.accept()
                        print(f"    ✓ 從 alert 獲取連結: {direct_link}")
                        return direct_link
                except:
                    pass

                # 檢查 URL 是否有變化
                url_after_click = self.driver.current_url
                print(f"    🔗 點擊後 URL: {url_after_click}")
                if url_after_click != url_before_click and 'oid=' in url_after_click:
                    direct_link = url_after_click
                    print(f"    ✓ URL 變化，獲取新連結: {direct_link}")
                    return direct_link

                # 檢查是否有臨時顯示的 input 或 textarea 包含連結
                try:
                    input_elements = self.driver.find_elements(By.XPATH, "//input[@type='text'][@value!=''] | //textarea[@value!='']")
                    for elem in input_elements:
                        if elem.is_displayed():
                            value = elem.get_attribute("value") or ""
                            print(f"    📝 檢查 input 值: {value[:100]}...")
                            if 'http' in value and ('inv_ann.aspx?oid=' in value or 'inv_case.aspx?oid=' in value):
                                direct_link = value
                                print(f"    ✓ 從 input 元素獲取連結: {direct_link}")
                                return direct_link
                except Exception as e:
                    print(f"    ⚠️ 檢查 input 元素時出錯: {e}")

                # 檢查頁面上是否有新出現的連結元素
                try:
                    link_elements = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'inv_ann.aspx?oid=') or contains(@href, 'inv_case.aspx?oid=')]")
                    for elem in link_elements:
                        href = elem.get_attribute("href")
                        if href and href != url_before_click:
                            direct_link = href
                            print(f"    ✓ 找到新的直連連結: {direct_link}")
                            return direct_link
                except Exception as e:
                    print(f"    ⚠️ 檢查連結元素時出錯: {e}")

                # 檢查頁面源碼中是否有直連連結
                try:
                    page_source = self.driver.page_source
                    import re

                    # 尋找可能的直連連結模式
                    oid_patterns = [
                        r'inv_ann\.aspx\?oid=[A-F0-9]+',
                        r'inv_case\.aspx\?oid=[A-F0-9]+',
                        r'https?://ppp\.mof\.gov\.tw/WWW/(?:inv_ann|inv_case)\.aspx\?oid=[A-F0-9]+'
                    ]

                    for pattern in oid_patterns:
                        matches = re.findall(pattern, page_source, re.IGNORECASE)
                        for match in matches:
                            if not match.startswith('http'):
                                match = urljoin("https://ppp.mof.gov.tw/WWW/", match)
                            if match != url_before_click:
                                direct_link = match
                                print(f"    ✓ 從頁面源碼找到直連連結: {direct_link}")
                                return direct_link
                except Exception as e:
                    print(f"    ⚠️ 檢查頁面源碼時出錯: {e}")

                # 對於公告中頁面，嘗試從 JavaScript 獲取連結
                page_type = self.get_page_type()
                if page_type == 'announce':
                    try:
                        # 嘗試執行按鈕的 onclick 程式碼，並從中提取連結
                        if onclick_attr:
                            print(f"    🔍 分析 onclick 程式碼以獲取連結...")

                            # 常見的複製連結 JavaScript 模式
                            import re

                            # 尋找 URL 生成模式
                            url_patterns = [
                                r"location\.href\s*=\s*['\"]([^'\"]+)['\"]",
                                r"window\.location\s*=\s*['\"]([^'\"]+)['\"]",
                                r"['\"](https?://[^'\"]+)['\"]",
                                r"copyToClipboard\(['\"]([^'\"]+)['\"]\)",
                                r"navigator\.clipboard\.writeText\(['\"]([^'\"]+)['\"]\)"
                            ]

                            for pattern in url_patterns:
                                matches = re.findall(pattern, onclick_attr, re.IGNORECASE)
                                for match in matches:
                                    if 'inv_ann.aspx?oid=' in match or 'inv_case.aspx?oid=' in match:
                                        if not match.startswith('http'):
                                            match = urljoin("https://ppp.mof.gov.tw/WWW/", match)
                                        direct_link = match
                                        print(f"    ✓ 從 onclick 程式碼提取連結: {direct_link}")
                                        return direct_link

                    except Exception as e:
                        print(f"    ⚠️ 分析 onclick 程式碼失敗: {e}")

                    # 如果當前 URL 包含 oid 參數，則直接使用
                    current_url = self.driver.current_url
                    if 'oid=' in current_url and 'inv_ann.aspx' in current_url:
                        direct_link = current_url
                        print(f"    ✓ 公告中頁面的當前 URL 作為直連連結: {direct_link}")
                        return direct_link

                print("    ⚠️ 無法從複製按鈕獲取直連連結")

        except Exception as e:
            print(f"    ❌ 獲取直連連結失敗: {str(e)}")
            import traceback
            traceback.print_exc()

        return direct_link

    def click_back_button(self) -> bool:
        """
        點擊返回按鈕回到列表頁
        通用方法：動態搜尋所有可能的返回按鈕，不依賴特定ID
        """
        try:
            page_type = self.get_page_type()
            print(f"    🔍 當前頁面類型: {page_type}")

            back_button = None
            selected_info = ""

            # 第一步：搜尋所有可能的 btnBack 系列按鈕（動態ID）
            print("    🔍 搜尋所有 btnBack 系列按鈕...")
            try:
                # 搜尋所有 id 包含 btnBack 的輸入元素
                all_btnback_inputs = self.driver.find_elements(By.XPATH, "//input[contains(@id, 'btnBack')]")
                for btn in all_btnback_inputs:
                    btn_id = btn.get_attribute("id") or ""
                    if btn.is_displayed() and btn.is_enabled():
                        back_button = btn
                        selected_info = f"btnBack系列 - ID:{btn_id}"
                        print(f"    📍 找到 btnBack 按鈕: {btn_id}")
                        break
            except Exception as e:
                print(f"    ⚠️ 搜尋 btnBack 按鈕失敗: {e}")

            # 第二步：如果沒找到，搜尋所有包含返回相關文字的按鈕
            if not back_button:
                print("    🔍 搜尋包含返回文字的按鈕...")
                try:
                    # 搜尋所有 input 按鈕
                    all_inputs = self.driver.find_elements(By.XPATH, "//input[@type='submit' or @type='button']")
                    for btn in all_inputs:
                        btn_value = btn.get_attribute("value") or ""
                        btn_id = btn.get_attribute("id") or ""
                        if ("返回" in btn_value or
                            "回上頁" in btn_value or
                            "上一頁" in btn_value or
                            "back" in btn_value.lower()):
                            if btn.is_displayed() and btn.is_enabled():
                                back_button = btn
                                selected_info = f"文字匹配輸入按鈕 - ID:{btn_id}, 值:{btn_value}"
                                print(f"    📍 找到文字匹配返回按鈕: {btn_value}")
                                break
                except Exception as e:
                    print(f"    ⚠️ 搜尋文字匹配按鈕失敗: {e}")

            # 第三步：如果還是沒找到，搜尋所有連結
            if not back_button:
                print("    🔍 搜尋包含返回文字的連結...")
                try:
                    all_links = self.driver.find_elements(By.XPATH, "//a")
                    for link in all_links:
                        link_text = link.text.strip()
                        link_href = link.get_attribute("href") or ""
                        if ("返回" in link_text or
                            "回上頁" in link_text or
                            "上一頁" in link_text or
                            "back" in link_href.lower()):
                            if link.is_displayed() and link.is_enabled():
                                back_button = link
                                selected_info = f"文字匹配連結 - 文字:{link_text}"
                                print(f"    📍 找到文字匹配返回連結: {link_text}")
                                break
                except Exception as e:
                    print(f"    ⚠️ 搜尋文字匹配連結失敗: {e}")

            # 第四步：如果還是沒找到，搜尋所有可能的導航相關元素
            if not back_button:
                print("    🔍 搜尋其他可能的導航元素...")
                try:
                    # 搜尋所有可能的按鈕和連結
                    all_clickable = self.driver.find_elements(By.XPATH, "//input[@type='submit' or @type='button'] | //a | //button")
                    for elem in all_clickable:
                        elem_text = elem.text.strip()
                        elem_value = elem.get_attribute("value") or ""
                        elem_id = elem.get_attribute("id") or ""
                        elem_class = elem.get_attribute("class") or ""

                        # 檢查各種可能的返回指示
                        is_back_button = (
                            "返回" in elem_text or "返回" in elem_value or
                            "回上頁" in elem_text or "回上頁" in elem_value or
                            "上一頁" in elem_text or "上一頁" in elem_value or
                            "back" in elem_id.lower() or "back" in elem_class.lower() or
                            "btnBack" in elem_id
                        )

                        if is_back_button and elem.is_displayed() and elem.is_enabled():
                            back_button = elem
                            selected_info = f"通用匹配 - 類型:{elem.tag_name}, ID:{elem_id}, 文字:{elem_text or elem_value}"
                            print(f"    📍 找到通用匹配返回元素: {elem.tag_name} - {elem_text or elem_value}")
                            break
                except Exception as e:
                    print(f"    ⚠️ 搜尋通用導航元素失敗: {e}")

            # 第五步：最終備用方案 - 瀏覽器返回功能
            if not back_button:
                print("    ❌ 找不到任何返回按鈕，嘗試使用瀏覽器返回功能...")
                try:
                    self.driver.back()
                    print("    ✓ 使用瀏覽器返回功能回到上一頁")
                    return True
                except Exception as e:
                    print(f"    ❌ 瀏覽器返回功能也失敗: {e}")

                    # 提供調試資訊
                    try:
                        current_url = self.driver.current_url
                        print(f"    🔗 當前 URL: {current_url}")

                        # 分析頁面上的所有可點擊元素
                        all_clickable = self.driver.find_elements(By.XPATH, "//input[@type='submit'] | //button | //a")
                        clickable_info = []
                        for elem in all_clickable[:10]:  # 只顯示前10個
                            elem_text = elem.text.strip()
                            elem_value = elem.get_attribute("value") or ""
                            elem_id = elem.get_attribute("id") or ""
                            if elem_text or elem_value or elem_id:
                                clickable_info.append(f"{elem.tag_name}[{elem_id}]: '{elem_text or elem_value}'")

                        if clickable_info:
                            print(f"    📋 頁面上找到的可點擊元素: {clickable_info}")
                    except Exception as debug_e:
                        print(f"    ⚠️ 無法獲取調試資訊: {debug_e}")

                    return False

            # 點擊找到的返回按鈕
            try:
                back_button.click()
                print(f"    ✓ 已點擊返回按鈕 ({page_type}) - {selected_info}")
                return True
            except Exception as click_e:
                print(f"    ❌ 點擊返回按鈕失敗: {click_e}")
                return False

        except Exception as e:
            print(f"    ❌ 返回按鈕處理過程出錯: {str(e)}")
            return False

    def extract_detail_info(self) -> Dict[str, str]:
        """
        從詳情頁快速抓取額外資訊（預算、案號等）
        優化版本：減少不必要的等待和輸出
        """
        detail_info = {
            'detailCaseNumber': '',
            'budget': '',
            'budgetAmount': None
        }

        try:
            # 快速搜尋預算資訊（優先順序）
            budget_selectors = [
                "//td[contains(text(), '民間投資金額')]/following-sibling::td",
                "//td[contains(text(), '預算')]/following-sibling::td",
                "//td[contains(text(), '金額')]/following-sibling::td"
            ]

            for selector in budget_selectors:
                try:
                    budget_elem = self.driver.find_element(By.XPATH, selector)
                    budget_text = budget_elem.text.strip()
                    if budget_text and budget_text != "":
                        detail_info['budget'] = budget_text
                        break
                except:
                    continue

            # 如果沒找到，嘗試從頁面文字中搜尋
            if not detail_info['budget']:
                try:
                    page_text = self.driver.find_element(By.TAG_NAME, "body").text
                    amount_pattern = r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*元'
                    match = re.search(amount_pattern, page_text)
                    if match:
                        detail_info['budget'] = match.group(1) + "元"
                except:
                    pass

            # 解析金額數字
            if detail_info['budget']:
                try:
                    budget_number = re.sub(r'[^\d.]', '', detail_info['budget'])
                    if budget_number:
                        detail_info['budgetAmount'] = float(budget_number)
                except:
                    pass

            # 搜尋案號
            case_number_selectors = [
                "//td[contains(text(), '已簽約案號')]/following-sibling::td",
                "//td[contains(text(), '標案案號')]/following-sibling::td",
                "//td[contains(text(), '案號')]/following-sibling::td"
            ]

            for selector in case_number_selectors:
                try:
                    case_elem = self.driver.find_element(By.XPATH, selector)
                    case_text = case_elem.text.strip()
                    if case_text and case_text != "":
                        detail_info['detailCaseNumber'] = case_text
                        break
                except:
                    continue

        except Exception as e:
            # 如果發生錯誤，靜默處理，不影響主要流程
            pass

        return detail_info

    def get_detail_url_and_info_from_row(self, row_index: int, current_page: int = 1) -> tuple:
        """
        從目前列表頁指定列取得詳情資訊。
        使用優化的頁面切換方式：點擊連結進入詳情頁，抓取資訊和直連連結，然後點擊返回按鈕回到原頁面。
        """
        list_url = self.current_list_url or self.driver.current_url
        detail_info = {}
        detail_url = list_url  # 預設值

        table = self.find_data_table()
        if not table:
            return list_url, detail_info

        rows = table.find_elements(By.TAG_NAME, "tr")
        if row_index >= len(rows):
            return list_url, detail_info

        row = rows[row_index]

        try:
            link_elem = row.find_element(By.TAG_NAME, "a")
        except NoSuchElementException:
            return list_url, detail_info

        # 從連結元素提取URL
        try:
            detail_page_url = link_elem.get_attribute("href")
            if not detail_page_url:
                return list_url, detail_info

            # 確保是完整的URL
            if not detail_page_url.startswith('http'):
                detail_page_url = urljoin("https://ppp.mof.gov.tw/WWW/", detail_page_url)

        except Exception as e:
            return list_url, detail_info

        # 使用優化的頁面切換方式：進入詳情頁，抓取資訊，點擊返回按鈕
        try:
            # 點擊連結進入詳情頁
            link_elem.click()

            # 等待頁面載入
            self.wait.until(lambda d: d.find_element(By.TAG_NAME, "body"))

            # 取得詳情頁URL和資訊
            detail_url = self.driver.current_url
            detail_info = self.extract_detail_info()

            # 檢查當前 URL 是否已經是直連連結格式
            page_type = self.get_page_type()
            if page_type == 'announce' and 'inv_ann.aspx?oid=' in detail_url:
                print(f"    ✓ 當前 URL 已是公告中直連連結: {detail_url}")
                # 不需要進一步處理，直接使用當前 URL
            elif page_type == 'registered' and 'inv_case.aspx?oid=' in detail_url:
                print(f"    ✓ 當前 URL 已是已登載直連連結: {detail_url}")
                # 不需要進一步處理，直接使用當前 URL
            else:
                # 嘗試點擊複製連結按鈕獲取正確的直連連結
                direct_link = self.get_direct_link_from_copy_button()
                if direct_link:
                    detail_url = direct_link
                    print(f"    🔄 更新為複製按鈕獲取的連結: {detail_url}")
                else:
                    print(f"    ⚠️ 無法獲取直連連結，使用當前 URL: {detail_url}")

            # 使用返回按鈕回到列表頁
            self.click_back_button()

            # 等待回到列表頁
            self.wait.until(lambda d: self.find_data_table() is not None)

        except Exception as e:
            print(f"    ⚠️ 詳情頁處理失敗: {str(e)}")
            # 如果出錯，嘗試使用返回按鈕或重新載入列表頁
            try:
                self.click_back_button()
                self.wait.until(lambda d: self.find_data_table() is not None)
            except:
                # 如果返回按鈕也失敗，重新載入列表頁
                try:
                    self.driver.get(list_url)
                    self.wait.until(lambda d: self.find_data_table() is not None)
                except:
                    pass
            detail_url = list_url

        return detail_url, detail_info

    def navigate_to_page(self, target_page: int) -> bool:
        """智慧翻頁到指定頁面"""
        try:
            # 檢查當前頁面是否已經是目標頁面
            current_page = self._get_current_page_number()
            if current_page == target_page:
                print(f"    ✅ 已經在第 {target_page} 頁")
                return True

            # 尋找可見的頁面按鈕
            page_buttons = self.driver.find_elements(By.CSS_SELECTOR, "a.imgPage.nuimgPage")
            available_pages = []

            for button in page_buttons:
                try:
                    page_text = button.text.strip()
                    if page_text.isdigit():
                        page_num = int(page_text)
                        available_pages.append((page_num, button))
                except:
                    continue

            print(f"    📄 可見頁面按鈕: {[p for p, _ in available_pages]}")

            # 檢查目標頁面是否在可見範圍內
            for page_num, button in available_pages:
                if page_num == target_page:
                    print(f"    🖱️ 直接點擊第 {target_page} 頁按鈕")
                    button.click()
                    self.wait.until(EC.staleness_of(self.find_data_table()))
                    self.wait.until(lambda d: self.find_data_table() is not None)
                    print(f"    ✅ 已跳到第 {target_page} 頁")
                    return True

            # 如果目標頁面不在可見範圍內，使用逐步翻頁
            print(f"    📄 第 {target_page} 頁不在可見範圍，使用逐步翻頁")
            current_page = self._get_current_page_number()

            if target_page > current_page:
                # 往後翻
                pages_to_flip = target_page - current_page
                for _ in range(pages_to_flip):
                    if not self.has_next_page():
                        print(f"    ❌ 無法繼續翻頁")
                        return False
                    if not self.click_next_page():
                        print(f"    ❌ 翻頁失敗")
                        return False
            else:
                # 往前翻（如果有的話）
                print(f"    ⚠️ 不支援往前翻頁，停留在當前頁面")
                return False

            return True

        except Exception as e:
            print(f"    ❌ 智慧翻頁失敗: {str(e)}")
            return False

    def _get_current_page_number(self) -> int:
        """獲取當前頁碼（盡可能精確）"""
        try:
            # 檢查哪個頁面按鈕有 active 或 current 類別
            page_buttons = self.driver.find_elements(By.CSS_SELECTOR, "a.imgPage.nuimgPage")
            for button in page_buttons:
                classes = button.get_attribute("class") or ""
                if "active" in classes.lower() or "current" in classes.lower():
                    try:
                        return int(button.text.strip())
                    except:
                        continue

            # 如果沒有找到 active 按鈕，檢查 URL 或其他跡象
            # 或者假設在第一頁（因為我們總是從第一頁重新開始）
            return 1

        except:
            return 1

    def has_next_page(self):
        """检查是否有下一页按钮（且可点击）"""
        try:
            # 方法1: 使用正確的 xpath（根據實際網頁結構）
            next_button = self.driver.find_element(By.XPATH, '//*[@id="ContentPlaceHolder1_ListView1_DataPager1"]/input[2]')

            # 检查按钮是否可用（不是 disabled）
            is_enabled = next_button.is_enabled()
            is_displayed = next_button.is_displayed()

            # 检查按钮的 class 是否包含 disabled 相关
            button_class = next_button.get_attribute('class') or ''
            is_disabled_class = 'aspNetDisabled' in button_class or 'disable' in button_class.lower()

            print(f"  檢查下一頁按鈕: 啟用={is_enabled}, 顯示={is_displayed}, 類別='{button_class}', 停用類別={is_disabled_class}")
            return is_enabled and is_displayed and not is_disabled_class

        except Exception as e:
            print(f"  找不到下一頁按鈕: {str(e)}")
            return False
    
    def click_next_page(self):
        """点击下一页按钮，使用显式等待替代 time.sleep"""
        table = self.find_data_table()
        if not table:
            return False

        try:
            # 方法 1: 使用正確的 XPath（優先使用這個）
            next_button = self.driver.find_element(By.XPATH, '//*[@id="ContentPlaceHolder1_ListView1_DataPager1"]/input[2]')
            if next_button and next_button.is_enabled():
                print(f"    🖱️ 點擊下一頁按鈕 (XPath)")
                self.driver.execute_script("arguments[0].click();", next_button)

                # 更強的等待邏輯
                try:
                    # 等待舊表格消失
                    self.wait.until(EC.staleness_of(table))
                    print(f"    ✅ 舊表格已消失")
                except TimeoutException:
                    print(f"    ⚠️ 等待舊表格消失逾時，但繼續")

                # 等待新表格出現，並確認有資料
                try:
                    self.wait.until(lambda d: self.find_data_table() is not None)
                    print(f"    ✅ 新表格已出現")

                    # 額外等待確保資料載入完成
                    import time
                    time.sleep(1)

                    # 檢查新表格是否有不同的資料（簡單檢查）
                    new_table = self.find_data_table()
                    if new_table:
                        new_rows = new_table.find_elements(By.TAG_NAME, 'tr')
                        print(f"    📊 新表格有 {len(new_rows)} 行資料")
                        if len(new_rows) > 1:  # 至少有表頭 + 一筆資料
                            print(f"    ✅ 翻頁成功")
                            return True
                        else:
                            print(f"    ⚠️ 新表格似乎沒有資料")
                            return False
                    else:
                        print(f"    ❌ 新表格不存在")
                        return False

                except TimeoutException:
                    print(f"    ❌ 等待新表格出現逾時")
                    return False
        except Exception as e:
            print(f"    方法 1 失敗: {str(e)}")

        # 如果方法 1 失敗，重新獲取表格引用
        table = self.find_data_table()
        if not table:
            return False

        try:
            # 方法 2: 使用 CSS 選擇器
            next_button = self.driver.find_element(By.CSS_SELECTOR, "input.imgPage.nimgPage[value='>']")
            if next_button and next_button.is_enabled():
                print(f"    🖱️ 點擊下一頁按鈕 (CSS)")
                self.driver.execute_script("arguments[0].click();", next_button)
                self.wait.until(EC.staleness_of(table))
                self.wait.until(lambda d: self.find_data_table() is not None)
                print(f"    ✅ 翻頁成功")
                return True
        except Exception as e:
            print(f"    方法 2 失敗: {str(e)}")

        # 如果方法 2 失敗，重新獲取表格引用
        table = self.find_data_table()
        if not table:
            return False

        try:
            # 方法 3: 使用 value='&gt;' 作為備用
            next_button = self.driver.find_element(By.XPATH, "//input[@value='&gt;' and @type='submit']")
            if next_button and next_button.is_enabled():
                print(f"    🖱️ 點擊下一頁按鈕 (value)")
                self.driver.execute_script("arguments[0].click();", next_button)
                self.wait.until(EC.staleness_of(table))
                self.wait.until(lambda d: self.find_data_table() is not None)
                print(f"    ✅ 翻頁成功")
                return True
        except Exception as e:
            print(f"    方法 3 失敗: {str(e)}")

        print(f"    ❌ 所有翻頁方法都失敗了")
        return False
    
    def get_current_page_number(self):
        """获取当前页码"""
        try:
            page_info = self.driver.find_element(By.XPATH, "//div[contains(text(), '頁數：')]")
            text = page_info.text
            match = re.search(r'頁數：\s*(\d+)/(\d+)', text)
            if match:
                return int(match.group(1)), int(match.group(2))
        except:
            pass
        return None, None
    
    def parse_table_data(self, keywords=None, follow_detail=True, extract_detail=True, current_page=1):
        """
        解析当前页面的表格资料

        :param keywords: 關鍵字過濾
        :param follow_detail: 是否點入詳情頁抓真正網址
        :param extract_detail: 是否從詳情頁抓取額外資訊（預算、案號等）
        """
        data = []

        table = self.find_data_table()
        if not table:
            return data

        # 判斷目前是哪個頁面（公告中 vs 已登載）
        current_url = self.driver.current_url
        is_announce_page = 'inv_ann.aspx' in current_url  # 公告中
        is_registered_page = 'inv_case.aspx' in current_url  # 已登載

        # 先抓一次總列數，迴圈用 index；真正取 row 時會每圈重新抓，避免 back() 之後 element 失效
        rows = table.find_elements(By.TAG_NAME, 'tr')
        row_count = len(rows)
        print(f"  發現 {row_count-1} 筆資料列（包含表頭）")

        # 從 1 開始：0 是表頭
        for row_index in range(1, row_count):
            try:
                # 每一圈重新拿一次最新的 row，避免 StaleElementReference
                table = self.find_data_table()
                if not table:
                    break

                rows = table.find_elements(By.TAG_NAME, 'tr')
                if row_index >= len(rows):
                    break

                row = rows[row_index]
                cols = row.find_elements(By.TAG_NAME, 'td')

                if len(cols) < 5:
                    continue

                # 根據頁面類型使用不同的欄位映射
                if is_announce_page:
                    # 公告中頁面的欄位順序（共8欄）
                    case_number = cols[0].text.strip()  # 案號
                    name = cols[1].text.strip()  # 案件名稱
                    agency = cols[2].text.strip() if len(cols) > 2 else ''  # 主辦機關
                    planning_method = cols[3].text.strip() if len(cols) > 3 else ''  # 規劃方式
                    announcement_type = cols[4].text.strip() if len(cols) > 4 else ''  # 公告類別
                    announcement_count = cols[5].text.strip() if len(cols) > 5 else ''  # 公告次數
                    announcement_start_date = cols[6].text.strip() if len(cols) > 6 else ''  # 公告開始日期
                    announcement_end_date = cols[7].text.strip() if len(cols) > 7 else ''  # 公告截止日期
                    # 設定主要日期為開始日期
                    date = announcement_start_date

                elif is_registered_page:
                    # 已登載頁面的欄位順序（共6欄）
                    name = cols[0].text.strip()  # 案件名稱
                    announcement_type = cols[1].text.strip() if len(cols) > 1 else ''  # 案件類別/狀態
                    agency = cols[2].text.strip() if len(cols) > 2 else ''  # 主辦機關
                    planning_method = cols[3].text.strip() if len(cols) > 3 else ''  # 規劃方式
                    registered_date = cols[4].text.strip() if len(cols) > 4 else ''  # 已登載日期
                    contract_date = cols[5].text.strip() if len(cols) > 5 else ''  # 簽約日期
                    case_number = ''  # 已登載頁面通常沒有明確的案號
                    # 設定主要日期為登載日期
                    date = registered_date

                else:
                    # 預設邏輯（向後兼容）
                    case_number = cols[0].text.strip()
                    name = cols[1].text.strip()
                    agency = cols[2].text.strip() if len(cols) > 2 else ''
                    planning_method = cols[3].text.strip() if len(cols) > 3 else ''
                    announcement_type = cols[4].text.strip() if len(cols) > 4 else ''
                    date = cols[5].text.strip() if len(cols) > 5 else ''
                    # 初始化其他變數
                    announcement_count = ''
                    announcement_start_date = ''
                    announcement_end_date = ''
                    registered_date = ''
                    contract_date = ''

                # 驗證必要欄位（至少要有案件名稱）
                if not name:
                    continue

                # 关键字过滤
                if keywords and not self.match_keywords(name + agency, keywords):
                    continue

                # 預設先給列表頁網址（至少不會是錯的假深連結）
                link = self.current_list_url or self.driver.current_url
                detail_info = {}

                # 如果要精準個案網址（和詳細資訊），就真的點進去拿
                if follow_detail:
                    try:
                        if extract_detail:
                            # 點進去拿 URL + 詳細資訊，傳遞當前頁碼
                            link, detail_info = self.get_detail_url_and_info_from_row(row_index, current_page)
                        else:
                            # 只拿 URL，不抓詳細資訊
                            link = self.get_detail_url_from_row(row_index)
                    except Exception as e:
                        # 失敗就維持列表頁網址
                        print(f"    ⚠ 抓取第 {row_index} 筆詳情失敗: {str(e)}")
                        link = self.current_list_url or self.driver.current_url

                # 建立資料項目，欄位名稱對齊 tender_announcement 格式
                item = {
                    'serial_no': str(row_index),  # 序號
                    'agency': agency,  # 機關名稱
                    'tenderId': case_number,  # 標案編號（案號）
                    'tenderName': name,  # 標案名稱
                    'transmission_count': announcement_count if is_announce_page else '',  # 傳輸次數（公告次數）
                    'tender_method': planning_method,  # 招標方式（規劃方式）
                    'procurement_type': announcement_type,  # 採購類別（公告類別/案件狀態）
                    'announcement_date': date,  # 公告日期
                    'deadline': announcement_end_date if is_announce_page else '',  # 截止日期
                    'budget_amount': '',  # 預算金額（稍後從詳情頁填充）
                    'sourceUrl': link,  # 來源網址
                    'detail_url': link,  # 詳細網址
                    'detail_fetched': True,  # 是否已抓取詳細資料
                }

                # 添加促參特有的欄位
                item['caseNumber'] = case_number  # 保留原有欄位以向後兼容
                item['planningMethod'] = planning_method
                item['announcementType'] = announcement_type

                # 添加公告中頁面的特定欄位（使用不同的欄位名稱避免重複）
                if is_announce_page:
                    item['announcementStartDate'] = announcement_start_date
                    item['announcementEndDate'] = announcement_end_date

                # 添加已登載頁面的特定欄位
                if is_registered_page:
                    item['registeredDate'] = registered_date
                    item['contractDate'] = contract_date

                # 如果有從詳情頁抓到額外資訊，合併進去
                if detail_info:
                    if detail_info.get('detailCaseNumber'):
                        item['detailCaseNumber'] = detail_info['detailCaseNumber']
                        # 如果列表頁沒有案號，用詳情頁的
                        if not item['caseNumber']:
                            item['caseNumber'] = detail_info['detailCaseNumber']
                            item['tenderId'] = detail_info['detailCaseNumber']  # 同時更新 tenderId
                    if detail_info.get('budget'):
                        item['budget'] = detail_info['budget']
                        item['budget_amount'] = detail_info['budget']  # 對齊欄位名稱
                    if detail_info.get('budgetAmount') is not None:
                        item['budgetAmount'] = detail_info['budgetAmount']

                data.append(item)

            except StaleElementReferenceException:
                # DOM 變動導致元素失效，這筆就先略過
                print(f"    ⚠ 第 {row_index} 筆資料失效，略過")
                continue
            except Exception as e:
                print(f"    ⚠ 處理第 {row_index} 筆資料時發生錯誤: {str(e)}")
                continue

        return data
    
    def scrape_with_autopagination(self, url, status_label, keywords=None, 
                                   follow_detail=True, extract_detail=True, max_pages=20):
        """
        自动翻页抓取所有资料
        
        :param url: 列表頁網址
        :param status_label: 狀態標籤（公告中/已登載）
        :param keywords: 關鍵字過濾
        :param follow_detail: 是否點入詳情頁抓真正網址
        :param extract_detail: 是否從詳情頁抓取額外資訊
        :param max_pages: 最大翻頁數
        """
        print("\n" + "="*70)
        print(f"📢 开始抓取促参{status_label}案件（详细版）...")
        if follow_detail:
            print(f"   ⚙️  模式：點入詳情頁抓取完整資訊（手動切換頁面）")
        else:
            print(f"   ⚙️  模式：僅抓取列表頁資訊（快速）")
        print("="*70)

        all_data = []

        try:
            # 記錄這次的列表網址
            self.current_list_url = url

            self.driver.get(url)
            print(f"✓ 成功访问: {url}")
            print("  等待页面加载...")
            self.wait.until(lambda d: self.find_data_table() is not None)
            
            page_num = 1
            
            while page_num <= max_pages:
                print(f"\n正在抓取第 {page_num} 页...")

                # 解析当前页面
                page_data = self.parse_table_data(
                    keywords=keywords,
                    follow_detail=follow_detail,
                    extract_detail=extract_detail,
                    current_page=page_num
                )

                if page_data:
                    # 为每笔资料加上状态和类型
                    for item in page_data:
                        item['status'] = status_label
                        item['type'] = '促参案件'

                    all_data.extend(page_data)
                    print(f"  ✓ 收集 {len(page_data)} 笔资料（累计 {len(all_data)} 笔）")
                else:
                    print(f"  ⚠ 本页未找到资料")

                # 检查是否有下一页
                if self.has_next_page():
                    print(f"  → 准备翻到下一页...")
                    if self.click_next_page():
                        page_num += 1
                        # 更新當前頁面 URL
                        self.current_list_url = self.driver.current_url
                        print(f"  ✅ 成功翻到第 {page_num} 页，URL: {self.current_list_url}")
                    else:
                        print("  ⚠ 无法点击下一页按钮，结束翻页")
                        break
                else:
                    print(f"  ✓ 已到达最后一页")
                    break
            
            if page_num > max_pages:
                print(f"\n⚠ 达到安全上限（{max_pages} 页），停止翻页")
            
            print(f"\n✓ 成功收集 {len(all_data)} 笔促参{status_label}案件")
            return all_data
            
        except Exception as e:
            print(f"✗ 抓取失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return all_data
    
    def collect_all_categories(self, keywords=None, follow_detail=True, 
                              extract_detail=True, max_pages=20):
        """
        依序抓取促參公告與已登載案件，回傳統一資料結構。

        :param keywords: 關鍵字列表，用於名稱/機關過濾
        :param follow_detail: 是否點入詳情頁抓真正網址
        :param extract_detail: 是否從詳情頁抓取額外資訊
        :param max_pages: 每個類別最大翻頁數
        :return: dict，包含 promotionAnnounce、promotionRegistered
        """
        all_data = {
            'promotionAnnounce': [],
            'promotionRegistered': []
        }

        try:
            all_data['promotionAnnounce'] = self.scrape_with_autopagination(
                'https://ppp.mof.gov.tw/WWW/inv_ann.aspx',
                '公告中',
                keywords=keywords,
                follow_detail=follow_detail,
                extract_detail=extract_detail,
                max_pages=max_pages
            )
            
            all_data['promotionRegistered'] = self.scrape_with_autopagination(
                'https://ppp.mof.gov.tw/WWW/inv_case.aspx',
                '已登载',
                keywords=keywords,
                follow_detail=follow_detail,
                extract_detail=extract_detail,
                max_pages=max_pages
            )
        except Exception as exc:
            print(f"✗ 抓取過程發生錯誤：{exc}")
            raise

        return all_data

    def match_keywords(self, text, keywords):
        """关键字匹配"""
        if not keywords:
            return True
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)
    
    def save_to_json(self, data, filename):
        """储存为 JSON"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ JSON 已储存: {filename}")
    
    def save_to_csv(self, all_data, base_filename):
        """储存为 CSV"""
        for key, data in all_data.items():
            if data:
                filename = f"{base_filename}_{key}.csv"
                try:
                    # 動態取得所有可能的欄位
                    fieldnames = set()
                    for item in data:
                        fieldnames.update(item.keys())
                    fieldnames = sorted(list(fieldnames))
                    
                    with open(filename, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        for item in data:
                            writer.writerow(item)
                    print(f"✓ CSV 已储存: {filename}")
                except Exception as e:
                    print(f"✗ CSV 储存失败: {str(e)}")


def _build_result_payload(
    data: Dict[str, List[Dict[str, Any]]],
    *,
    keywords: Optional[List[str]] = None
) -> Dict[str, Any]:
    """整理統一輸出格式，包含統計資訊。"""
    timestamp = datetime.now()
    stats = {
        key: len(value)
        for key, value in data.items()
    }
    total = sum(stats.values())
    return {
        "crawlerId": "promotion-platform-detailed",
        "runAt": timestamp.isoformat(),
        "filters": {
            "keywords": keywords or [],
        },
        "stats": stats,
        "totalRecords": total,
        "data": data,
    }


def run_promotions(
    headless: bool = True,
    keywords: Optional[List[str]] = None,
    output_dir: Optional[Path] = None,
    follow_detail: bool = True,
    extract_detail: bool = True,
    max_pages: int = 20
) -> Dict[str, Any]:
    """
    供外部呼叫的實用函式：
    - headless: 是否啟用 Headless 模式（預設 True，方便自動化）
    - keywords: 關鍵字過濾；None 代表擷取全部
    - output_dir: 若指定則在該資料夾底下輸出 JSON 檔案
    - follow_detail: 是否點入詳情頁抓真正網址
    - extract_detail: 是否從詳情頁抓取額外資訊
    - max_pages: 每個類別最大翻頁數

    :return: 包含資料與統計資訊的 dict
    """
    scraper = ProcurementScraperDetailed(headless=headless)
    try:
        scraper.setup_driver()
        data = scraper.collect_all_categories(
            keywords=keywords,
            follow_detail=follow_detail,
            extract_detail=extract_detail,
            max_pages=max_pages
        )
        result = _build_result_payload(data, keywords=keywords)

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = output_dir / f"promotion_platform_detailed_{datetime.now():%Y%m%d_%H%M%S}.json"
            scraper.save_to_json(result, str(filename))

        return result
    finally:
        scraper.close_driver()


def main():
    print("\n" + "="*70)
    print("🏢 ECOVE 政府标案资讯收集系统 - 詳細版")
    print("   會點進每筆案件的詳情頁，取得真正的網址和完整資訊")
    print("="*70 + "\n")
    
    # 设定参数
    print("⚙️  設定參數：")
    print("="*70)
    
    # 关键字设定（None = 收集所有案件）
    keywords = None
    print(f"  關鍵字過濾: {'無（抓取全部）' if not keywords else ', '.join(keywords)}")
    
    # 是否點進詳情頁（預設為 True，使用手動切換頁面方式）
    follow_detail = True
    print(f"  點入詳情頁: {'是（手動切換頁面）' if follow_detail else '否'}")

    # 是否抓取詳細資訊（預算、案號等）
    extract_detail = True
    print(f"  抓取詳細資訊: {'是（預算、案號等）' if extract_detail else '否'}")
    
    # 最大翻頁數
    max_pages = 5  # 測試時可以設小一點，正式使用改成 20 或更大
    print(f"  最大翻頁數: {max_pages} 頁/類別")
    
    print("="*70 + "\n")
    
    if follow_detail:
        print("⚠️  注意：點入詳情頁會比較慢，請耐心等候...")
        print("   如需快速測試，可將 follow_detail 設為 False\n")
    
    scraper = ProcurementScraperDetailed(headless=False)
    all_data = {
        'promotionAnnounce': [],
        'promotionRegistered': []
    }
    run_result = {}

    try:
        scraper.setup_driver()
        
        all_data = scraper.collect_all_categories(
            keywords=keywords,
            follow_detail=follow_detail,
            extract_detail=extract_detail,
            max_pages=max_pages
        )
        run_result = _build_result_payload(all_data, keywords=keywords)
        
        # 储存结果
        print("\n" + "="*70)
        print("💾 储存收集结果...")
        print("="*70)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        scraper.save_to_json(run_result, f'procurement_data_detailed_{timestamp}.json')
        
        # 统计
        print("\n" + "="*70)
        print("📊 收集完成！统计资讯：")
        print("="*70)
        
        total = run_result.get("totalRecords", 0)
        for key, value in all_data.items():
            count = len(value)
            if count > 0:
                type_name = {
                    'promotionAnnounce': '促参公告',
                    'promotionRegistered': '促参登载'
                }.get(key, key)
                print(f"  {type_name}: {count} 笔")
                
                # 顯示是否有抓到詳細資訊
                if extract_detail and value:
                    with_budget = sum(1 for item in value if item.get('budget'))
                    with_detail_case_no = sum(1 for item in value if item.get('detailCaseNumber'))
                    print(f"    └─ 含預算資訊: {with_budget} 筆")
                    print(f"    └─ 含詳細案號: {with_detail_case_no} 筆")
        
        print(f"\n  📌 总计: {total} 笔资料")
        print(f"  ✓ 资料已储存为 JSON 格式")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ 执行错误: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        scraper.close_driver()
    
    # 批次執行時不暫停，讓程式自動結束


if __name__ == '__main__':
    main()





