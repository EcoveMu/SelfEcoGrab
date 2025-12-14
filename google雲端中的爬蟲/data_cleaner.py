from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# ==== Config ====

# 可以用環境變數 CRAWLER_BASE_DIR 覆蓋，預設是這支檔案所在目錄
BASE_DIR = Path(os.environ.get("CRAWLER_BASE_DIR", Path(__file__).resolve().parent))

ARCHIVE_DIR_NAME = "_archive"
DAYS_TO_KEEP_ARCHIVES = 30

# 這些欄位不算「內容變更」，只用來記錄抓取時間之類
EXCLUDED_FIELDS_FOR_CHANGE_DETECTION = {
    "scrapedAt",
    "scraped_at",
    "scrapedTime",
    "scrape_time",
    "scraped_at_ts",
    "lastUpdateTime",
    "updatedAt",
    "updated_at",
}

@dataclass
class CrawlerConfig:
    name: str
    file_pattern: str               # 原始爬蟲輸出檔案 pattern
    merged_prefix: str              # 輸出檔案前綴，例如 "tender_merged"
    id_field: str = "tenderId"      # 用來做版本追蹤的主鍵欄位
    base_dir: Path = BASE_DIR       # 此 crawler 的工作目錄

# 本地版本的 CRAWLER_CONFIGS，根據實際檔案命名格式設定
CRAWLER_CONFIGS: List[CrawlerConfig] = [
    CrawlerConfig(
        name="tender",
        file_pattern="tender_batch_*.json",
        merged_prefix="tender_merged",
        id_field="tenderId",
    ),
    CrawlerConfig(
        name="promotion",
        file_pattern="procurement_data_detailed_*.json",
        merged_prefix="promotion_merged",
        id_field="tenderId",
    ),
    CrawlerConfig(
        name="public_read",
        file_pattern="public_read_2*.json",  # 使用 2* 排除 public_read_merged_*.json
        merged_prefix="public_read_merged",
        id_field="tenderId",
    ),
]


# ==== 基本 I/O ====


