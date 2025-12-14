# GitHub SelfEcoGrab 設定更新待辦事項

> **目標**：讓 GitHub Actions 上的 SelfEcoGrab 支援版本追蹤(Strategy C)、舊資料歸檔、週日自動清理功能

---

## 📁 需要修改的檔案

| # | 檔案路徑 | 修改內容 |
|---|----------|----------|
| 1 | `SelfEcoGrab/utils/config.py` | 新增環境變數讀取 |
| 2 | `SelfEcoGrab/utils/data_cleaner.py` | 整合 Strategy C 版本追蹤邏輯 |
| 3 | `SelfEcoGrab/main.py` | 整合新功能與週日清理判斷 |

---

## ✅ 已完成的設定

- [x] `.github/workflows/scraper.yml` - 週日清理排程 `cron: '0 16 * * 6'`
- [x] `.github/workflows/scraper.yml` - 環境變數 `GOOGLE_DRIVE_ARCHIVE_FOLDER_ID`
- [x] `utils/drive_uploader.py` - `list_files()`, `download_file()`, `move_file()`, `delete_file()` 等新功能

---

## 📝 待辦事項

### 1️⃣ 修改 `utils/config.py`

**新增以下設定**：
```python
GOOGLE_DRIVE_ARCHIVE_FOLDER_ID = os.environ.get(
    'GOOGLE_DRIVE_ARCHIVE_FOLDER_ID',
    '16K_M2lWLZPgeljTVGlSwbb2oqr4KyRHM'  # 舊資料留存資料夾
)
```

---

### 2️⃣ 修改 `utils/data_cleaner.py`

將本地版 `google雲端中的爬蟲/data_cleaner.py` 的功能整合進去：

| 功能 | 說明 |
|------|------|
| **Strategy C 版本追蹤** | 只保留內容有變更的版本，排除 `scrapedAt` 等時間戳欄位 |
| **載入舊合併檔案** | 從 Google Drive 下載最新的 `*_merged_*.json` 合併 |
| **歸檔處理** | 將舊的 merged 檔案移動到 `00.舊資料留存` |

**新增函數**：
- `_content_has_changed()` - 比較內容是否變更
- `keep_only_changed_versions()` - Strategy C 去重邏輯
- `_load_previous_merged_from_drive()` - 從 Drive 載入舊資料
- `_archive_old_merged()` - 歸檔舊合併檔

---

### 3️⃣ 修改 `main.py`

| 項目 | 說明 |
|------|------|
| 讀取環境變數 | `GOOGLE_DRIVE_ARCHIVE_FOLDER_ID` |
| 傳入 DriveUploader | 讓 data_cleaner 可以操作 Google Drive |
| 週日清理邏輯 | 判斷是否為週日，執行超過 30 天舊資料清理 |

**修改 `main()` 函數流程**：
```
1. 執行爬蟲取得新資料
2. 從 Google Drive 下載舊合併檔案
3. 合併舊+新資料
4. 執行 Strategy C 版本去重
5. 上傳新合併檔案
6. 移動舊合併檔案到舊資料區
7. (週日) 清理超過 30 天的舊資料
```

---

### 4️⃣ 設定 GitHub Secret

> ⚠️ **需要手動操作**

1. 前往 GitHub Repository → **Settings** → **Secrets and variables** → **Actions**
2. 點擊 **New repository secret**
3. 設定：
   - **Name**: `GOOGLE_DRIVE_ARCHIVE_FOLDER_ID`
   - **Value**: `16K_M2lWLZPgeljTVGlSwbb2oqr4KyRHM`

---

## 🔗 參考資料

- 本地版 data_cleaner.py: `google雲端中的爬蟲/data_cleaner.py`
- drive_uploader.py: `SelfEcoGrab/utils/drive_uploader.py`
- 舊資料留存 Folder ID: `16K_M2lWLZPgeljTVGlSwbb2oqr4KyRHM`
- 爬蟲資料 Folder ID: `1HenAIy7mPsfaVMHGd2sLu1fygfSpeFad`
