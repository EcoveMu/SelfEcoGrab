"""
Configuration handler for the scraper system.
Reads environment variables and provides defaults.
"""

import os


class Config:
    """Configuration manager for scraper settings."""
    
    # Google Drive settings
    GOOGLE_DRIVE_FOLDER_ID = os.environ.get(
        'GOOGLE_DRIVE_FOLDER_ID', 
        '1HenAIy7mPsfaVMHGd2sLu1fygfSpeFad'
    )
    
    SERVICE_ACCOUNT_FILE = os.environ.get(
        'SERVICE_ACCOUNT_FILE',
        'service_account.json'
    )
    
    # Scraper settings
    HEADLESS = True  # Always headless in cloud environment
    WAIT_SECONDS = 20
    MAX_PAGES = 100  # Safety limit
    
    # Output settings
    OUTPUT_DIR = 'output'
    
    @classmethod
    def get_output_path(cls, filename: str) -> str:
        """Get full path for output file."""
        os.makedirs(cls.OUTPUT_DIR, exist_ok=True)
        return os.path.join(cls.OUTPUT_DIR, filename)
