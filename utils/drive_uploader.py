"""
Google Drive upload utility using Service Account authentication.
"""

import json
import os
from pathlib import Path
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


class DriveUploader:
    """Handles file uploads to Google Drive using Service Account."""
    
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
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
