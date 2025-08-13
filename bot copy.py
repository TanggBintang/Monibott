import os
import asyncio
import signal
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import io
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import json
from datetime import datetime
import traceback
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import threading
import time
import psutil
from spreadsheet_config import SpreadsheetConfig, SpreadsheetPresets
import atexit
from datetime import datetime, timedelta
try:
    import psutil  # Untuk monitoring sistem
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("⚠️ Warning: psutil not found. Install with: pip install psutil")
    print("📊 Server monitoring will have limited functionality")



# States untuk ConversationHandler
INPUT_ID, INPUT_NAMA, UPLOAD_FOTO, INPUT_DESKRIPSI, REQUEST_LOCATION = range(5)
SESSION_WARNING_TIME = 15 * 60  # 15 menit
SESSION_TIMEOUT_TIME = 30 * 60  # 30 menit total

# Scopes untuk Google API
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

class TelegramBot:
    def __init__(self, token, spreadsheet_id):
        self.token = token
        self.spreadsheet_id = spreadsheet_id
        self.service_drive = None
        self.service_sheets = None
        self.user_sessions = {}
        self.completed_reports = {}
        self.parent_folder_id = "1mLsCBEqEb0R4_pX75-xmpRE1023H6A90"
        self.session_timers = {}  # user_id -> timer info
        self.session_locks = {}   # user_id -> threading lock
        # TAMBAHAN BARU: Variabel untuk status monitoring dan broadcast
        self.server_start_time = None
        self.active_users = set()  # Track users yang pernah berinteraksi
        self.broadcast_users = set()  # Users yang akan menerima notifikasi broadcast
        self.is_shutting_down = False
        self.load_users_from_file()


        
        # ========================================
        # OPSI 1: KONFIGURASI POSISI TABEL
        # ========================================
        # Uncomment baris di bawah jika ingin memindah tabel ke posisi lain
        
        # self.table_start_row = 1      # Default: baris 1 (A1, B1, C1...)
        # self.table_start_col = "A"    # Default: kolom A
        # self.table_end_col = "I"      # Default: sampai kolom I
        
        # CONTOH: Memindah tabel ke D5 (mulai dari D5, E5, F5...)
        # self.table_start_row = 5      # Mulai dari baris 5
        # self.table_start_col = "D"    # Mulai dari kolom D  
        # self.table_end_col = "L"      # Sampai kolom L
        
        # CONTOH: Memindah tabel ke B10 (mulai dari B10, C10, D10...)
        # self.table_start_row = 10     # Mulai dari baris 10
        # self.table_start_col = "B"    # Mulai dari kolom B
        # self.table_end_col = "J"      # Sampai kolom J

    def load_users_from_file(self):
        """Load users dari file JSON"""
        try:
            if os.path.exists('users.json'):
                with open('users.json', 'r') as f:
                    data = json.load(f)
                    self.broadcast_users = set(data.get('broadcast_users', []))
                    self.active_users = set(data.get('active_users', []))
                    print(f"📂 Loaded {len(self.broadcast_users)} users from file")
            else:
                print("📝 No users.json found, starting with empty user list")
        except Exception as e:
            print(f"❌ Error loading users: {e}")
            self.broadcast_users = set()
            self.active_users = set()

    def save_users_to_file(self):
        """Save users ke file JSON"""
        try:
            data = {
                'broadcast_users': list(self.broadcast_users),
                'active_users': list(self.active_users),
                'last_updated': datetime.now().isoformat()
            }
            with open('users.json', 'w') as f:
                json.dump(data, f, indent=2)
            print(f"💾 Saved {len(self.broadcast_users)} users to file")
        except Exception as e:
            print(f"❌ Error saving users: {e}")
        
    def get_gps_coordinates(self, exif_data):
        """Extract GPS coordinates from EXIF data"""
        try:
            gps_info = {}
            if 'GPSInfo' in exif_data:
                for tag, value in exif_data['GPSInfo'].items():
                    decoded = GPSTAGS.get(tag, tag)
                    gps_info[decoded] = value
            
            if 'GPSLatitude' in gps_info and 'GPSLongitude' in gps_info:
                lat_ref = gps_info.get('GPSLatitudeRef', 'N')
                lon_ref = gps_info.get('GPSLongitudeRef', 'E')
                
                # Convert GPS coordinates to decimal degrees
                lat = self.convert_gps_to_decimal(gps_info['GPSLatitude'])
                lon = self.convert_gps_to_decimal(gps_info['GPSLongitude'])
                
                # Apply reference (N/S for latitude, E/W for longitude)
                if lat_ref == 'S':
                    lat = -lat
                if lon_ref == 'W':
                    lon = -lon
                    
                return lat, lon
            return None, None
        except Exception as e:
            print(f"Error extracting GPS: {e}")
            return None, None

    def convert_gps_to_decimal(self, gps_coord):
        """Convert GPS coordinates from degrees, minutes, seconds to decimal"""
        try:
            degrees = float(gps_coord[0])
            minutes = float(gps_coord[1])
            seconds = float(gps_coord[2])
            return degrees + (minutes / 60.0) + (seconds / 3600.0)
        except:
            return 0.0

    def get_address_from_coordinates(self, lat, lon):
        """Get address from GPS coordinates using reverse geocoding"""
        try:
            geolocator = Nominatim(user_agent="telegram_bot")
            location = geolocator.reverse(f"{lat}, {lon}", timeout=10)
            if location:
                return location.address
            return None
        except GeocoderTimedOut:
            print("Geocoding timeout")
            return None
        except Exception as e:
            print(f"Error getting address: {e}")
            return None

    def extract_photo_metadata(self, filepath):
        """Extract basic metadata from photo (timestamp and camera info only)"""
        metadata = {
            'timestamp': None,
            'camera_info': None
        }
        
        try:
            # Open image and extract EXIF data
            with Image.open(filepath) as image:
                exif_data = image._getexif()
                
                if exif_data:
                    # Extract timestamp and camera info only
                    for tag, value in exif_data.items():
                        tag_name = TAGS.get(tag, tag)
                        
                        if tag_name == 'DateTime':
                            metadata['timestamp'] = value
                        elif tag_name == 'Make':
                            metadata['camera_info'] = f"{value} "
                        elif tag_name == 'Model':
                            if metadata['camera_info']:
                                metadata['camera_info'] += value
                            else:
                                metadata['camera_info'] = value
        
        except Exception as e:
            print(f"Error extracting metadata: {e}")
        
        # If no timestamp from EXIF, use current time
        if not metadata['timestamp']:
            metadata['timestamp'] = datetime.now().strftime("%d/%m/%y %H:%M")
        else:
            # Convert EXIF timestamp format to desired format
            try:
                dt = datetime.strptime(metadata['timestamp'], "%Y:%m:%d %H:%M:%S")
                metadata['timestamp'] = dt.strftime("%d/%m/%y %H:%M")
            except:
                metadata['timestamp'] = datetime.now().strftime("%d/%m/%y %H:%M")
        
        return metadata

    def reset_session_timer(self, user_id):
        """Reset session timer untuk user"""
        if user_id in self.session_timers:
            # Cancel timer yang sudah ada
            if self.session_timers[user_id]['warning_timer']:
                self.session_timers[user_id]['warning_timer'].cancel()
            if self.session_timers[user_id]['timeout_timer']:
                self.session_timers[user_id]['timeout_timer'].cancel()
        
        # Buat timer baru
        warning_timer = threading.Timer(SESSION_WARNING_TIME, self.send_session_warning, [user_id])
        timeout_timer = threading.Timer(SESSION_TIMEOUT_TIME, self.timeout_session, [user_id])
        
        self.session_timers[user_id] = {
            'warning_timer': warning_timer,
            'timeout_timer': timeout_timer,
            'last_activity': time.time()
        }
        
        warning_timer.start()
        timeout_timer.start()
        
        print(f"🕐 Session timer reset for user {user_id}")

    def send_session_warning(self, user_id):
        """Kirim peringatan session timeout"""
        try:
            if user_id in self.user_sessions:
                # Import asyncio untuk menjalankan coroutine
                import asyncio
                
                # Buat event loop baru jika belum ada
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Jalankan coroutine
                if loop.is_running():
                    # Jika loop sudah berjalan, schedule task
                    asyncio.create_task(self._send_warning_message(user_id))
                else:
                    # Jika loop belum berjalan, jalankan coroutine
                    loop.run_until_complete(self._send_warning_message(user_id))
                
                print(f"⚠️ Warning sent to user {user_id}")
        except Exception as e:
            print(f"Error sending warning to user {user_id}: {e}")

    async def _send_warning_message(self, user_id):
        """Helper method untuk mengirim pesan warning"""
        try:
            from telegram import Bot
            bot = Bot(token=self.token)
            
            session = self.user_sessions.get(user_id)
            if session:
                message = (
                    f"⚠️ PERINGATAN TIMEOUT SESSION\n\n"
                    f"🕐 Sesi pembuatan laporan Anda sudah tidak aktif selama 15 menit.\n\n"
                    f"📋 Laporan yang sedang dibuat:\n"
                    f"🆔 ID: {session['id']}\n"
                    f"👤 Teknisi: {session['nama']}\n\n"
                    f"⏰ Sesi akan berakhir otomatis dalam 15 menit lagi jika tidak ada aktivitas.\n"
                    f"🗑️ Folder dan semua foto yang sudah diupload akan terhapus otomatis.\n\n"
                    f"💡 Ketik /start atau pilih menu untuk melanjutkan sesi."
                )
                
                await bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            print(f"Error in _send_warning_message: {e}")

    def timeout_session(self, user_id):
        """Handle session timeout - hapus session dan folder"""
        try:
            if user_id in self.user_sessions:
                session = self.user_sessions[user_id]
                
                # Hapus folder dan semua file di dalamnya
                if session.get('folder_id'):
                    self.delete_folder_and_contents(session['folder_id'])
                
                # Hapus session
                del self.user_sessions[user_id]
                
                # Hapus timer
                if user_id in self.session_timers:
                    del self.session_timers[user_id]
                
                # Kirim notifikasi timeout
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                if loop.is_running():
                    asyncio.create_task(self._send_timeout_message(user_id))
                else:
                    loop.run_until_complete(self._send_timeout_message(user_id))
                
                print(f"⏰ Session timed out for user {user_id}")
        except Exception as e:
            print(f"Error timing out session for user {user_id}: {e}")

    async def _send_timeout_message(self, user_id):
        """Helper method untuk mengirim pesan timeout"""
        try:
            from telegram import Bot
            bot = Bot(token=self.token)
            
            message = (
                f"⏰ SESSION BERAKHIR\n\n"
                f"🚫 Sesi pembuatan laporan Anda telah berakhir karena tidak ada aktivitas selama 30 menit.\n\n"
                f"🗑️ Folder laporan dan semua foto yang sudah diupload telah dihapus otomatis.\n\n"
                f"📝 Silakan ketik /start untuk membuat laporan baru."
            )
            
            await bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            print(f"Error in _send_timeout_message: {e}")

    def delete_folder_and_contents(self, folder_id):
        """Hapus folder dan semua isinya dari Google Drive"""
        try:
            if not folder_id:
                return
            
            # Dapatkan semua file dalam folder
            results = self.service_drive.files().list(
                q=f"'{folder_id}' in parents",
                fields="files(id, name)"
            ).execute()
            
            files = results.get('files', [])
            
            # Hapus setiap file
            for file in files:
                try:
                    self.service_drive.files().delete(fileId=file['id']).execute()
                    print(f"🗑️ Deleted file: {file['name']}")
                except Exception as e:
                    print(f"❌ Error deleting file {file['name']}: {e}")
            
            # Hapus folder itu sendiri
            try:
                self.service_drive.files().delete(fileId=folder_id).execute()
                print(f"🗑️ Deleted folder: {folder_id}")
            except Exception as e:
                print(f"❌ Error deleting folder {folder_id}: {e}")
                
        except Exception as e:
            print(f"❌ Error in delete_folder_and_contents: {e}")

    def clear_session_timer(self, user_id):
        """Clear session timer ketika session selesai"""
        if user_id in self.session_timers:
            try:
                if self.session_timers[user_id]['warning_timer']:
                    self.session_timers[user_id]['warning_timer'].cancel()
                if self.session_timers[user_id]['timeout_timer']:
                    self.session_timers[user_id]['timeout_timer'].cancel()
                del self.session_timers[user_id]
                print(f"🕐 Session timer cleared for user {user_id}")
            except Exception as e:
                print(f"⚠️ Error clearing timer for user {user_id}: {e}")
                # Force remove from dict even if error
                try:
                    del self.session_timers[user_id]
                except:
                    pass
                
    # ========================================
    # TAMBAHAN BARU: STATUS MONITORING & BROADCAST
    # ========================================

    def add_user_to_broadcast_list(self, user_id):
        """Tambah user ke daftar broadcast dan simpan ke file"""
        was_new_user = user_id not in self.broadcast_users
        
        self.broadcast_users.add(user_id)
        self.active_users.add(user_id)
        
        # Auto save to file when new user is added
        if was_new_user:
            self.save_users_to_file()
            print(f"👥 New user {user_id} added and saved to file")


    async def broadcast_message(self, message, exclude_user_id=None):
        """Kirim pesan broadcast ke semua user yang terdaftar"""
        if not self.broadcast_users:
            print("📢 No users to broadcast to")
            return
        
        successful = 0
        failed = 0
        
        for user_id in self.broadcast_users.copy():  # Use copy to avoid modification during iteration
            if exclude_user_id and user_id == exclude_user_id:
                continue
                
            try:
                from telegram import Bot
                bot = Bot(token=self.token)
                await bot.send_message(chat_id=user_id, text=message)
                successful += 1
                print(f"📤 Broadcast sent to user {user_id}")
            except Exception as e:
                failed += 1
                print(f"❌ Failed to send broadcast to user {user_id}: {e}")
                # Remove user jika bot di-block
                if "blocked" in str(e).lower() or "forbidden" in str(e).lower():
                    self.broadcast_users.discard(user_id)
        
        print(f"📊 Broadcast summary: {successful} sent, {failed} failed")
        
        # TAMBAHAN: Detail debug untuk shutdown
        if failed > 0:
            print(f"⚠️ {failed} notifications failed to send")
        if successful > 0:
            print(f"✅ {successful} shutdown notifications sent successfully")
        else:
            print("❌ No shutdown notifications were sent!")
            
    async def broadcast_message_sequential(self, message, exclude_user_id=None):
        """Kirim pesan broadcast ke semua user secara berurutan dengan delay"""
        if not self.broadcast_users:
            print("📢 No users to broadcast to")
            return
        
        successful = 0
        failed = 0
        
        print(f"🚀 Starting sequential broadcast to {len(self.broadcast_users)} users...")
        
        for i, user_id in enumerate(self.broadcast_users.copy(), 1):  # Enumerate untuk tracking
            if exclude_user_id and user_id == exclude_user_id:
                continue
                
            try:
                from telegram import Bot
                bot = Bot(token=self.token)
                
                print(f"📤 Sending to user {user_id} ({i}/{len(self.broadcast_users)})...")
                await bot.send_message(chat_id=user_id, text=message)
                successful += 1
                print(f"✅ Successfully sent to user {user_id}")
                
                # Delay antar pengiriman untuk menghindari rate limit
                if i < len(self.broadcast_users):  # Tidak delay setelah user terakhir
                    await asyncio.sleep(1)  # 1 detik delay
                    
            except Exception as e:
                failed += 1
                print(f"❌ Failed to send to user {user_id}: {e}")
                # Remove user jika bot di-block
                if "blocked" in str(e).lower() or "forbidden" in str(e).lower():
                    self.broadcast_users.discard(user_id)
                    print(f"🚫 Removed blocked user {user_id}")
        
        print(f"📊 Sequential broadcast completed: {successful} sent, {failed} failed")
        return successful, failed

    async def server_startup_notification(self):
        """Kirim notifikasi server startup"""
        startup_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        message = (
            f"🟢 SERVER BOT AKTIF\n\n"
            f"✅ Bot Laporan Teknisi telah diaktifkan kembali\n\n"
            f"⏰ Waktu aktif: {startup_time}\n"
            f"🔧 Status: Siap melayani\n"
            f"📡 Server: Online\n\n"
            f"💡 Ketik /start untuk mulai menggunakan bot\n"
            f"📊 Ketik /status untuk cek status server"
        )
        
        await self.broadcast_message(message)
        print(f"🚀 Startup notification sent at {startup_time}")

    async def server_shutdown_notification(self):
        """Kirim notifikasi server shutdown"""
        if self.is_shutting_down:
            return  # Avoid duplicate notifications
        
        self.is_shutting_down = True
        
        # PERBAIKAN: Load users terlebih dahulu jika belum ada data
        if not self.broadcast_users:
            try:
                print("📂 Force loading ALL users from file for shutdown notification...")
                old_count = len(self.broadcast_users)
                self.load_users_from_file()  # Reload semua user dari file
                print(f"📂 Loaded {len(self.broadcast_users)} users from file (was {old_count} in memory)")
            except Exception as e:
                print(f"❌ Error loading users from file: {e}")
        
        # TAMBAHAN: Debug info sebelum kirim notifikasi
        print(f"📊 Users to notify: {len(self.broadcast_users)} users")
        if self.broadcast_users:
            print(f"📋 User IDs: {list(self.broadcast_users)}")
        else:
            print("⚠️ No users found to notify!")
            return
        
        # Save users before shutdown
        try:
            self.save_users_to_file()
            print("💾 User data saved before shutdown notification")
        except Exception as e:
            print(f"❌ Error saving users before shutdown: {e}")
        
        shutdown_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        uptime = ""
        if self.server_start_time:
            uptime_delta = datetime.now() - self.server_start_time
            hours = int(uptime_delta.total_seconds() // 3600)
            minutes = int((uptime_delta.total_seconds() % 3600) // 60)
            uptime = f"\n⏱️ Uptime: {hours} jam {minutes} menit"
        
        message = (
            f"🔴 SERVER BOT NONAKTIF\n\n"
            f"⚠️ Bot Laporan Teknisi telah berhenti{uptime}\n\n"
            f"⏰ Waktu berhenti: {shutdown_time}\n"
            f"🔧 Status: Maintenance\n"
            f"📡 Server: Offline\n\n"
            f"⏳ Bot akan aktif kembali setelah maintenance selesai\n"
            f"📞 Hubungi administrator jika ada keperluan mendesak"
        )
        
        print(f"📤 Sending shutdown notification to {len(self.broadcast_users)} users...")
        await self.broadcast_message_sequential(message)  # GANTI dengan sequential
        print(f"🛑 Shutdown notification completed at {shutdown_time}")

    def get_server_status(self):
        """Get detailed server status"""
        try:
            # System info
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Bot specific info
            active_sessions = len(self.user_sessions)
            completed_reports = len(self.completed_reports)
            total_users = len(self.active_users)
            broadcast_users = len(self.broadcast_users)
            
            # Uptime calculation
            uptime = ""
            if self.server_start_time:
                uptime_delta = datetime.now() - self.server_start_time
                days = uptime_delta.days
                hours = int(uptime_delta.seconds // 3600)
                minutes = int((uptime_delta.seconds % 3600) // 60)
                
                if days > 0:
                    uptime = f"{days} hari {hours} jam {minutes} menit"
                else:
                    uptime = f"{hours} jam {minutes} menit"
            
            return {
                'cpu_percent': cpu_percent,
                'memory_used': memory.percent,
                'disk_used': disk.percent,
                'active_sessions': active_sessions,
                'completed_reports': completed_reports,
                'total_users': total_users,
                'broadcast_users': broadcast_users,
                'uptime': uptime,
                'start_time': self.server_start_time.strftime("%d/%m/%Y %H:%M:%S") if self.server_start_time else "Unknown"
            }
            
        except Exception as e:
            print(f"Error getting server status: {e}")
            return None

    async def handle_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user_id = update.effective_user.id
        self.add_user_to_broadcast_list(user_id)
        
        status = self.get_server_status()
        
        if not status:
            await update.message.reply_text(
                "❌ Gagal mendapatkan status server\n\n"
                "🔧 Silakan coba lagi atau hubungi administrator"
            )
            return
        
        # Status emoji based on performance
        cpu_emoji = "🟢" if status['cpu_percent'] < 70 else "🟡" if status['cpu_percent'] < 90 else "🔴"
        memory_emoji = "🟢" if status['memory_used'] < 70 else "🟡" if status['memory_used'] < 90 else "🔴"
        disk_emoji = "🟢" if status['disk_used'] < 70 else "🟡" if status['disk_used'] < 90 else "🔴"
        
        status_message = (
            f"📊 STATUS SERVER BOT\n\n"
            f"🟢 Status: ONLINE & AKTIF\n"
            f"⏰ Mulai: {status['start_time']}\n"
            f"⏱️ Uptime: {status['uptime']}\n\n"
            f"💻 PERFORMA SISTEM:\n"
            f"{cpu_emoji} CPU: {status['cpu_percent']:.1f}%\n"
            f"{memory_emoji} RAM: {status['memory_used']:.1f}%\n"
            f"{disk_emoji} Disk: {status['disk_used']:.1f}%\n\n"
            f"🤖 STATISTIK BOT:\n"
            f"👥 Total pengguna: {status['total_users']}\n"
            f"📢 Subscribe notifikasi: {status['broadcast_users']}\n"
            f"⚡ Sesi aktif: {status['active_sessions']}\n"
            f"📦 Laporan siap kirim: {status['completed_reports']}\n\n"
            f"✅ Semua sistem berfungsi normal"
        )
        
        # Add warning if performance is poor
        if status['cpu_percent'] > 80 or status['memory_used'] > 80:
            status_message += f"\n\n⚠️ PERINGATAN: Server dalam beban tinggi"
        
        await update.message.reply_text(status_message)
        
    async def handle_save_users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /saveusers command for manual backup"""
        user_id = update.effective_user.id
        
        # Add user to broadcast list if not already added
        self.add_user_to_broadcast_list(user_id)
        
        try:
            self.save_users_to_file()
            await update.message.reply_text(
                f"💾 USER DATA BERHASIL DISIMPAN\n\n"
                f"👥 Total users: {len(self.active_users)}\n"
                f"📢 Subscribe notifikasi: {len(self.broadcast_users)}\n"
                f"📁 File: users.json\n"
                f"⏰ Waktu: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
                f"✅ Data user telah tersimpan dengan aman"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error menyimpan data user: {e}")

    async def handle_load_users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /loadusers command for manual reload"""
        user_id = update.effective_user.id
        
        old_count = len(self.broadcast_users)
        
        try:
            self.load_users_from_file()
            # Add current user to ensure they get notifications
            self.add_user_to_broadcast_list(user_id)
            
            await update.message.reply_text(
                f"📂 USER DATA BERHASIL DIMUAT\n\n"
                f"📊 Sebelumnya: {old_count} users\n"
                f"📊 Sekarang: {len(self.broadcast_users)} users\n"
                f"📁 File: users.json\n"
                f"⏰ Waktu: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
                f"✅ Data user telah dimuat ulang"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error memuat data user: {e}")

    def create_metadata_overlay(self, filepath, metadata, location_data=None):
        """Add metadata overlay to the image with adaptive layout"""
        try:
            from PIL import ImageDraw, ImageFont
            import textwrap
            
            with Image.open(filepath) as img:
                # Create a copy to work with
                img_copy = img.copy()
                draw = ImageDraw.Draw(img_copy)
                
                img_width, img_height = img_copy.size
                
                # Determine font size based on image resolution
                if img_width > 2000:
                    font_size = 32  # Large images
                    padding = 15
                    line_spacing = 40
                elif img_width > 1200:
                    font_size = 28  # Medium images
                    padding = 12
                    line_spacing = 35
                else:
                    font_size = 24  # Small images
                    padding = 10
                    line_spacing = 30
                
                # Try to use a font with adaptive size
                try:
                    font = ImageFont.truetype("arial.ttf", font_size)
                except:
                    try:
                        # Try other common fonts
                        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
                    except:
                        font = ImageFont.load_default()
                
                # Calculate max text width (use 90% of image width for very long addresses)
                max_text_width = int(img_width * 0.9)
                
                # Prepare overlay text with word wrapping
                overlay_lines = []
                
                if metadata.get('timestamp'):
                    overlay_lines.append(f"📅 {metadata['timestamp']}")
                
                # Add real-time location data if provided
                if location_data:
                    if location_data.get('coordinates'):
                        overlay_lines.append(f"📍 {location_data['coordinates']}")
                    
                    if location_data.get('address'):
                        # Calculate how many characters fit in one line
                        avg_char_width = draw.textlength("A", font=font)
                        chars_per_line = max(20, int((max_text_width - padding * 2) / avg_char_width))
                        
                        # Wrap address text to fit multiple lines
                        address_prefix = "🏠 "
                        address_text = location_data['address']
                        
                        # Split long address into multiple lines
                        wrapped_address = textwrap.fill(
                            address_text, 
                            width=chars_per_line - len(address_prefix),
                            break_long_words=False,
                            break_on_hyphens=False
                        )
                        
                        # Add prefix to first line and proper indentation to subsequent lines
                        address_lines = wrapped_address.split('\n')
                        overlay_lines.append(f"{address_prefix}{address_lines[0]}")
                        
                        # Add continuation lines with proper indentation
                        for line in address_lines[1:]:
                            overlay_lines.append(f"   {line}")  # 3 spaces for indent
                
                if metadata.get('camera_info'):
                    overlay_lines.append(f"📷 {metadata['camera_info']}")
                
                if overlay_lines:
                    # Calculate actual text dimensions for each line
                    line_widths = []
                    line_heights = []
                    
                    for line in overlay_lines:
                        bbox = draw.textbbox((0, 0), line, font=font)
                        line_width = bbox[2] - bbox[0]
                        line_height = bbox[3] - bbox[1]
                        line_widths.append(line_width)
                        line_heights.append(line_height)
                    
                    # Calculate background dimensions
                    max_line_width = max(line_widths)
                    total_text_height = sum(line_heights) + (line_spacing - max(line_heights)) * (len(overlay_lines) - 1)
                    
                    # Ensure minimum and maximum sizes
                    text_bg_width = min(max_line_width + (padding * 2), max_text_width)
                    text_bg_height = total_text_height + (padding * 2)
                    
                    # Position overlay at bottom-left for better readability with long text
                    bg_x1 = padding
                    bg_y1 = img_height - text_bg_height - padding
                    bg_x2 = bg_x1 + text_bg_width
                    bg_y2 = img_height - padding
                    
                    # If overlay is too tall, position it at top instead
                    if bg_y1 < padding:
                        bg_y1 = padding
                        bg_y2 = bg_y1 + text_bg_height
                    
                    # Draw semi-transparent background with rounded corners effect
                    # Main background
                    # Draw semi-transparent background with rounded corners effect
                    # Main background - more transparent
                    draw.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], fill=(0, 0, 0, 80))

                    # Add border for better visibility - more transparent
                    draw.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], outline=(255, 255, 255, 60), width=1)
                    
                    # Draw text with proper spacing
                    current_y = bg_y1 + padding
                    
                    for i, line in enumerate(overlay_lines):
                        line_height = line_heights[i]
                        
                        # Center text horizontally within the background
                        line_width = line_widths[i]
                        text_x = bg_x1 + padding
                        
                        # Add shadow effect for better readability
                        # Add shadow effect for better readability - more subtle
                        draw.text((text_x + 1, current_y + 1), line, fill=(0, 0, 0, 100), font=font)
                        draw.text((text_x, current_y), line, fill="white", font=font)
                        
                        current_y += line_spacing
                    
                    # Save the modified image with higher quality
                    output_path = filepath.replace('.jpg', '_with_metadata.jpg')
                    img_copy.save(output_path, 'JPEG', quality=95, optimize=True)
                    return output_path
        
        except Exception as e:
            print(f"Error creating metadata overlay: {e}")
            import traceback
            traceback.print_exc()
        
        return filepath

        
    def authenticate_google(self):
        """Authenticate with Google APIs"""
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        
        self.service_drive = build('drive', 'v3', credentials=creds)
        self.service_sheets = build('sheets', 'v4', credentials=creds)
        print("✅ Google APIs authenticated successfully!")

    # ========================================
    # OPSI 2: TEST CONNECTION DENGAN POSISI CUSTOM
    # ========================================


    def test_spreadsheet_connection(self):
        """Test if we can read from the spreadsheet"""
        try:
            # Try to read the first few rows
            result = self.service_sheets.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='Sheet1!A1:I10'
            ).execute()
            
            # UNCOMMENT jika menggunakan posisi tabel custom
            # result = self.service_sheets.spreadsheets().values().get(
            #     spreadsheetId=self.spreadsheet_id,
            #     range=f'Sheet1!{self.table_start_col}{self.table_start_row}:{self.table_end_col}{self.table_start_row + 10}'
            # ).execute()
            
            values = result.get('values', [])
            print("✅ Successfully connected to spreadsheet!")
            print(f"Found {len(values)} rows")
            if values:
                print(f"Headers: {values[0]}")
            return True
            
        except Exception as e:
            print(f"❌ Error connecting to spreadsheet: {e}")
            return False

    def get_spreadsheet_info(self):
        """Get spreadsheet metadata"""
        try:
            spreadsheet = self.service_sheets.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            title = spreadsheet.get('properties', {}).get('title', 'Unknown')
            print(f"Spreadsheet title: {title}")
            
            sheets = spreadsheet.get('sheets', [])
            for sheet in sheets:
                sheet_title = sheet.get('properties', {}).get('title', 'Unknown')
                print(f"Sheet found: {sheet_title}")
                
            return True
            
        except Exception as e:
            print(f"Error getting spreadsheet info: {e}")
            return False

    def create_folder(self, folder_name, parent_folder_id="1mLsCBEqEb0R4_pX75-xmpRE1023H6A90"):
        """Create folder in Google Drive"""
        try:
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_folder_id:
                folder_metadata['parents'] = [parent_folder_id]
            
            folder = self.service_drive.files().create(body=folder_metadata).execute()
            print(f"✅ Folder created: {folder_name}")
            return folder.get('id')
        except Exception as e:
            print(f"❌ Error creating folder: {e}")
            return None

    def upload_to_drive(self, file_path, file_name, folder_id):
        """Upload file to Google Drive"""
        try:
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            media = MediaFileUpload(file_path, resumable=True)
            uploaded_file = self.service_drive.files().create(
                body=file_metadata, 
                media_body=media
            ).execute()
            print(f"✅ File uploaded: {file_name}")
            return uploaded_file.get('id')
        except Exception as e:
            print(f"❌ Error uploading file: {e}")
            return None

    def get_folder_link(self, folder_id):
        """Get shareable link for Google Drive folder"""
        return f"https://drive.google.com/drive/folders/{folder_id}"

    def update_spreadsheet(self, laporan_data):
        """Update Google Spreadsheet with report data"""
        try:
            # Get current date
            current_date = datetime.now().strftime("%d/%m/%Y")
            
            # First, get the current number of rows to determine the next row number
            result = self.service_sheets.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range='Sheet1!A:A'
            ).execute()
            
            values = result.get('values', [])
            next_row_number = len(values)  # This will be the row number (starting from 1 for header)
            
            # UNCOMMENT jika menggunakan posisi tabel custom
            # result = self.service_sheets.spreadsheets().values().get(
            #     spreadsheetId=self.spreadsheet_id,
            #     range=f'Sheet1!{self.table_start_col}:{self.table_start_col}'
            # ).execute()
            # 
            # values = result.get('values', [])
            # rows_before_table = self.table_start_row - 1
            # actual_data_rows = max(0, len(values) - rows_before_table)
            # next_row_number = actual_data_rows + 1
            
            # DEFAULT: Struktur kolom A sampai I
            # A: No, B: ID, C: Tanggal, D: Nama teknisi, E: odp, F: odc, G: kabel dropcore, H: speed test, I: Foto Eviden

            
            # Structure data according to your spreadsheet columns:
            # A: No, B: ID, C: Tanggal, D: Nama teknisi, E: odp, F: odc, G: kabel dropcore, H: speed test, I: Foto Eviden
            row_data = [
                str(next_row_number),  # A: No (row number)
                laporan_data['id'],    # B: ID
                current_date,          # C: Tanggal
                laporan_data['nama'],  # D: Nama teknisi
                laporan_data.get('odp', ''),  # E: odp
                laporan_data.get('odc', ''),  # F: odc
                laporan_data.get('kabel_dropcore', ''),  # G: kabel dropcore
                laporan_data.get('speed_test', ''),      # H: speed test
                laporan_data['folder_link']  # I: Foto Eviden (Link Folder)
            ]
            
            # UNCOMMENT untuk menambah kolom baru
            # CONTOH 1: Menambah 1 kolom Kabel UTP (menjadi A sampai J)
            # row_data = [
            #     str(next_row_number),                    # A: No
            #     laporan_data['id'],                      # B: ID
            #     current_date,                            # C: Tanggal
            #     laporan_data['nama'],                    # D: Nama teknisi
            #     laporan_data.get('odp', ''),            # E: odp
            #     laporan_data.get('odc', ''),            # F: odc
            #     laporan_data.get('kabel_dropcore', ''),  # G: kabel dropcore
            #     laporan_data.get('kabel_utp', ''),       # H: kabel utp (BARU!)
            #     laporan_data.get('speed_test', ''),      # I: speed test
            #     laporan_data['folder_link']              # J: Foto Eviden
            # ]

            # CONTOH 2: Untuk posisi tabel custom (misal mulai dari D5)
            # actual_row_position = self.table_start_row + len(values) - (self.table_start_row - 1)
            # write_range = f'Sheet1!{self.table_start_col}{actual_row_position}:{self.table_end_col}{actual_row_position}'
            # 
            # body = {'values': [row_data]}
            # result = self.service_sheets.spreadsheets().values().update(
            #     spreadsheetId=self.spreadsheet_id,
            #     range=write_range,
            #     valueInputOption='RAW',
            #     body=body
            # ).execute()
            
            body = {'values': [row_data]}
            result = self.service_sheets.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range='Sheet1!A:I',  #  # Ubah ke A:J, A:K, A:L sesuai jumlah kolom baru
                valueInputOption='RAW',
                body=body
            ).execute()
            
            print(f"✅ Successfully added row to spreadsheet: {row_data}")
            return True
            
        except Exception as e:
            print(f"❌ Error updating spreadsheet: {e}")
            traceback.print_exc()  # This will show the full error traceback
            return False

    def has_active_session(self, user_id):
        """Check if user has active session (sedang dalam proses pembuatan)"""
        return (user_id in self.user_sessions and 
                self.user_sessions[user_id].get('id') and 
                self.user_sessions[user_id].get('nama'))

    def has_completed_report(self, user_id):
        """Check if user has completed report (sudah dikemas, siap kirim)"""
        return user_id in self.completed_reports

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Unknown"
        
        # TAMBAHAN BARU: Register user untuk broadcast dan reset timer
        was_new = user_id not in self.broadcast_users
        self.add_user_to_broadcast_list(user_id)
        
        # Log new user registration
        if was_new:
            print(f"👋 New user registered: {user_name} (ID: {user_id})")

        
        # TAMBAHAN BARU: Reset session timer jika user memiliki session aktif
        if self.has_active_session(user_id):
            self.reset_session_timer(user_id)
        
        # Determine available options based on user status
        keyboard = []
        status_message = "🤖 Selamat datang di Bot Laporan Teknisi!\n\n"
        
        # Always show create new report option
        keyboard.append([KeyboardButton("📝 Buat Laporan Baru")])
        
        # Show continue option if has active session
        if self.has_active_session(user_id):
            keyboard.append([KeyboardButton("📸 Lanjutkan Upload Foto")])
            keyboard.append([KeyboardButton("✅ Selesai & Kemas Laporan")])
            keyboard.append([KeyboardButton("🗑️ Hapus Foto")])
            keyboard.append([KeyboardButton("❌ Batalkan Laporan")])
            
            session = self.user_sessions[user_id]
            total_photos = sum(len(photos) for photos in session['photos'].values())
            status_message += f"📋 Laporan Aktif (Dalam Proses):\n"
            status_message += f"🆔 ID: {session['id']}\n"
            status_message += f"👤 Teknisi: {session['nama']}\n"
            status_message += f"📷 Total foto: {total_photos}\n\n"
        
        # Show send option if has completed report
        if self.has_completed_report(user_id):
            keyboard.append([KeyboardButton("📤 Kirim Laporan ke Spreadsheet")])
            
            report = self.completed_reports[user_id]
            total_photos = sum(len(photos) for photos in report['photos'].values())
            status_message += f"📦 Laporan Siap Kirim:\n"
            status_message += f"🆔 ID: {report['id']}\n"
            status_message += f"👤 Teknisi: {report['nama']}\n"
            status_message += f"📷 Total foto: {total_photos}\n\n"
        
        if not self.has_active_session(user_id) and not self.has_completed_report(user_id):
            status_message += "📋 Silakan buat laporan baru untuk memulai.\n\n"
        
        status_message += "Pilih menu yang tersedia:"
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(status_message, reply_markup=reply_markup)

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle main menu selections"""
        text = update.message.text
        user_id = update.effective_user.id
        
        # TAMBAHAN BARU: Reset timer untuk setiap aktivitas user
        if self.has_active_session(user_id):
            self.reset_session_timer(user_id)
        
        if text in ["📝 Buat Laporan Baru", "Buat Laporan Baru"]:
            return await self.start_laporan(update, context)
        elif text in ["📸 Lanjutkan Upload Foto", "Lanjutkan Upload Foto"]:
            if self.has_active_session(user_id):
                await self.show_photo_options(update, context)
                return UPLOAD_FOTO
            else:
                await update.message.reply_text("❌ Tidak ada laporan aktif. Silakan buat laporan baru terlebih dahulu.")
                await self.start(update, context)
        elif text in ["✅ Selesai & Kemas Laporan", "Selesai & Kemas Laporan"]:
            if self.has_active_session(user_id):
                return await self.kemas_laporan(update, context)
            else:
                await update.message.reply_text("❌ Tidak ada laporan aktif. Silakan buat laporan baru terlebih dahulu.")
                await self.start(update, context)
        elif text in ["📤 Kirim Laporan ke Spreadsheet", "Kirim Laporan"]:
            if self.has_completed_report(user_id):
                return await self.kirim_laporan(update, context)
            else:
                await update.message.reply_text("❌ Tidak ada laporan yang siap dikirim. Silakan selesaikan laporan terlebih dahulu.")
                await self.start(update, context)
        elif text in ["🗑️ Hapus Foto", "Hapus Foto"]:
            if self.has_active_session(user_id):
                return await self.ulangi_upload(update, context)
            else:
                await update.message.reply_text("❌ Tidak ada laporan aktif. Silakan buat laporan baru terlebih dahulu.")
                await self.start(update, context)
        # TAMBAHAN BARU: Handler untuk batalkan laporan
        elif text in ["❌ Batalkan Laporan", "Batalkan Laporan"]:
            if self.has_active_session(user_id):
                return await self.batalkan_laporan(update, context)
            else:
                await update.message.reply_text("❌ Tidak ada laporan aktif untuk dibatalkan.")
                await self.start(update, context)

    async def start_laporan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start creating a new report"""
        user_id = update.effective_user.id
        
        # Clear any existing sessions and completed reports for this user
        if user_id in self.user_sessions:
            # TAMBAHAN BARU: Clear timer sebelum hapus session
            self.clear_session_timer(user_id)
            del self.user_sessions[user_id]
        if user_id in self.completed_reports:
            del self.completed_reports[user_id]
        
        # Initialize new session
        self.user_sessions[user_id] = {
            'id': None,
            'nama': None,
            'current_photo_type': None,
            'photos': {},
            'folder_id': None
        }
        
        # TAMBAHAN BARU: Set timer untuk session baru
        # TAMBAHAN BARU: Set timer untuk session baru
        self.reset_session_timer(user_id)
        
        # Tambahkan keyboard dengan opsi batalkan sejak awal
        keyboard = [
            [KeyboardButton("❌ Batalkan Laporan")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "📝 Masukkan ID Laporan:",
            reply_markup=reply_markup
        )
        return INPUT_ID

    async def input_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle ID input"""
        user_id = update.effective_user.id
        # TAMBAHAN BARU: Reset timer untuk aktivitas user
        if user_id in self.user_sessions:
            self.reset_session_timer(user_id)
        
        laporan_id = update.message.text.strip()
        
        if not laporan_id:
            await update.message.reply_text("❌ ID Laporan tidak boleh kosong. Silakan masukkan ID yang valid:")
            return INPUT_ID
        
        self.user_sessions[user_id]['id'] = laporan_id
        
        # Tambahkan keyboard dengan opsi batalkan setelah input ID
        keyboard = [
            [KeyboardButton("❌ Batalkan Laporan")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "👤 Masukkan Nama Teknisi:",
            reply_markup=reply_markup
        )
        return INPUT_NAMA

    async def input_nama(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle technician name input"""
        user_id = update.effective_user.id
        # TAMBAHAN BARU: Reset timer untuk aktivitas user
        if user_id in self.user_sessions:
            self.reset_session_timer(user_id)
        
        nama = update.message.text.strip()
        
        if not nama:
            await update.message.reply_text("❌ Nama Teknisi tidak boleh kosong. Silakan masukkan nama yang valid:")
            return INPUT_NAMA
        
        self.user_sessions[user_id]['nama'] = nama
        
        # Buat folder untuk laporan ini
        folder_name = f"Laporan_{self.user_sessions[user_id]['id']}_{nama}"
        folder_id = self.create_folder(folder_name)
        
        if not folder_id:
            await update.message.reply_text("❌ Gagal membuat folder. Silakan coba lagi.")
            return INPUT_NAMA
            
        self.user_sessions[user_id]['folder_id'] = folder_id
        
        # Tambahkan keyboard dengan opsi pembatalan setelah folder dibuat
        # Tambahkan keyboard dengan opsi batalkan setelah folder dibuat
        keyboard = [
            [KeyboardButton("📸 Mulai Upload Foto")],
            [KeyboardButton("❌ Batalkan Laporan")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"✅ Folder laporan berhasil dibuat!\n📁 Nama folder: {folder_name}\n\n"
            f"📸 Silakan pilih 'Mulai Upload Foto' untuk melanjutkan.",
            reply_markup=reply_markup
        )
        return UPLOAD_FOTO
    
    async def handle_start_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle mulai upload foto"""
            user_id = update.effective_user.id
            
            if user_id in self.user_sessions:
                self.reset_session_timer(user_id)
            
            await self.show_photo_options(update, context)
            return UPLOAD_FOTO
    
    # ========================================
    # OPSI 3: SHOW PHOTO OPTIONS DENGAN HEADER BARU
    # ========================================

    async def show_photo_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show photo upload options"""
        keyboard = [
            [InlineKeyboardButton("📡 ODP", callback_data="photo_odp")],
            [InlineKeyboardButton("🔌 ODC", callback_data="photo_odc")],
            [InlineKeyboardButton("🔗 Kabel Dropcore", callback_data="photo_kabel_dropcore")],
            [InlineKeyboardButton("⚡ Speed Test", callback_data="photo_speed_test")]
        ]
        
        # UNCOMMENT untuk menambah header/kolom baru
        # CONTOH 1: Menambah Kabel UTP
        # keyboard = [
        #     [InlineKeyboardButton("📡 ODP", callback_data="photo_odp")],
        #     [InlineKeyboardButton("🔌 ODC", callback_data="photo_odc")],
        #     [InlineKeyboardButton("🔗 Kabel Dropcore", callback_data="photo_kabel_dropcore")],
        #     [InlineKeyboardButton("🌐 Kabel UTP", callback_data="photo_kabel_utp")],      # BARU!
        #     [InlineKeyboardButton("⚡ Speed Test", callback_data="photo_speed_test")]
        # ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Tambahkan keyboard menu utama dengan opsi batalkan
        main_keyboard = [
            [KeyboardButton("❌ Batalkan Laporan")]
        ]
        main_reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "📸 Pilih jenis foto yang akan diupload:",
            reply_markup=reply_markup
        )

    # ========================================
    # OPSI 6: UPDATE SEMUA FUNCTION YANG MENGGUNAKAN TYPE_NAMES
    # ========================================

    async def photo_type_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo type selection"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        photo_type = query.data.replace("photo_", "")
        
        if user_id not in self.user_sessions:
            await query.edit_message_text("❌ Sesi tidak ditemukan. Silakan mulai dari awal.")
            return ConversationHandler.END
        
        self.user_sessions[user_id]['current_photo_type'] = photo_type
        
        # ========================================
        # OPSI 4: TYPE NAMES DENGAN HEADER BARU
        # ========================================

        type_names = {
            'odp': 'ODP',
            'odc': 'ODC', 
            'kabel_dropcore': 'Kabel Dropcore',
            'speed_test': 'Speed Test'
        }

        
        # UNCOMMENT untuk menambah kolom baru:
        # CONTOH 1: Menambah Kabel UTP
        # type_names = {
        #     'odp': 'ODP',
        #     'odc': 'ODC', 
        #     'kabel_dropcore': 'Kabel Dropcore',
        #     'kabel_utp': 'Kabel UTP',          # BARU!
        #     'speed_test': 'Speed Test'
        # }

        
        await query.edit_message_text(
            f"📍 LANGKAH 1: Bagikan Lokasi\n\n"
            f"Untuk foto {type_names[photo_type]}, mohon bagikan lokasi Anda saat ini terlebih dahulu.\n\n"
            f"📱 Tekan tombol 'Kirim Lokasi Saya' di bawah untuk menggunakan GPS perangkat Anda.\n\n"
            f"⚠️ Pastikan GPS/lokasi pada perangkat Anda sudah aktif!"
        )

        # Send location request keyboard
        location_markup = ReplyKeyboardMarkup([[KeyboardButton("📍 Kirim Lokasi Saya", request_location=True)]], 
                                            resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="👆 Tekan tombol di atas untuk mengirim lokasi, atau ketik 'lewati' untuk melanjutkan tanpa lokasi:",
            reply_markup=location_markup
        )
        
        return REQUEST_LOCATION

    async def handle_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle location received from user"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions:
            await update.message.reply_text("❌ Sesi tidak ditemukan. Silakan mulai dari awal.")
            return ConversationHandler.END
        
        location_data = None
        
        if update.message.location:
            # Get location coordinates
            latitude = update.message.location.latitude
            longitude = update.message.location.longitude
            
            await update.message.reply_text("⏳ Mendapatkan alamat dari koordinat GPS...")
            
            # Get address from coordinates
            address = self.get_address_from_coordinates(latitude, longitude)
            
            location_data = {
                'coordinates': f"{latitude:.6f}, {longitude:.6f}",
                'address': address if address else "Alamat tidak dapat ditemukan"
            }
            
            # Store location data in session
            self.user_sessions[user_id]['current_location'] = location_data
            
            await update.message.reply_text(
                f"✅ Lokasi berhasil diterima!\n\n"
                f"📍 Koordinat: {location_data['coordinates']}\n"
                f"🏠 Alamat: {location_data['address'][:100]}...\n\n" if len(location_data['address']) > 100 
                else f"🏠 Alamat: {location_data['address']}\n\n"
                f"📸 LANGKAH 2: Sekarang silakan upload foto:"
            )
            
        elif update.message.text and update.message.text.lower() in ['lewati', 'skip']:
            # User chose to skip location
            self.user_sessions[user_id]['current_location'] = None
            await update.message.reply_text(
                f"⏭️ Lokasi dilewati.\n\n"
                f"📸 Silakan upload foto:"
            )
        else:
            await update.message.reply_text(
                "❌ Harap kirim lokasi dengan menekan tombol 'Kirim Lokasi Saya' atau ketik 'lewati' untuk melanjutkan tanpa lokasi."
            )
            return REQUEST_LOCATION
        
        # Remove location keyboard
        keyboard = [
            [KeyboardButton("📸 Lanjutkan Upload Foto")],
            [KeyboardButton("✅ Selesai & Kemas Laporan")],
            [KeyboardButton("🗑️ Hapus Foto")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "💡 Tips: Pastikan foto jelas dan tidak buram",
            reply_markup=reply_markup
        )
        
        return UPLOAD_FOTO

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo upload with metadata extraction"""
        user_id = update.effective_user.id
        # TAMBAHAN BARU: Reset timer untuk aktivitas user
        if user_id in self.user_sessions:
            self.reset_session_timer(user_id)
        
        if user_id not in self.user_sessions or not self.user_sessions[user_id]['current_photo_type']:
            await update.message.reply_text("❌ Silakan pilih jenis foto terlebih dahulu.")
            await self.show_photo_options(update, context)
            return UPLOAD_FOTO
        
        try:
            # Download foto
            photo = update.message.photo[-1]  # Get highest resolution
            file = await context.bot.get_file(photo.file_id)
            
            photo_type = self.user_sessions[user_id]['current_photo_type']
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{photo_type}_{timestamp}.jpg"
            filepath = f"temp_{filename}"
            
            await update.message.reply_text("⏳ Mengupload foto ke Google Drive...")
            
            await file.download_to_drive(filepath)
            
            # Extract metadata from photo
            metadata = self.extract_photo_metadata(filepath)
            
            # Get current location data from session
            location_data = self.user_sessions[user_id].get('current_location')
            
            # Create image with metadata overlay
            final_filepath = self.create_metadata_overlay(filepath, metadata, location_data)
            
            # If overlay creation failed, use original file
            if final_filepath == filepath:
                print("Using original file without overlay")
            else:
                # Remove original temp file and rename the overlay file
                if os.path.exists(filepath):
                    os.remove(filepath)
                filepath = final_filepath
                filename = f"{photo_type}_{timestamp}_with_metadata.jpg"
            
            # Upload ke Google Drive
            folder_id = self.user_sessions[user_id]['folder_id']
            file_id = self.upload_to_drive(filepath, filename, folder_id)
            
            # Hapus file temporary
            if os.path.exists(filepath):
                os.remove(filepath)
            
            if not file_id:
                await update.message.reply_text("❌ Gagal mengupload foto. Silakan coba lagi.")
                return UPLOAD_FOTO
            
            # Simpan info foto dengan metadata
            if photo_type not in self.user_sessions[user_id]['photos']:
                self.user_sessions[user_id]['photos'][photo_type] = []
            
            photo_info = {
                'file_id': file_id,
                'filename': filename,
                'metadata': metadata,
                'location_data': location_data
            }
            
            self.user_sessions[user_id]['photos'][photo_type].append(photo_info)
            
            type_names = {
                'odp': 'ODP',
                'odc': 'ODC',
                'kabel_dropcore': 'Kabel Dropcore',
                'speed_test': 'Speed Test'
            }
            
            metadata_text = ""
            if metadata['timestamp']:
                metadata_text += f"📅 Waktu: {metadata['timestamp']}\n"
            if location_data:
                if location_data.get('coordinates'):
                    metadata_text += f"📍 Koordinat: {location_data['coordinates']}\n"
                if location_data.get('address'):
                    metadata_text += f"🏠 Lokasi: {location_data['address'][:50]}...\n" if len(location_data['address']) > 50 else f"🏠 Lokasi: {location_data['address']}\n"
            if metadata['camera_info']:
                metadata_text += f"📷 Kamera: {metadata['camera_info']}\n"
            
            await update.message.reply_text(
                f"✅ Foto {type_names[photo_type]} berhasil diupload!\n\n"
                f"📊 Informasi Foto:\n{metadata_text}\n"
                f"📝 Sekarang masukkan deskripsi untuk foto ini:"
            )
            
            return INPUT_DESKRIPSI
            
        except Exception as e:
            print(f"Error handling photo: {e}")
            await update.message.reply_text("❌ Terjadi kesalahan saat mengupload foto. Silakan coba lagi.")
            return UPLOAD_FOTO


    async def input_deskripsi(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle description input"""
        user_id = update.effective_user.id
        deskripsi = update.message.text.strip()
        
        if not deskripsi:
            await update.message.reply_text("❌ Deskripsi tidak boleh kosong. Silakan masukkan deskripsi:")
            return INPUT_DESKRIPSI
        
        photo_type = self.user_sessions[user_id]['current_photo_type']
        
        # Update deskripsi foto terakhir
        if photo_type in self.user_sessions[user_id]['photos']:
            last_photo_index = len(self.user_sessions[user_id]['photos'][photo_type]) - 1
            self.user_sessions[user_id]['photos'][photo_type][last_photo_index]['deskripsi'] = deskripsi
        
        # Reset current photo type
        self.user_sessions[user_id]['current_photo_type'] = None
        
        # Show upload summary and options
        total_photos = sum(len(photos) for photos in self.user_sessions[user_id]['photos'].values())
        
        keyboard = [
            [KeyboardButton("📸 Lanjutkan Upload Foto")],
            [KeyboardButton("✅ Selesai & Kemas Laporan")],
            [KeyboardButton("🗑️ Hapus Foto")],
            [KeyboardButton("❌ Batalkan Laporan")]  # Tambahkan opsi batalkan
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        # Show detailed photo summary
        photo_summary = []
        type_names = {
            'odp': 'ODP',
            'odc': 'ODC',
            'kabel_dropcore': 'Kabel Dropcore',
            'speed_test': 'Speed Test'
        }
        
        for photo_type, photos in self.user_sessions[user_id]['photos'].items():
            photo_summary.append(f"• {type_names[photo_type]}: {len(photos)} foto")
        
        await update.message.reply_text(
            f"✅ Deskripsi berhasil disimpan!\n\n"
            f"📊 Status Upload Saat Ini:\n"
            f"🆔 ID: {self.user_sessions[user_id]['id']}\n"
            f"👤 Teknisi: {self.user_sessions[user_id]['nama']}\n\n"
            f"📸 Foto yang sudah diupload:\n" + "\n".join(photo_summary) + f"\n\n"
            f"📷 Total foto: {total_photos}\n\n"
            f"Pilih aksi selanjutnya:",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END

    async def kemas_laporan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kemas/Selesaikan laporan untuk siap dikirim"""
        user_id = update.effective_user.id
        
        if not self.has_active_session(user_id):
            await update.message.reply_text("❌ Tidak ada laporan aktif.")
            await self.start(update, context)
            return
        
        session = self.user_sessions[user_id]
        
        if not session['photos']:
            await update.message.reply_text("❌ Belum ada foto yang diupload. Silakan upload foto terlebih dahulu.")
            await self.start(update, context)
            return
        
        # Show confirmation with detailed summary
        photo_summary = []
        type_names = {
            'odp': 'ODP',
            'odc': 'ODC',
            'kabel_dropcore': 'Kabel Dropcore',
            'speed_test': 'Speed Test'
        }
        
        for photo_type, photos in session['photos'].items():
            photo_summary.append(f"• {type_names[photo_type]}: {len(photos)} foto")
            for i, photo in enumerate(photos):
                desc = photo.get('deskripsi', 'Tidak ada deskripsi')
                photo_summary.append(f"  - Foto {i+1}: {desc}")
        
        total_photos = sum(len(photos) for photos in session['photos'].values())
        
        keyboard = [
            [InlineKeyboardButton("✅ Ya, Kemas Laporan", callback_data="kemas_confirm")],
            [InlineKeyboardButton("❌ Batal, Lanjut Upload", callback_data="kemas_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📦 KONFIRMASI PENGEMASAN LAPORAN\n\n"
            f"🆔 ID: {session['id']}\n"
            f"👤 Teknisi: {session['nama']}\n"
            f"📅 Tanggal: {datetime.now().strftime('%d/%m/%Y')}\n"
            f"📷 Total foto: {total_photos}\n\n"
            f"📸 Detail foto:\n" + "\n".join(photo_summary) + "\n\n"
            f"❓ Apakah Anda yakin sudah selesai upload dan ingin mengemas laporan?\n\n"
            f"⚠️ Setelah dikemas, laporan tidak bisa diedit lagi dan siap untuk dikirim ke spreadsheet.",
            reply_markup=reply_markup
        )

    async def kemas_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle packaging confirmation callback"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        if query.data == "kemas_confirm":
            if not self.has_active_session(user_id):
                await query.edit_message_text("❌ Sesi tidak ditemukan.")
                return
            
            # Pindahkan dari active session ke completed reports
            session = self.user_sessions[user_id]
            self.completed_reports[user_id] = {
                'id': session['id'],
                'nama': session['nama'],
                'photos': session['photos'],
                'folder_id': session['folder_id'],
                'created_at': datetime.now()
            }
            
            # Hapus dari active session
            del self.user_sessions[user_id]
            
            # TAMBAHAN BARU: Clear timer ketika laporan dikemas
            self.clear_session_timer(user_id)
            
            # Show success message with new menu
            keyboard = [
                [KeyboardButton("📤 Kirim Laporan ke Spreadsheet")],
                [KeyboardButton("📝 Buat Laporan Baru")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            total_photos = sum(len(photos) for photos in self.completed_reports[user_id]['photos'].values())
            
            await query.edit_message_text(
                f"✅ LAPORAN BERHASIL DIKEMAS!\n\n"
                f"📦 Laporan Anda telah selesai dan siap untuk dikirim:\n"
                f"🆔 ID: {self.completed_reports[user_id]['id']}\n"
                f"👤 Teknisi: {self.completed_reports[user_id]['nama']}\n"
                f"📷 Total foto: {total_photos}\n\n"
                f"🎯 Sekarang Anda dapat mengirim laporan ke spreadsheet atau membuat laporan baru."
            )
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Pilih aksi selanjutnya:",
                reply_markup=reply_markup
            )
            
        else:  # kemas_cancel
            keyboard = [
                [KeyboardButton("📸 Lanjutkan Upload Foto")],
                [KeyboardButton("✅ Selesai & Kemas Laporan")],
                [KeyboardButton("🗑️ Hapus Foto")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await query.edit_message_text("❌ Pengemasan laporan dibatalkan. Anda dapat melanjutkan upload foto.")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Pilih aksi selanjutnya:",
                reply_markup=reply_markup
            )

    async def kirim_laporan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kirim laporan yang sudah dikemas ke spreadsheet"""
        user_id = update.effective_user.id
        
        if not self.has_completed_report(user_id):
            await update.message.reply_text("❌ Tidak ada laporan yang siap dikirim.")
            await self.start(update, context)
            return
        
        await update.message.reply_text("⏳ Sedang mengirim laporan ke spreadsheet...")
        
        report = self.completed_reports[user_id]
        
        # Siapkan data untuk spreadsheet dengan metadata
        laporan_data = await self.prepare_laporan_data_with_metadata(report)
        
        if self.update_spreadsheet(laporan_data):
            # Prepare summary
            photo_summary = []
            type_names = {
                'odp': 'ODP',
                'odc': 'ODC',
                'kabel_dropcore': 'Kabel Dropcore',
                'speed_test': 'Speed Test'
            }
            
            for photo_type, photos in report['photos'].items():
                photo_summary.append(f"• {type_names[photo_type]}: {len(photos)} foto")
            
            # Reset keyboard to initial state
            keyboard = [
                [KeyboardButton("📝 Buat Laporan Baru")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ LAPORAN BERHASIL DIKIRIM KE SPREADSHEET!\n\n"
                f"📋 Detail Laporan:\n"
                f"🆔 ID: {report['id']}\n"
                f"👤 Teknisi: {report['nama']}\n"
                f"📅 Tanggal: {datetime.now().strftime('%d/%m/%Y')}\n\n"
                f"📸 Foto yang dikirim:\n" + "\n".join(photo_summary) + "\n\n"
                f"📁 Link folder: {laporan_data['folder_link']}\n\n"
                f"🎉 Data telah tersimpan di spreadsheet dengan metadata lengkap!\n\n"
                f"Terima kasih! Anda dapat membuat laporan baru.",
                reply_markup=reply_markup
            )
            
            # Clear completed report
            del self.completed_reports[user_id]
        else:
            await update.message.reply_text(
                "❌ Gagal mengirim laporan ke spreadsheet.\n"
                "Foto sudah tersimpan di Google Drive, namun gagal menyimpan ke spreadsheet.\n"
                "Silakan hubungi administrator."
            )

    # ========================================
    # FUNGSI TAMBAHAN YANG DIPERLUKAN
    # ========================================
    # Tambahkan fungsi ini juga (setelah fungsi kirim_laporan di atas)

    async def prepare_laporan_data_with_metadata(self, report):
        """Prepare report data with metadata for spreadsheet"""
        laporan_data = {
            'id': report['id'],
            'nama': report['nama'],
            'folder_link': self.get_folder_link(report['folder_id'])
        }
        
        # Gabungkan semua deskripsi dan metadata berdasarkan jenis foto
        for photo_type, photos in report['photos'].items():
            deskripsi_list = []
            metadata_list = []
            
            for photo in photos:
                desc = photo.get('deskripsi', 'Tidak ada deskripsi')
                deskripsi_list.append(desc)
                
                # Add metadata info
                if 'metadata' in photo:
                    metadata = photo['metadata']
                    meta_info = []
                    if metadata.get('timestamp'):
                        meta_info.append(f"Waktu: {metadata['timestamp']}")
                    if metadata.get('coordinates'):
                        meta_info.append(f"GPS: {metadata['coordinates']}")
                    if metadata.get('location'):
                        meta_info.append(f"Lokasi: {metadata['location'][:30]}...")
                    
                    if meta_info:
                        metadata_list.append(f"[{'; '.join(meta_info)}]")
            
            # Combine descriptions with metadata
            combined_info = []
            for i, desc in enumerate(deskripsi_list):
                if i < len(metadata_list):
                    combined_info.append(f"{desc} {metadata_list[i]}")
                else:
                    combined_info.append(desc)
            
            laporan_data[photo_type] = '; '.join(combined_info)
        
        return laporan_data

    async def ulangi_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle re-upload photos"""
        user_id = update.effective_user.id
        
        if not self.has_active_session(user_id):
            await update.message.reply_text("❌ Tidak ada laporan aktif.")
            await self.start(update, context)
            return
        
        # Tampilkan foto yang sudah diupload
        session = self.user_sessions[user_id]
        if not session['photos']:
            await update.message.reply_text("❌ Belum ada foto yang diupload.")
            await self.start(update, context)
            return
        
        keyboard = []
        for photo_type, photos in session['photos'].items():
            type_names = {
                'odp': 'ODP',
                'odc': 'ODC',
                'kabel_dropcore': 'Kabel Dropcore', 
                'speed_test': 'Speed Test'
            }
            keyboard.append([InlineKeyboardButton(
                f"🗑️ Hapus {type_names[photo_type]} ({len(photos)} foto)",
                callback_data=f"delete_{photo_type}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🗑️ Pilih jenis foto yang ingin dihapus:",
            reply_markup=reply_markup
        )
        
    async def batalkan_laporan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Konfirmasi pembatalan laporan"""
        user_id = update.effective_user.id
        
        if not self.has_active_session(user_id):
            await update.message.reply_text("❌ Tidak ada laporan aktif untuk dibatalkan.")
            await self.start(update, context)
            return
        
        session = self.user_sessions[user_id]
        total_photos = sum(len(photos) for photos in session['photos'].values())
        
        keyboard = [
            [InlineKeyboardButton("⚠️ Ya, Batalkan Laporan", callback_data="cancel_confirm")],
            [InlineKeyboardButton("↩️ Kembali ke Menu", callback_data="cancel_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚠️ KONFIRMASI PEMBATALAN LAPORAN\n\n"
            f"🆔 ID: {session['id']}\n"
            f"👤 Teknisi: {session['nama']}\n"
            f"📷 Total foto: {total_photos}\n\n"
            f"🚨 PERINGATAN: Tindakan ini akan:\n"
            f"• Menghapus SEMUA foto yang sudah diupload\n"
            f"• Menghapus folder laporan dari Google Drive\n"
            f"• Mengakhiri sesi pembuatan laporan\n\n"
            f"❓ Apakah Anda yakin ingin membatalkan laporan ini?\n\n"
            f"⚠️ Tindakan ini TIDAK DAPAT DIBATALKAN!",
            reply_markup=reply_markup
        )
        
    async def handle_cancel_in_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle pembatalan laporan selama dalam conversation flow"""
            user_id = update.effective_user.id
            
            if not self.has_active_session(user_id):
                await update.message.reply_text("❌ Tidak ada laporan aktif untuk dibatalkan.")
                await self.start(update, context)
                return ConversationHandler.END
            
            session = self.user_sessions[user_id]
            total_photos = sum(len(photos) for photos in session['photos'].values()) if session['photos'] else 0
            
            keyboard = [
                [InlineKeyboardButton("⚠️ Ya, Batalkan Laporan", callback_data="cancel_confirm")],
                [InlineKeyboardButton("↩️ Lanjutkan Laporan", callback_data="cancel_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"⚠️ KONFIRMASI PEMBATALAN LAPORAN\n\n"
                f"🆔 ID: {session['id'] if session.get('id') else 'Belum diisi'}\n"
                f"👤 Teknisi: {session['nama'] if session.get('nama') else 'Belum diisi'}\n"
                f"📷 Total foto: {total_photos}\n\n"
                f"🚨 PERINGATAN: Tindakan ini akan:\n"
                f"• Menghapus SEMUA data yang sudah diinput\n"
                f"• Menghapus folder laporan dari Google Drive (jika sudah dibuat)\n"
                f"• Mengakhiri sesi pembuatan laporan\n\n"
                f"❓ Apakah Anda yakin ingin membatalkan laporan ini?\n\n"
                f"⚠️ Tindakan ini TIDAK DAPAT DIBATALKAN!",
                reply_markup=reply_markup
            )
            
            return ConversationHandler.END
        
    async def cancel_laporan_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle pembatalan laporan callback"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        if query.data == "cancel_confirm":
            if not self.has_active_session(user_id):
                await query.edit_message_text("❌ Sesi tidak ditemukan.")
                return
            
            session = self.user_sessions[user_id]
            folder_id = session.get('folder_id')
            total_photos = sum(len(photos) for photos in session['photos'].values())
            
            # Hapus folder dan semua isinya
            if folder_id:
                self.delete_folder_and_contents(folder_id)
            
            # Clear session timer
            self.clear_session_timer(user_id)
            
            # Hapus session
            del self.user_sessions[user_id]
            
            # Reset keyboard ke initial state
            keyboard = [
                [KeyboardButton("📝 Buat Laporan Baru")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await query.edit_message_text(
                f"✅ LAPORAN BERHASIL DIBATALKAN\n\n"
                f"🗑️ Yang telah dihapus:\n"
                f"• Folder laporan dari Google Drive\n"
                f"• {total_photos} foto yang sudah diupload\n"
                f"• Data sesi pembuatan laporan\n\n"
                f"📝 Anda dapat membuat laporan baru kapan saja."
            )
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Silakan pilih menu:",
                reply_markup=reply_markup
            )
            
        else:  # cancel_back
            keyboard = [
                [KeyboardButton("📸 Lanjutkan Upload Foto")],
                [KeyboardButton("✅ Selesai & Kemas Laporan")],
                [KeyboardButton("🗑️ Hapus Foto")],
                [KeyboardButton("❌ Batalkan Laporan")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await query.edit_message_text("↩️ Pembatalan dibatalkan. Sesi laporan dilanjutkan.")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Pilih aksi selanjutnya:",
                reply_markup=reply_markup
            )

    async def delete_photo_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo deletion"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        photo_type = query.data.replace("delete_", "")
        
        if user_id in self.user_sessions and photo_type in self.user_sessions[user_id]['photos']:
            # Hapus foto dari Google Drive
            for photo in self.user_sessions[user_id]['photos'][photo_type]:
                try:
                    self.service_drive.files().delete(fileId=photo['file_id']).execute()
                    print(f"✅ Deleted file from Drive: {photo['filename']}")
                except Exception as e:
                    print(f"❌ Error deleting file: {e}")
            
            # Hapus dari session
            del self.user_sessions[user_id]['photos'][photo_type]
            
            type_names = {
                'odp': 'ODP',
                'odc': 'ODC',
                'kabel_dropcore': 'Kabel Dropcore',
                'speed_test': 'Speed Test'
            }
            
            # Show updated menu
            keyboard = [
                [KeyboardButton("📸 Lanjutkan Upload Foto")],
                [KeyboardButton("✅ Selesai & Kemas Laporan")],
                [KeyboardButton("🗑️ Hapus Foto")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await query.edit_message_text(
                f"✅ Foto {type_names[photo_type]} berhasil dihapus dari Google Drive!"
            )
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Pilih aksi selanjutnya:",
                reply_markup=reply_markup
            )

    def run(self):
        """Run the bot"""
        print("🚀 Starting Telegram Bot...")
        
        # TAMBAHAN BARU: Set server start time
        self.server_start_time = datetime.now()

        
        # Authenticate Google APIs
        self.authenticate_google()
        
        # Test spreadsheet connection
        print("\n🧪 Testing spreadsheet connection...")
        if self.test_spreadsheet_connection():
            self.get_spreadsheet_info()
        else:
            print("❌ Failed to connect to spreadsheet. Please check your SPREADSHEET_ID and permissions.")
            return
        
        print("\n✅ All systems ready! Starting bot...")
        
        try:
            # Create application
            application = Application.builder().token(self.token).build()
            
            # Conversation handler untuk pembuatan laporan
            conv_handler = ConversationHandler(
                entry_points=[
                    MessageHandler(filters.Regex("^(📝 Buat Laporan Baru|Buat Laporan Baru)$"), self.start_laporan),
                    MessageHandler(filters.Regex("^(📸 Lanjutkan Upload Foto|Lanjutkan Upload Foto)$"), self.handle_menu)
                ],
                states={
                    INPUT_ID: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(❌ Batalkan Laporan|Batalkan Laporan)$"), self.input_id),
                        MessageHandler(filters.Regex("^(❌ Batalkan Laporan|Batalkan Laporan)$"), self.handle_cancel_in_conversation)
                    ],
                    INPUT_NAMA: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(❌ Batalkan Laporan|Batalkan Laporan)$"), self.input_nama),
                        MessageHandler(filters.Regex("^(❌ Batalkan Laporan|Batalkan Laporan)$"), self.handle_cancel_in_conversation)
                    ],
                    REQUEST_LOCATION: [
                        MessageHandler(filters.LOCATION, self.handle_location),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_location)
                    ],
                    UPLOAD_FOTO: [
                        CallbackQueryHandler(self.photo_type_callback, pattern="^photo_"),
                        MessageHandler(filters.PHOTO, self.handle_photo),
                        # Tambahkan handler untuk "Mulai Upload Foto"
                        MessageHandler(filters.Regex("^(📸 Mulai Upload Foto|Mulai Upload Foto)$"), self.handle_start_upload)
                    ],
                    INPUT_DESKRIPSI: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.input_deskripsi)]
                },
                fallbacks=[
                    CommandHandler('start', self.start),
                    MessageHandler(filters.Regex("^(📝 Buat Laporan Baru)$"), self.start_laporan)
                ]
            )
            
            # Add handlers
            application.add_handler(CommandHandler("start", self.start))
            application.add_handler(CommandHandler("status", self.handle_status_command))
            application.add_handler(CommandHandler("saveusers", self.handle_save_users_command))
            application.add_handler(CommandHandler("loadusers", self.handle_load_users_command))
            application.add_handler(conv_handler)
            
            # Handler untuk menu non-conversation
            application.add_handler(MessageHandler(
                filters.Regex("^(✅ Selesai & Kemas Laporan|Selesai & Kemas Laporan)$"), 
                self.handle_menu
            ))
            application.add_handler(MessageHandler(
                filters.Regex("^(📤 Kirim Laporan ke Spreadsheet|Kirim Laporan)$"), 
                self.handle_menu
            ))
            application.add_handler(MessageHandler(
                filters.Regex("^(🗑️ Hapus Foto|Hapus Foto)$"), 
                self.handle_menu
            ))
            application.add_handler(MessageHandler(
                filters.Regex("^(❌ Batalkan Laporan|Batalkan Laporan)$"), 
                self.handle_menu
            ))

            
            # Callback handlers
            application.add_handler(CallbackQueryHandler(self.kemas_callback, pattern="^kemas_"))
            application.add_handler(CallbackQueryHandler(self.delete_photo_callback, pattern="^delete_"))
            # TAMBAHAN BARU: Handler untuk pembatalan laporan
            application.add_handler(CallbackQueryHandler(self.cancel_laporan_callback, pattern="^cancel_"))

            # TAMBAHAN BARU: Handler untuk status command
            application.add_handler(CommandHandler("status", self.handle_status_command))

            # TAMBAHAN BARU: Setup signal handlers untuk graceful shutdown
            def signal_handler(signum, frame):
                print(f"\n🛑 Menerima signal {signum}...")
                
                # PERBAIKAN: Load users sebelum shutdown
                if not self.broadcast_users:
                    try:
                        print("📂 Signal force loading users...")
                        self.load_users_from_file()
                        print(f"📂 Signal loaded {len(self.broadcast_users)} users")
                    except:
                        pass
                
                # PERBAIKAN: Gunakan threading untuk menjalankan async function
                import threading
                import asyncio as signal_asyncio
                
                def run_shutdown_notification():
                    try:
                        # Buat loop baru di thread terpisah
                        loop = signal_asyncio.new_event_loop()
                        signal_asyncio.set_event_loop(loop)
                        
                        print("⏳ Sending shutdown notifications...")
                        loop.run_until_complete(self.server_shutdown_notification())
                        
                        # TAMBAHAN: Tunggu sebentar untuk memastikan pesan terkirim
                        print("⏳ Waiting for messages to be delivered...")
                        loop.run_until_complete(signal_asyncio.sleep(3))
                        
                        loop.close()
                        print("✅ Shutdown notifications completed")
                        
                    except Exception as e:
                        print(f"❌ Error in signal shutdown thread: {e}")
                
                # Jalankan dalam thread terpisah untuk menghindari konflik event loop
                shutdown_thread = threading.Thread(target=run_shutdown_notification)
                shutdown_thread.start()
                
                # Tunggu thread selesai dengan timeout maksimal 30 detik
                shutdown_thread.join(timeout=30)
                
                if shutdown_thread.is_alive():
                    print("⚠️ Shutdown notification timeout, forcing exit...")
                else:
                    print("✅ Shutdown notification thread completed")
                
                # Save users final
                try:
                    self.save_users_to_file()
                    print("💾 Final save completed")
                except:
                    pass
                
                # Force exit after notification
                print("🚪 Exiting now...")
                import os
                os._exit(0)


            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

            # TAMBAHAN BARU: Register atexit untuk cleanup
            # PERBAIKAN: Fix atexit asyncio import
            # TAMBAHAN BARU: Register atexit untuk cleanup dengan threading
            def cleanup_on_exit():
                if not self.is_shutting_down:
                    try:
                        import threading
                        import asyncio as exit_asyncio
                        
                        def run_cleanup():
                            try:
                                loop = exit_asyncio.new_event_loop()
                                exit_asyncio.set_event_loop(loop)
                                loop.run_until_complete(self.server_shutdown_notification())
                                loop.close()
                            except:
                                pass
                        
                        cleanup_thread = threading.Thread(target=run_cleanup)
                        cleanup_thread.start()
                        cleanup_thread.join(timeout=15)  # Max 15 detik
                    except:
                        pass

            atexit.register(cleanup_on_exit)

            print("🤖 Bot is running... Press Ctrl+C to stop")

            # Run polling dengan proper cleanup
            try:
                # PERBAIKAN: Fix asyncio import conflict
                import asyncio as aio
                
                async def post_init_callback(application):
                    """Callback setelah bot siap"""
                    try:
                        print("📡 Bot is ready, sending startup notification...")
                        # Wait a bit to ensure bot is fully initialized
                        await aio.sleep(2)
                        await self.server_startup_notification()
                    except Exception as e:
                        print(f"❌ Error sending startup notification: {e}")

                # Set post init callback
                application.post_init = post_init_callback

                
                application.run_polling(drop_pending_updates=True)
            except KeyboardInterrupt:
                print("\n🛑 Menerima sinyal Ctrl+C...")
                print("🔄 Mengirim notifikasi shutdown...")
                
                # PERBAIKAN: Load users sebelum shutdown notification
                if not self.broadcast_users:
                    try:
                        print("📂 Ctrl+C force loading ALL users from file...")
                        old_count = len(self.broadcast_users)
                        self.load_users_from_file()  # Paksa reload dari file
                        print(f"📂 Ctrl+C loaded {len(self.broadcast_users)} users from file (was {old_count} in memory)")
                    except Exception as e:
                        print(f"❌ Error loading users from file: {e}")
                
                # PERBAIKAN: Send shutdown notification dengan waktu tunggu yang cukup
                try:
                    import asyncio as shutdown_asyncio
                    loop = shutdown_asyncio.new_event_loop()
                    shutdown_asyncio.set_event_loop(loop)
                    
                    print("⏳ Mengirim notifikasi shutdown (mohon tunggu)...")
                    successful, failed = loop.run_until_complete(self.server_shutdown_notification())
                    
                    # TAMBAHAN: Tunggu lebih lama jika masih ada yang gagal
                    if failed > 0:
                        print(f"⚠️ {failed} notifications failed, retrying in 3 seconds...")
                        loop.run_until_complete(asyncio.sleep(3))
                    
                    print("✅ Shutdown notification process completed")
                    loop.close()
                    
                except Exception as e:
                    print(f"❌ Error sending shutdown notification: {e}")
                
                # TAMBAHAN: Save users before complete shutdown
                try:
                    self.save_users_to_file()
                    print("💾 Final user data save completed")
                except Exception as e:
                    print(f"❌ Error in final user save: {e}")
                
                print("🔄 Menghentikan bot dengan aman...")
                
                # Cleanup semua session timers
                print("⏰ Membersihkan session timers...")
                for user_id in list(self.session_timers.keys()):
                    try:
                        if self.session_timers[user_id]['warning_timer']:
                            self.session_timers[user_id]['warning_timer'].cancel()
                        if self.session_timers[user_id]['timeout_timer']:
                            self.session_timers[user_id]['timeout_timer'].cancel()
                    except:
                        pass
                self.session_timers.clear()
                
                # Stop application gracefully
                print("🔄 Menghentikan application...")
                try:
                    # TAMBAHAN: Tunggu sebentar sebelum force stop
                    import time
                    time.sleep(2)  # Tunggu 2 detik untuk memastikan semua pesan terkirim
                    
                    # Force stop application
                    if hasattr(application, 'stop'):
                        application.stop()
                    if hasattr(application, 'shutdown'):
                        application.shutdown()
                except:
                    pass
                
                print("🚪 Bot telah berhenti")
                
            except Exception as e:
                print(f"❌ Error saat menjalankan bot: {e}")
                
            finally:
                print("🧹 Pembersihan akhir...")
                
                # Final cleanup
                try:
                    # TAMBAHAN BARU: Final save users
                    try:
                        self.save_users_to_file()
                        print("💾 Emergency user data save completed")
                    except:
                        pass
                    
                    # Clear all timers
                    for user_id in list(self.session_timers.keys()):
                        try:
                            if self.session_timers[user_id]['warning_timer']:
                                self.session_timers[user_id]['warning_timer'].cancel()
                            if self.session_timers[user_id]['timeout_timer']:
                                self.session_timers[user_id]['timeout_timer'].cancel()
                        except:
                            pass
                    self.session_timers.clear()
                    
                    # Force exit if needed
                    import threading
                    active_threads = threading.active_count()
                    if active_threads > 1:
                        print(f"⚠️ Masih ada {active_threads-1} thread aktif, memaksa keluar...")
                        import os
                        os._exit(0)
                    
                except:
                    pass
                
                print("💻 Terminal siap digunakan kembali")
                print("✨ Ketik perintah baru atau jalankan ulang bot")


        except Exception as e:
            print(f"❌ Error starting bot: {e}")
            import traceback
            traceback.print_exc()
            print("\n🔧 Troubleshooting:")
            print("1. Check your bot token is correct")
            print("2. Make sure bot token starts with numbers followed by ':'")
            print("3. Verify internet connection")

if __name__ == "__main__":
    # Check telegram library version
    try:
        import telegram
        print(f"📦 python-telegram-bot version: {telegram.__version__}")
    except Exception as e:
        print(f"❌ Error checking telegram version: {e}")
    
    # Konfigurasi - GANTI DENGAN TOKEN DAN SPREADSHEET ID ANDA
    BOT_TOKEN = "rahasia"  # Ganti dengan token bot Anda
    SPREADSHEET_ID = "1y_VwDtLa_G-gQeTDeEGkN7W8hwHliORhIAKSJEgYPhM"  # Ganti dengan ID spreadsheet Anda
    
    # Validasi konfigurasi
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or SPREADSHEET_ID == "YOUR_SPREADSHEET_ID_HERE":
        print("❌ Error: Please set your BOT_TOKEN and SPREADSHEET_ID in the code!")
        print("📝 Instructions:")
        print("1. Replace BOT_TOKEN with your actual Telegram bot token")
        print("2. Replace SPREADSHEET_ID with your actual Google Spreadsheet ID")
        exit(1)
    
    bot = TelegramBot(BOT_TOKEN, SPREADSHEET_ID)
    bot.run()