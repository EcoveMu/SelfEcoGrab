"""
Main runner for automated data collection.
Runs all scrapers and uploads results to Google Drive.
"""

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from scrapers import run_procurement_scraper, run_tender_scraper, run_public_read_scraper
from utils import Config, DriveUploader, run_data_cleaner


def save_result(result: dict, prefix: str) -> str:
    """Save result to JSON file and return the path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.json"
    filepath = Config.get_output_path(filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"  💾 Saved: {filepath}")
    return filepath


def run_all_scrapers() -> list:
    """Run all scrapers and return list of output files."""
    output_files = []
    
    scrapers = [
        ("public-read", run_public_read_scraper, "public_read"),
        ("ppp-mof", run_procurement_scraper, "procurement"),
        ("tender", run_tender_scraper, "tender_announcement"),
    ]
    
    for name, runner, prefix in scrapers:
        print(f"\n{'=' * 60}")
        print(f"🔍 Running: {name}")
        print('=' * 60)
        
        try:
            result = runner()
            total = result.get('totalRecords', 0)
            print(f"  ✓ Found {total} records")
            
            if total > 0:
                filepath = save_result(result, prefix)
                output_files.append(filepath)
            else:
                print(f"  ⚠ No records found, skipping save")
                
        except Exception as e:
            print(f"  ✗ Error running {name}: {e}")
            traceback.print_exc()
    
    return output_files


def upload_to_drive(files: list) -> None:
    """Upload files to Google Drive."""
    if not files:
        print("\n⚠ No files to upload")
        return
    
    service_account_file = Config.SERVICE_ACCOUNT_FILE
    folder_id = Config.GOOGLE_DRIVE_FOLDER_ID
    
    if not os.path.exists(service_account_file):
        print(f"\n⚠ Service account file not found: {service_account_file}")
        print("  Skipping Google Drive upload")
        return
    
    print(f"\n{'=' * 60}")
    print("📤 Uploading to Google Drive")
    print('=' * 60)
    
    try:
        uploader = DriveUploader(service_account_file, folder_id)
        
        for filepath in files:
            uploader.upload_file(filepath)
            
        print(f"\n✓ Uploaded {len(files)} files to Google Drive")
        
    except Exception as e:
        print(f"\n✗ Upload error: {e}")
        traceback.print_exc()


def main():
    """Main entry point."""
    print("\n" + "=" * 60)
    print("🚀 Automated Data Collection")
    print(f"   Started at: {datetime.now().isoformat()}")
    print("=" * 60)
    
    # Create output directory
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    
    # Run all scrapers
    output_files = run_all_scrapers()
    
    # Run data cleaner to merge and deduplicate
    print("\n" + "=" * 60)
    print("🧹 Running Data Cleaner")
    print("=" * 60)
    
    try:
        cleaner_result = run_data_cleaner(Config.OUTPUT_DIR)
        merged_files = cleaner_result.get("merged_files", [])
        print(f"  ✓ Generated {len(merged_files)} merged files")
    except Exception as e:
        print(f"  ✗ Data cleaner error: {e}")
        traceback.print_exc()
        merged_files = []
    
    # Upload merged files to Google Drive (instead of raw scraper output)
    files_to_upload = merged_files if merged_files else output_files
    upload_to_drive(files_to_upload)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Summary")
    print("=" * 60)
    print(f"  Raw scraper files: {len(output_files)}")
    print(f"  Merged files: {len(merged_files)}")
    print(f"  Files uploaded: {len(files_to_upload)}")
    for f in files_to_upload:
        print(f"    - {os.path.basename(f)}")
    print(f"  Finished at: {datetime.now().isoformat()}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
