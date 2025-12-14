"""
資料清理與合併工具
功能：
1. 刪除過期資料（根據 deadline / public_read_end / announcementEndDate）
2. 合併同類型爬蟲資料，去除重複
3. 每 1000 筆輸出一個檔案

Adapted for SelfEcoGrab cloud runner.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
import re


class DataCleaner:
    """資料清理器：過期資料刪除、去重、合併"""
    
    # 三種爬蟲類型的設定 - 適配 SelfEcoGrab 的檔名格式
    CRAWLER_CONFIGS = {
        "tender": {
            "file_pattern": "tender_announcement_*.json",  # SelfEcoGrab format
            "date_field": "deadline",
            "id_field": "tenderId",
            "crawler_id": "tender-announcement",
            "output_prefix": "tender_merged",
        },
        "public_read": {
            "file_pattern": "public_read_*.json",
            "date_field": "public_read_end",
            "id_field": "tenderId",
            "crawler_id": "public-read",
            "output_prefix": "public_read_merged",
        },
        "promotion": {
            "file_pattern": "procurement_*.json",  # SelfEcoGrab format for ppp-mof
            "date_field": "announcementEndDate",
            "id_field": "tenderId",
            "crawler_id": "ppp-mof",
            "output_prefix": "promotion_merged",
        },
    }
    
    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.today = self._get_today_roc()
        print(f"📅 今天日期（民國年）: {self.today}")
    
    def _get_today_roc(self) -> str:
        """取得今天的民國年日期 (YYY/MM/DD)"""
        now = datetime.now()
        roc_year = now.year - 1911
        return f"{roc_year}/{now.month:02d}/{now.day:02d}"
    
    def _parse_roc_date(self, date_str: str) -> Optional[datetime]:
        """解析民國年日期字串，轉換為 datetime"""
        if not date_str or not date_str.strip():
            return None
        
        # 清理日期字串
        date_str = date_str.strip()
        
        # 嘗試不同格式
        patterns = [
            r"(\d{3})/(\d{1,2})/(\d{1,2})",  # 114/12/13
            r"(\d{3})\.(\d{1,2})\.(\d{1,2})",  # 114.12.13
            r"(\d{3})-(\d{1,2})-(\d{1,2})",  # 114-12-13
        ]
        
        for pattern in patterns:
            match = re.match(pattern, date_str)
            if match:
                try:
                    roc_year = int(match.group(1))
                    month = int(match.group(2))
                    day = int(match.group(3))
                    ad_year = roc_year + 1911
                    return datetime(ad_year, month, day)
                except ValueError:
                    continue
        
        return None
    
    def _is_expired(self, date_str: str) -> bool:
        """判斷是否過期"""
        if not date_str or not date_str.strip():
            # 如果沒有截止日期，視為不過期（保留資料）
            return False
        
        parsed_date = self._parse_roc_date(date_str)
        if not parsed_date:
            # 無法解析的日期，視為不過期（保留資料）
            return False
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return parsed_date < today
    
    def _get_record_hash(self, record: Dict[str, Any], id_field: str) -> str:
        """計算記錄的 hash，用於去重"""
        # 使用案號 + 完整內容的 hash
        record_id = record.get(id_field, "")
        # 排序 key 確保相同內容產生相同 hash
        content = json.dumps(record, sort_keys=True, ensure_ascii=False)
        content_hash = hashlib.md5(content.encode()).hexdigest()
        return f"{record_id}_{content_hash}"
    
    def _load_json_files(self, pattern: str) -> List[Dict[str, Any]]:
        """載入符合 pattern 的所有 JSON 檔案"""
        files = list(self.data_dir.glob(pattern))
        all_records = []
        
        for file_path in files:
            # Skip merged files to avoid re-processing
            if "_merged_" in file_path.name:
                continue
                
            print(f"  📂 讀取: {file_path.name}")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 提取資料
                if "data" in data:
                    records = data["data"]
                    # 處理 promotion 類型的巢狀結構
                    if isinstance(records, dict):
                        for key, items in records.items():
                            if isinstance(items, list):
                                all_records.extend(items)
                    elif isinstance(records, list):
                        all_records.extend(records)
            except Exception as e:
                print(f"    ⚠ 讀取失敗: {e}")
        
        return all_records
    
    def _save_batches(
        self,
        records: List[Dict[str, Any]],
        prefix: str,
        crawler_id: str,
        batch_size: int = 1000
    ) -> int:
        """將記錄分批存檔，每批 batch_size 筆"""
        if not records:
            return 0
        
        timestamp = datetime.now().strftime("%Y%m%d")
        total_batches = (len(records) + batch_size - 1) // batch_size
        
        for i in range(total_batches):
            start = i * batch_size
            end = min((i + 1) * batch_size, len(records))
            batch_records = records[start:end]
            
            filename = f"{prefix}_{timestamp}_batch{i + 1:03d}.json"
            filepath = self.data_dir / filename
            
            payload = {
                "crawlerId": crawler_id,
                "mergedAt": datetime.now().isoformat(),
                "batchNumber": i + 1,
                "totalBatches": total_batches,
                "totalRecords": len(batch_records),
                "data": batch_records,
            }
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            
            print(f"    💾 已存檔: {filename} ({len(batch_records)} 筆)")
        
        return total_batches
    
    def clean_crawler_type(self, crawler_type: str) -> Dict[str, int]:
        """清理特定類型的爬蟲資料"""
        if crawler_type not in self.CRAWLER_CONFIGS:
            raise ValueError(f"未知的爬蟲類型: {crawler_type}")
        
        config = self.CRAWLER_CONFIGS[crawler_type]
        print(f"\n{'='*60}")
        print(f"🔧 處理 {crawler_type} 類型資料")
        print(f"{'='*60}")
        
        # 1. 載入所有檔案
        print(f"\n📥 載入檔案 ({config['file_pattern']})...")
        records = self._load_json_files(config["file_pattern"])
        original_count = len(records)
        print(f"  ✓ 載入 {original_count} 筆資料")
        
        if original_count == 0:
            return {
                "original": 0,
                "after_expire": 0,
                "after_dedup": 0,
                "files": 0,
            }
        
        # 2. 過濾過期資料
        print(f"\n🗑 過濾過期資料 ({config['date_field']})...")
        valid_records = [
            r for r in records
            if not self._is_expired(r.get(config["date_field"], ""))
        ]
        expired_count = original_count - len(valid_records)
        print(f"  ✓ 過期資料: {expired_count} 筆")
        print(f"  ✓ 有效資料: {len(valid_records)} 筆")
        
        # 3. 去除重複
        print(f"\n🔄 去除重複資料 ({config['id_field']})...")
        seen_hashes = set()
        unique_records = []
        
        for record in valid_records:
            record_hash = self._get_record_hash(record, config["id_field"])
            if record_hash not in seen_hashes:
                seen_hashes.add(record_hash)
                unique_records.append(record)
        
        duplicate_count = len(valid_records) - len(unique_records)
        print(f"  ✓ 重複資料: {duplicate_count} 筆")
        print(f"  ✓ 不重複資料: {len(unique_records)} 筆")
        
        # 4. 分批存檔
        print(f"\n💾 分批存檔 ({config['output_prefix']})...")
        files_count = self._save_batches(
            unique_records,
            config["output_prefix"],
            config["crawler_id"]
        )
        
        return {
            "original": original_count,
            "after_expire": len(valid_records),
            "after_dedup": len(unique_records),
            "files": files_count,
        }
    
    def clean_all(self) -> Dict[str, Dict[str, int]]:
        """清理所有類型的爬蟲資料"""
        results = {}
        
        for crawler_type in self.CRAWLER_CONFIGS:
            try:
                results[crawler_type] = self.clean_crawler_type(crawler_type)
            except Exception as e:
                print(f"  ⚠ 處理 {crawler_type} 時發生錯誤: {e}")
                results[crawler_type] = {"error": str(e)}
        
        return results
    
    def get_merged_files(self) -> List[str]:
        """取得所有合併後的檔案路徑"""
        merged_files = []
        for config in self.CRAWLER_CONFIGS.values():
            prefix = config["output_prefix"]
            pattern = f"{prefix}_*.json"
            for f in self.data_dir.glob(pattern):
                merged_files.append(str(f))
        return merged_files


def run_data_cleaner(data_dir: str = ".") -> Dict[str, Any]:
    """執行資料清理並返回結果"""
    print("\n" + "=" * 70)
    print("📊 資料清理與合併工具")
    print("    功能: 刪除過期資料、去重複、合併檔案")
    print("=" * 70)
    
    cleaner = DataCleaner(data_dir)
    
    # 清理所有類型
    results = cleaner.clean_all()
    
    # 輸出統計
    print("\n" + "=" * 70)
    print("📊 處理統計")
    print("=" * 70)
    
    for crawler_type, stats in results.items():
        if "error" in stats:
            print(f"\n❌ {crawler_type}: 發生錯誤 - {stats['error']}")
        else:
            print(f"\n✅ {crawler_type}:")
            print(f"   原始資料: {stats['original']} 筆")
            print(f"   刪除過期: {stats['original'] - stats['after_expire']} 筆")
            print(f"   刪除重複: {stats['after_expire'] - stats['after_dedup']} 筆")
            print(f"   最終資料: {stats['after_dedup']} 筆")
            print(f"   輸出檔案: {stats['files']} 個")
    
    print("\n" + "=" * 70)
    print("✅ 資料清理完成！")
    print("=" * 70 + "\n")
    
    return {
        "stats": results,
        "merged_files": cleaner.get_merged_files()
    }


if __name__ == "__main__":
    run_data_cleaner(".")
