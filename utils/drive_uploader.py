"""
Google Drive upload utility using Service Account authentication.
Enhanced with file listing, download, move, and delete capabilities.
"""

import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


class DriveUploader:
    """Handles file operations on Google Drive using Service Account."""
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    def __init__(self, service_account_file: str, folder_id: str):
        """
        Initialize the uploader.
        
        Args:
            service_account_file: Path to service account JSON file
            folder_id: Target Google Drive folder ID
        """
        self.folder_id = folder_id
        self.service = self._build_service(service_account_file)
    
    def _build_service(self, service_account_file: str):
        """Build Google Drive API service."""
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=self.SCOPES
        )
        return build('drive', 'v3', credentials=credentials)
    
    # =========================================================================
    # Upload Methods
    # =========================================================================
    
    def upload_file(self, file_path: str, mime_type: str = 'application/json') -> Optional[str]:
        """
        Upload a file to Google Drive.
        
        Args:
            file_path: Path to the file to upload
            mime_type: MIME type of the file
            
        Returns:
            File ID if successful, None otherwise
        """
        try:
            file_name = Path(file_path).name
            
            file_metadata = {
                'name': file_name,
                'parents': [self.folder_id]
            }
            
            media = MediaFileUpload(
                file_path,
                mimetype=mime_type,
                resumable=True
            )
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            file_id = file.get('id')
            print(f"  ✓ Uploaded: {file_name} (ID: {file_id})")
            return file_id
            
        except Exception as e:
            print(f"  ✗ Upload failed for {file_path}: {e}")
            return None
    
    def upload_json(self, data: dict, filename: str) -> Optional[str]:
        """
        Upload JSON data directly to Google Drive.
        
        Args:
            data: Dictionary to upload as JSON
            filename: Target filename
            
        Returns:
            File ID if successful, None otherwise
        """
        # Save to temporary file first
        temp_path = f"/tmp/{filename}"
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return self.upload_file(temp_path)
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    # =========================================================================
    # List Methods
    # =========================================================================
    
    def list_files(self, folder_id: Optional[str] = None, 
                   name_contains: Optional[str] = None) -> List[Dict]:
        """
        List files in a folder.
        
        Args:
            folder_id: Folder ID to list (defaults to self.folder_id)
            name_contains: Filter by filename containing this string
            
        Returns:
            List of file metadata dicts with 'id', 'name', 'createdTime', 'modifiedTime'
        """
        target_folder = folder_id or self.folder_id
        try:
            query = f"'{target_folder}' in parents and trashed = false"
            if name_contains:
                query += f" and name contains '{name_contains}'"
            
            results = self.service.files().list(
                q=query,
                fields="files(id, name, createdTime, modifiedTime)",
                orderBy="createdTime desc",
                pageSize=100
            ).execute()
            
            files = results.get('files', [])
            return files
            
        except Exception as e:
            print(f"  ✗ List files failed: {e}")
            return []
    
    # =========================================================================
    # Download Methods
    # =========================================================================
    
    def download_file(self, file_id: str, local_path: str) -> bool:
        """
        Download a file from Google Drive.
        
        Args:
            file_id: Google Drive file ID
            local_path: Local path to save the file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            # Write to local file
            fh.seek(0)
            with open(local_path, 'wb') as f:
                f.write(fh.read())
            
            return True
            
        except Exception as e:
            print(f"  ✗ Download failed for {file_id}: {e}")
            return False
    
    def download_json(self, file_id: str) -> Optional[Dict]:
        """
        Download a JSON file and parse it.
        
        Args:
            file_id: Google Drive file ID
            
        Returns:
            Parsed JSON data or None if failed
        """
        temp_path = f"/tmp/temp_download_{file_id}.json"
        try:
            if self.download_file(file_id, temp_path):
                with open(temp_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return None
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    # =========================================================================
    # Move Methods
    # =========================================================================
    
    def move_file(self, file_id: str, new_folder_id: str) -> bool:
        """
        Move a file to another folder.
        
        Args:
            file_id: File ID to move
            new_folder_id: Target folder ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current parents
            file = self.service.files().get(
                fileId=file_id,
                fields='parents'
            ).execute()
            previous_parents = ",".join(file.get('parents', []))
            
            # Move to new folder
            self.service.files().update(
                fileId=file_id,
                addParents=new_folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            
            return True
            
        except Exception as e:
            print(f"  ✗ Move failed for {file_id}: {e}")
            return False
    
    # =========================================================================
    # Delete Methods
    # =========================================================================
    
    def delete_file(self, file_id: str) -> bool:
        """
        Delete a file from Google Drive.
        
        Args:
            file_id: File ID to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except Exception as e:
            print(f"  ✗ Delete failed for {file_id}: {e}")
            return False
    
    def delete_old_files(self, folder_id: Optional[str] = None, 
                         days: int = 30,
                         name_contains: Optional[str] = None) -> int:
        """
        Delete files older than specified days.
        
        Args:
            folder_id: Folder ID (defaults to self.folder_id)
            days: Delete files older than this many days
            name_contains: Only delete files with names containing this string
            
        Returns:
            Number of files deleted
        """
        target_folder = folder_id or self.folder_id
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        cutoff_str = cutoff_date.strftime('%Y-%m-%dT%H:%M:%S')
        
        try:
            query = f"'{target_folder}' in parents and trashed = false"
            query += f" and createdTime < '{cutoff_str}'"
            if name_contains:
                query += f" and name contains '{name_contains}'"
            
            results = self.service.files().list(
                q=query,
                fields="files(id, name, createdTime)",
                pageSize=100
            ).execute()
            
            files = results.get('files', [])
            deleted_count = 0
            
            for file in files:
                if self.delete_file(file['id']):
                    print(f"    🗑️ Deleted old file: {file['name']}")
                    deleted_count += 1
            
            return deleted_count
            
        except Exception as e:
            print(f"  ✗ Delete old files failed: {e}")
            return 0
