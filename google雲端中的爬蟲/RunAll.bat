@echo off
chcp 65001 >nul 2>&1

echo.
echo ==========================================
echo   招標資料爬蟲批次執行程式
echo ==========================================
echo.

REM 切換到腳本所在目錄
cd /d "%~dp0"

REM 檢查 Python 是否已安裝，使用 py 啟動器確保一致性
echo [Step 1/5] 檢查 Python 環境...
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [錯誤] 找不到 Python！請先安裝 Python 並勾選「Add to PATH」。
    echo        下載網址: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('py --version 2^>^&1') do echo [OK] %%v

REM 強制安裝/升級所有依賴套件
echo.
echo [Step 2/5] 安裝所需依賴套件...
echo.

echo 安裝 selenium...
py -m pip install selenium --quiet --upgrade 2>nul
if %errorlevel% neq 0 (
    echo [警告] selenium 安裝可能有問題，繼續執行...
) else (
    echo [OK] selenium 已就緒
)

echo 安裝 webdriver-manager...
py -m pip install webdriver-manager --quiet --upgrade 2>nul
if %errorlevel% neq 0 (
    echo [警告] webdriver-manager 安裝可能有問題，繼續執行...
) else (
    echo [OK] webdriver-manager 已就緒
)

echo 安裝 requests...
py -m pip install requests --quiet --upgrade 2>nul
if %errorlevel% neq 0 (
    echo [警告] requests 安裝可能有問題，繼續執行...
) else (
    echo [OK] requests 已就緒
)

echo 安裝 beautifulsoup4...
py -m pip install beautifulsoup4 --quiet --upgrade 2>nul
if %errorlevel% neq 0 (
    echo [警告] beautifulsoup4 安裝可能有問題，繼續執行...
) else (
    echo [OK] beautifulsoup4 已就緒
)

echo.
echo [OK] 依賴套件安裝完成
echo.

REM 驗證安裝
echo [驗證] 檢查套件是否可正常載入...
py -c "import selenium; print('  selenium:', selenium.__version__)" 2>nul || echo   [錯誤] selenium 無法載入
py -c "import webdriver_manager; print('  webdriver_manager: OK')" 2>nul || echo   [錯誤] webdriver_manager 無法載入
py -c "import requests; print('  requests:', requests.__version__)" 2>nul || echo   [錯誤] requests 無法載入
py -c "import bs4; print('  beautifulsoup4:', bs4.__version__)" 2>nul || echo   [錯誤] beautifulsoup4 無法載入
echo.

REM 執行爬蟲腳本
echo ==========================================
echo [Step 3/5] 開始執行爬蟲腳本...
echo ==========================================
echo.

echo ------------------------------------------
echo [1/3] 正在執行: public_read_scraper.py
echo       (公開閱覽標案爬蟲)
echo ------------------------------------------
py public_read_scraper.py
if %errorlevel% neq 0 (
    echo [警告] public_read_scraper.py 執行時發生錯誤
)
echo.

echo ------------------------------------------
echo [2/3] 正在執行: procurement_scraper_detailed.py
echo       (促參平台詳細爬蟲)
echo ------------------------------------------
py procurement_scraper_detailed.py
if %errorlevel% neq 0 (
    echo [警告] procurement_scraper_detailed.py 執行時發生錯誤
)
echo.

echo ------------------------------------------
echo [3/3] 正在執行: procurement_tender_scraper_unlimited.py
echo       (招標公告爬蟲)
echo ------------------------------------------
py procurement_tender_scraper_unlimited.py
if %errorlevel% neq 0 (
    echo [警告] procurement_tender_scraper_unlimited.py 執行時發生錯誤
)
echo.

REM 執行資料清理
echo ==========================================
echo [Step 4/5] 資料清理與合併...
echo ==========================================
echo.
echo 功能: 刪除過期資料、去除重複、合併檔案
echo ------------------------------------------
py data_cleaner.py
if %errorlevel% neq 0 (
    echo [警告] data_cleaner.py 執行時發生錯誤
)
echo.

echo ==========================================
echo [Step 5/5] 執行完畢！
echo ==========================================
echo.
echo 所有爬蟲腳本已執行完成。
echo 清理後的合併檔案：
echo   - tender_merged_*.json (招標公告)
echo   - public_read_merged_*.json (公開閱覽)
echo   - promotion_merged_*.json (促參平台)
echo.
pause