def _load_json(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to load JSON from {path}: {e}") from e
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 有些情況會是 { "data": [...] }
        if "data" in data and isinstance(data["data"], list):
            return data["data"]
    raise ValueError(f"Unexpected JSON format in {path}: {type(data)}")


def _dump_json(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = list(rows)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ==== 版本追蹤相關（Strategy C） ====


def _normalized_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """移除不影響內容的欄位後回傳新的 dict，用來比較內容是否有變更。"""
    return {
        k: v
        for k, v in record.items()
        if k not in EXCLUDED_FIELDS_FOR_CHANGE_DETECTION and not k.startswith("_")
    }


def _content_has_changed(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    """比較兩筆資料內容是否有變更（排除 scrapedAt 等時間戳欄位）。"""
    return _normalized_record(old) != _normalized_record(new)


def _record_timestamp_key(rec: Dict[str, Any]) -> Tuple[int, Any]:
    """
    取得排序用的 key，盡量依 scrapedAt / scraped_at 類欄位排序。
    回傳 (priority, value) 以避免 datetime / str 混在一起比較。
    """
    for field in (
        "scrapedAt",
        "scraped_at",
        "scrapedTime",
        "scrape_time",
        "createdAt",
        "created_at",
    ):
        ts = rec.get(field)
        if not ts:
            continue
        # 盡量當成 ISO datetime 處理
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return (0, dt)
            except Exception:
                # 無法 parse，就當普通字串
                return (1, ts)
        return (1, ts)
    # 找不到時間欄位時，排到最後
    return (2, "")


def keep_only_changed_versions(
    records: Iterable[Dict[str, Any]], id_field: str
) -> List[Dict[str, Any]]:
    """
    Strategy C:
    對於同一個 tenderId（或 config.id_field），保留「內容有變更」的版本序列，
    並移除內容完全相同（只時間不同）的重複版本。
    """
    grouped: Dict[Any, List[Dict[str, Any]]] = {}
    for r in records:
        key = r.get(id_field)
        if key is None:
            # 沒有 id_field 的資料就直接略過，避免污染版本鏈
            continue
        grouped.setdefault(key, []).append(r)

    result: List[Dict[str, Any]] = []
    for key, versions in grouped.items():
        # 依時間排序，確保版本順序一致
        versions_sorted = sorted(versions, key=_record_timestamp_key)
        previous_kept: Dict[str, Any] | None = None
        for v in versions_sorted:
            if previous_kept is None:
                result.append(v)
                previous_kept = v
            else:
                if _content_has_changed(previous_kept, v):
                    result.append(v)
                    previous_kept = v
                # else: 內容完全一樣，略過

    return result


# ==== 舊合併檔載入 / 歸檔 ====


def _load_previous_merged_records(
    cfg: CrawlerConfig,
) -> Tuple[List[Dict[str, Any]], List[Path]]:
    """
    載入現有的 *_merged_*.json 檔案，把所有舊資料攤平成一個 list。
    同時回傳這些 merged 檔案路徑，以便後續歸檔到 _archive/。
    """
    pattern = f"{cfg.merged_prefix}_*.json"
    merged_files = sorted(cfg.base_dir.glob(pattern))
    all_rows: List[Dict[str, Any]] = []

    for path in merged_files:
        try:
            rows = _load_json(path)
        except Exception as e:
            print(f"[WARN] Skip broken merged file {path}: {e}")
            continue
        all_rows.extend(rows)

    return all_rows, merged_files


def _load_raw_crawler_records(cfg: CrawlerConfig) -> List[Dict[str, Any]]:
    """載入此次爬蟲的原始輸出檔案。"""
    rows: List[Dict[str, Any]] = []
    for path in sorted(cfg.base_dir.glob(cfg.file_pattern)):
        try:
            data = _load_json(path)
        except Exception as e:
            print(f"[WARN] Skip broken raw file {path}: {e}")
            continue
        rows.extend(data)
    return rows


def archive_old_merged_files(cfg: CrawlerConfig, existing_merged_files: List[Path]) -> None:
    """
    將舊的 merged 檔案搬到 _archive/ 子資料夾，只保留最新的一份在主目錄。
    """
    if not existing_merged_files:
        return

    # 依檔名排序，最後一個視為最新
    existing_merged_files = sorted(existing_merged_files)
    latest = existing_merged_files[-1]
    to_archive = existing_merged_files[:-1]

    archive_dir = latest.parent / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)

    for path in to_archive:
        target = archive_dir / path.name
        try:
            print(f"[INFO] Archiving old merged file {path} -> {target}")
            shutil.move(str(path), str(target))
        except Exception as e:
            print(f"[WARN] Failed to archive {path}: {e}")


def cleanup_old_archives(base_dir: Path, days: int = DAYS_TO_KEEP_ARCHIVES) -> None:
    """
    刪除 _archive/ 底下超過 N 天的檔案。
    這個功能主要是給週日排程使用，但每天執行也安全。
    """
    cutoff = datetime.now() - timedelta(days=days)
    for path in base_dir.rglob("*.json"):
        if path.parent.name != ARCHIVE_DIR_NAME:
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError as e:
            print(f"[WARN] Failed to stat {path}: {e}")
            continue
        if mtime < cutoff:
            try:
                print(f"[INFO] Removing old archive file {path}")
                path.unlink()
            except OSError as e:
                print(f"[WARN] Failed to remove {path}: {e}")


# ==== 資料處理主流程 ====


def process_crawler(cfg: CrawlerConfig) -> None:
    print(f"==== Processing crawler: {cfg.name} ====")

    # 1. 載入舊 merged 資料
    previous_rows, existing_merged_files = _load_previous_merged_records(cfg)
    print(f"[INFO] Loaded {len(previous_rows)} rows from previous merged files for {cfg.name}")

    # 2. 載入此次爬蟲原始資料
    raw_rows = _load_raw_crawler_records(cfg)
    print(f"[INFO] Loaded {len(raw_rows)} rows from raw files for {cfg.name}")

    # 3. 合併後做過期過濾 & 版本去重
    all_rows = previous_rows + raw_rows
    if not all_rows:
        print(f"[INFO] No data found for {cfg.name}, skip.")
        return

    # 保留所有資料，不做過期過濾
    cleaned_rows = keep_only_changed_versions(all_rows, id_field=cfg.id_field)
    print(f"[INFO] After Strategy C, kept {len(cleaned_rows)} rows for {cfg.name}")

    # 4. 輸出新的 merged 檔案
    today_str = datetime.now().strftime("%Y%m%d")
    output_path = cfg.base_dir / f"{cfg.merged_prefix}_{today_str}.json"
    _dump_json(output_path, cleaned_rows)
    print(f"[INFO] Written merged file: {output_path}")

    # 5. 將舊的 merged 檔案搬到 _archive/
    archive_old_merged_files(cfg, existing_merged_files)


def main() -> None:
    for cfg in CRAWLER_CONFIGS:
        process_crawler(cfg)

    # 執行一次 archive 清理（每天跑也沒關係）
    cleanup_old_archives(BASE_DIR, days=DAYS_TO_KEEP_ARCHIVES)


if __name__ == "__main__":
    main()
