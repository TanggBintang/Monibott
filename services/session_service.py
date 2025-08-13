import json
import os
from datetime import datetime

class SessionService:
    def __init__(self, google_service):
        self.user_sessions = {}
        self.google_service = google_service
    
    def create_session(self, user_id):
        """Create new session"""
        self.user_sessions[user_id] = {
            'report_type': None,
            'id_ticket': None,
            'folder_id': None,
            'photos': [],
            'data': None,
            'created_at': datetime.now().isoformat()
        }
        return self.user_sessions[user_id]
    
    def get_session(self, user_id):
        """Get current session"""
        return self.user_sessions.get(user_id)
    
    def update_session(self, user_id, data):
        """Update session data"""
        if user_id in self.user_sessions:
            self.user_sessions[user_id].update(data)
            return True
        return False
    
    def end_session(self, user_id):
        """End current session"""
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
            return True
        return False