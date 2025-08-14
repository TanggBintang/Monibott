import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime
import json

# Scopes untuk Google API
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

class GoogleService:
    def __init__(self, parent_folder_id="1mLsCBEqEb0R4_pX75-xmpRE1023H6A90"):
        self.service_drive = None
        self.service_sheets = None
        self.parent_folder_id = parent_folder_id
        
    def authenticate(self):
        """Authenticate with Google APIs using Service Account"""
        try:
            # Coba ambil dari environment variable dulu (untuk production)
            service_account_info = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
            
            if service_account_info:
                try:
                    # Parse JSON string dari environment variable
                    service_account_dict = json.loads(service_account_info)
                    creds = service_account.Credentials.from_service_account_info(
                        service_account_dict, scopes=SCOPES
                    )
                    print("✅ Using service account from environment variable")
                except Exception as e:
            print(f"❌ Error accessing spreadsheet: {e}")
            return False

    def delete_file_or_folder(self, file_id):
        """Delete file or folder from Google Drive"""
        try:
            if not self.service_drive:
                print("❌ Google Drive service not initialized")
                return False
                
            self.service_drive.files().delete(fileId=file_id).execute()
            print(f"✅ Successfully deleted file/folder: {file_id}")
            return True
            
        except Exception as e:
            print(f"❌ Error deleting file/folder {file_id}: {e}")
            return False

    def list_files_in_folder(self, folder_id, max_results=100):
        """List files in a Google Drive folder"""
        try:
            if not self.service_drive:
                print("❌ Google Drive service not initialized")
                return []
            
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.service_drive.files().list(
                q=query,
                pageSize=max_results,
                fields="nextPageToken, files(id, name, mimeType, createdTime, size)"
            ).execute()
            
            files = results.get('files', [])
            print(f"📁 Found {len(files)} files in folder {folder_id}")
            
            return files
            
        except Exception as e:
            print(f"❌ Error listing files in folder {folder_id}: {e}")
            return []

    def get_spreadsheet_info(self, spreadsheet_id):
        """Get basic information about a spreadsheet"""
        try:
            if not self.service_sheets:
                print("❌ Google Sheets service not initialized")
                return None
            
            spreadsheet = self.service_sheets.spreadsheets().get(
                spreadsheetId=spreadsheet_id,
                fields="properties,sheets.properties"
            ).execute()
            
            properties = spreadsheet.get('properties', {})
            sheets = spreadsheet.get('sheets', [])
            
            info = {
                'title': properties.get('title', 'Unknown'),
                'locale': properties.get('locale', 'Unknown'),
                'timeZone': properties.get('timeZone', 'Unknown'),
                'sheet_count': len(sheets),
                'sheets': [sheet.get('properties', {}).get('title', f'Sheet{i+1}') 
                          for i, sheet in enumerate(sheets)]
            }
            
            print(f"📊 Spreadsheet info: {info}")
            return info
            
        except Exception as e:
            print(f"❌ Error getting spreadsheet info: {e}")
            return None json.JSONDecodeError as e:
                    print(f"❌ Error parsing service account JSON from environment: {e}")
                    return False
            else:
                # Fallback ke file local (untuk development)
                service_account_files = ['service-account.json', 'credentials.json']
                creds = None
                
                for filename in service_account_files:
                    if os.path.exists(filename):
                        try:
                            creds = service_account.Credentials.from_service_account_file(
                                filename, scopes=SCOPES
                            )
                            print(f"✅ Using service account from file: {filename}")
                            break
                        except Exception as e:
                            print(f"❌ Error loading service account from {filename}: {e}")
                            continue
                
                if not creds:
                    raise Exception("No valid service account credentials found!")
            
            # Build services
            self.service_drive = build('drive', 'v3', credentials=creds)
            self.service_sheets = build('sheets', 'v4', credentials=creds)
            
            # Test the connection
            try:
                # Test Drive API
                drive_about = self.service_drive.about().get(fields="user").execute()
                print(f"✅ Google Drive API connected as: {drive_about.get('user', {}).get('emailAddress', 'Unknown')}")
                
                # Test Sheets API by getting spreadsheet info (if we have a test spreadsheet ID)
                print("✅ Google Sheets API connected successfully")
                
            except Exception as e:
                print(f"❌ Error testing API connections: {e}")
                return False
            
            print("✅ Google APIs authenticated successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Error authenticating Google APIs: {e}")
            return False

    def create_folder(self, folder_name, parent_folder_id=None):
        """Create folder in Google Drive"""
        try:
            if not self.service_drive:
                print("❌ Google Drive service not initialized")
                return None
                
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            
            # Use provided parent folder or default
            target_parent = parent_folder_id or self.parent_folder_id
            if target_parent:
                folder_metadata['parents'] = [target_parent]
            
            folder = self.service_drive.files().create(body=folder_metadata).execute()
            folder_id = folder.get('id')
            
            if folder_id:
                print(f"✅ Folder created: {folder_name} (ID: {folder_id})")
                
                # Set folder permissions to be viewable by anyone with link
                try:
                    permission = {
                        'type': 'anyone',
                        'role': 'reader'
                    }
                    self.service_drive.permissions().create(
                        fileId=folder_id,
                        body=permission
                    ).execute()
                    print(f"✅ Folder permissions set for: {folder_name}")
                except Exception as perm_e:
                    print(f"⚠️ Warning: Could not set folder permissions: {perm_e}")
                
                return folder_id
            else:
                print(f"❌ Failed to get folder ID for: {folder_name}")
                return None
                
        except Exception as e:
            print(f"❌ Error creating folder '{folder_name}': {e}")
            return None

    def upload_to_drive(self, file_path, file_name, folder_id):
        """Upload file to Google Drive"""
        try:
            if not self.service_drive:
                print("❌ Google Drive service not initialized")
                return None
                
            if not os.path.exists(file_path):
                print(f"❌ File not found: {file_path}")
                return None
            
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            
            # Determine MIME type based on file extension
            mime_type = 'application/octet-stream'  # Default
            if file_path.lower().endswith(('.jpg', '.jpeg')):
                mime_type = 'image/jpeg'
            elif file_path.lower().endswith('.png'):
                mime_type = 'image/png'
            elif file_path.lower().endswith('.pdf'):
                mime_type = 'application/pdf'
            elif file_path.lower().endswith(('.doc', '.docx')):
                mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            
            media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
            
            uploaded_file = self.service_drive.files().create(
                body=file_metadata, 
                media_body=media
            ).execute()
            
            file_id = uploaded_file.get('id')
            
            if file_id:
                print(f"✅ File uploaded: {file_name} (ID: {file_id})")
                
                # Set file permissions
                try:
                    permission = {
                        'type': 'anyone',
                        'role': 'reader'
                    }
                    self.service_drive.permissions().create(
                        fileId=file_id,
                        body=permission
                    ).execute()
                    print(f"✅ File permissions set for: {file_name}")
                except Exception as perm_e:
                    print(f"⚠️ Warning: Could not set file permissions: {perm_e}")
                
                return file_id
            else:
                print(f"❌ Failed to get file ID for: {file_name}")
                return None
                
        except Exception as e:
            print(f"❌ Error uploading file '{file_name}': {e}")
            return None

    def get_folder_link(self, folder_id):
        """Get shareable link for Google Drive folder"""
        if folder_id:
            return f"https://drive.google.com/drive/folders/{folder_id}"
        return ""

    def get_file_link(self, file_id):
        """Get shareable link for Google Drive file"""
        if file_id:
            return f"https://drive.google.com/file/d/{file_id}/view"
        return ""

    def update_spreadsheet(self, spreadsheet_id, spreadsheet_config, laporan_data):
        """Update Google Spreadsheet with report data"""
        try:
            if not self.service_sheets:
                print("❌ Google Sheets service not initialized")
                return False
            
            if not spreadsheet_id:
                print("❌ Spreadsheet ID is required")
                return False
                
            print(f"📊 Updating spreadsheet: {spreadsheet_id}")
            print(f"📋 Report data: {laporan_data}")
            
            # Prepare row data
            row_data = spreadsheet_config.prepare_row_data(laporan_data, 0)
            print(f"📝 Prepared row data: {row_data}")
            
            body = {
                'values': [row_data]
            }
            
            # Append data to spreadsheet
            result = self.service_sheets.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=spreadsheet_config.get_append_range(),
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()
            
            updates = result.get('updates', {})
            updated_rows = updates.get('updatedRows', 0)
            updated_range = updates.get('updatedRange', 'Unknown')
            
            if updated_rows > 0:
                print(f"✅ Successfully added {updated_rows} row(s) to spreadsheet")
                print(f"📍 Updated range: {updated_range}")
                return True
            else:
                print(f"⚠️ No rows were added to spreadsheet")
                return False
            
        except Exception as e:
            print(f"❌ Error updating spreadsheet: {e}")
            # Print more detailed error info
            if hasattr(e, 'resp'):
                print(f"Response status: {e.resp.status}")
                print(f"Response reason: {e.resp.reason}")
            return False

    def test_spreadsheet_access(self, spreadsheet_id):
        """Test access to spreadsheet"""
        try:
            if not self.service_sheets:
                print("❌ Google Sheets service not initialized")
                return False
            
            # Try to get spreadsheet metadata
            spreadsheet = self.service_sheets.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            
            title = spreadsheet.get('properties', {}).get('title', 'Unknown')
            print(f"✅ Spreadsheet access confirmed: '{title}'")
            return True
            
        except
