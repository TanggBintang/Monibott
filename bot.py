import os
import re
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from datetime import datetime

# Fixed imports - use absolute paths
from services.google_service import GoogleService
from services.session_service import SessionService
from config.spreadsheet_config import SpreadsheetConfig

# States untuk ConversationHandler
SELECT_REPORT_TYPE, INPUT_ID, INPUT_DATA, CONFIRM_DATA, UPLOAD_PHOTO, INPUT_PHOTO_DESC = range(6)

class TelegramBot:
    def __init__(self, token, spreadsheet_id):
        self.token = token
        self.spreadsheet_id = spreadsheet_id
        
        # Initialize services
        self.google_service = GoogleService()
        self.session_service = SessionService(self.google_service)
        self.spreadsheet_config = SpreadsheetConfig()
        
        # Authenticate Google
        if not self.google_service.authenticate():
            raise Exception("Failed to authenticate Google APIs")

    def delete_folder_if_exists(self, user_id):
        """Delete folder if session exists"""
        session = self.session_service.get_session(user_id)
        if session and session.get('folder_id'):
            try:
                self.google_service.service_drive.files().delete(fileId=session['folder_id']).execute()
                print(f"✅ Folder deleted for user {user_id}")
            except Exception as e:
                print(f"❌ Error deleting folder: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        try:
            user_id = update.effective_user.id
            username = update.effective_user.first_name or "User"
            
            # Clean up any existing session
            self.session_service.end_session(user_id)
            
            # Buat sesi baru
            self.session_service.create_session(user_id)
            
            keyboard = [
                [KeyboardButton("Non B2B"), KeyboardButton("BGES")],
                [KeyboardButton("Squad")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(
                f"👋 Halo {username}!\n\n"
                f"📋 Selamat datang di Report Bot\n"
                f"Silakan pilih jenis laporan:",
                reply_markup=reply_markup
            )
            return SELECT_REPORT_TYPE
            
        except Exception as e:
            print(f"Error in start handler: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan. Silakan coba lagi dengan /start"
            )
            return ConversationHandler.END

    async def select_report_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle report type selection"""
        try:
            user_id = update.effective_user.id
            message_text = update.message.text.strip()
            
            print(f"User {user_id} selected: '{message_text}'")  # Debug log
            
            # Handle normal report type selection
            valid_types = ['Non B2B', 'BGES', 'Squad']
            if message_text not in valid_types:
                keyboard = [
                    [KeyboardButton("Non B2B"), KeyboardButton("BGES")],
                    [KeyboardButton("Squad")]
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(
                    "❌ Pilihan tidak valid.\n"
                    "Silakan pilih salah satu jenis laporan yang tersedia:",
                    reply_markup=reply_markup
                )
                return SELECT_REPORT_TYPE
            
            # Update session
            session = self.session_service.get_session(user_id)
            if not session:
                await update.message.reply_text(
                    "❌ Session tidak ditemukan. Silakan mulai ulang dengan /start"
                )
                return ConversationHandler.END
                
            self.session_service.update_session(user_id, {'report_type': message_text})
            
            keyboard = [[KeyboardButton("❌ Batalkan")]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(
                f"✅ Jenis laporan: {message_text}\n\n"
                f"🎫 Silakan masukkan ID Ticket:",
                reply_markup=reply_markup
            )
            return INPUT_ID
            
        except Exception as e:
            print(f"Error in select_report_type: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan. Silakan mulai ulang dengan /start"
            )
            return ConversationHandler.END

    async def input_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle ID input"""
        try:
            user_id = update.effective_user.id
            ticket_id = update.message.text.strip()
            
            print(f"User {user_id} entered ticket ID: '{ticket_id}'")  # Debug log
            
            if ticket_id == "❌ Batalkan":
                return await self.cancel_report(update, context)
            
            if not ticket_id or len(ticket_id) < 2:
                keyboard = [[KeyboardButton("❌ Batalkan")]]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(
                    "❌ ID Ticket tidak valid. Silakan masukkan ID Ticket yang benar:",
                    reply_markup=reply_markup
                )
                return INPUT_ID
            
            # Get and validate session
            session = self.session_service.get_session(user_id)
            if not session:
                await update.message.reply_text(
                    "❌ Session tidak ditemukan. Silakan mulai ulang dengan /start"
                )
                return ConversationHandler.END
            
            # Update session
            self.session_service.update_session(user_id, {'id_ticket': ticket_id})
            
            # Buat folder di Google Drive
            folder_name = f"{session['report_type']}_{ticket_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            folder_id = self.google_service.create_folder(folder_name)
            
            if not folder_id:
                await update.message.reply_text(
                    "❌ Gagal membuat folder di Google Drive. Silakan coba lagi."
                )
                return INPUT_ID
            
            self.session_service.update_session(user_id, {'folder_id': folder_id})
            
            # Kirim format pengisian
            folder_link = self.google_service.get_folder_link(folder_id)
            report_format = (
                f"✅ Folder berhasil dibuat!\n\n"
                f"📋 **Detail Laporan:**\n"
                f"• Report Type: {session['report_type']}\n"
                f"• ID Ticket: {ticket_id}\n"
                f"• Folder Drive: {folder_link}\n\n"
                f"📝 **Format Laporan** (Salin dan isi):\n\n"
                f"Customer Name: \n"
                f"Service No: \n"
                f"Segment: \n"
                f"Teknisi 1: \n"
                f"Teknisi 2: \n"
                f"STO: \n"
                f"Valins ID: "
            )
            
            keyboard = [[KeyboardButton("❌ Batalkan")]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(report_format, reply_markup=reply_markup)
            return INPUT_DATA
            
        except Exception as e:
            print(f"Error in input_id: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan. Silakan coba lagi."
            )
            return INPUT_ID

    async def input_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle data input"""
        try:
            user_id = update.effective_user.id
            message_text = update.message.text.strip()
            
            print(f"User {user_id} entered data: {message_text[:100]}...")  # Debug log
            
            if message_text == "❌ Batalkan":
                return await self.cancel_report(update, context)
            
            # Parse data dari format
            data = {}
            lines = message_text.split('\n')
            
            for line in lines:
                if ':' in line and line.strip():
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    if key and value:  # Only add if both key and value exist
                        data[key] = value
            
            print(f"Parsed data: {data}")  # Debug log
            
            # Validasi data yang diperlukan
            required_fields = ['Customer Name', 'Service No', 'Segment', 'Teknisi 1', 'Teknisi 2', 'STO', 'Valins ID']
            missing_fields = [field for field in required_fields if field not in data or not data[field]]
            
            if missing_fields:
                keyboard = [[KeyboardButton("❌ Batalkan")]]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(
                    f"❌ **Data tidak lengkap!**\n\n"
                    f"Field yang belum diisi: **{', '.join(missing_fields)}**\n\n"
                    f"Silakan kirim ulang format dengan data yang lengkap.\n\n"
                    f"**Contoh format yang benar:**\n"
                    f"Customer Name: John Doe\n"
                    f"Service No: 12345\n"
                    f"Segment: Enterprise\n"
                    f"Teknisi 1: Budi\n"
                    f"Teknisi 2: Sari\n"
                    f"STO: Jakarta\n"
                    f"Valins ID: VAL123",
                    reply_markup=reply_markup
                )
                return INPUT_DATA
            
            # Get session and validate
            session = self.session_service.get_session(user_id)
            if not session:
                await update.message.reply_text(
                    "❌ Session tidak ditemukan. Silakan mulai ulang dengan /start"
                )
                return ConversationHandler.END
            
            # Simpan data ke session
            report_data = {
                'report_type': session['report_type'],
                'id_ticket': session['id_ticket'],
                'folder_link': self.google_service.get_folder_link(session['folder_id']),
                'reported': datetime.now().strftime("%d/%m/%Y %H:%M"),
                'customer_name': data['Customer Name'],
                'service_no': data['Service No'],
                'segment': data['Segment'],
                'teknisi_1': data['Teknisi 1'],
                'teknisi_2': data['Teknisi 2'],
                'sto': data['STO'],
                'valins_id': data['Valins ID']
            }
            
            self.session_service.update_session(user_id, {'data': report_data})
            
            # Tampilkan konfirmasi
            return await self.show_confirmation(update, context)
            
        except Exception as e:
            print(f"Error in input_data: {e}")
            keyboard = [[KeyboardButton("❌ Batalkan")]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                "❌ Terjadi kesalahan saat memproses data. Silakan coba lagi:",
                reply_markup=reply_markup
            )
            return INPUT_DATA

    async def show_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show confirmation screen"""
        try:
            user_id = update.effective_user.id
            session = self.session_service.get_session(user_id)
            
            if not session or not session.get('data'):
                await update.message.reply_text(
                    "❌ Data tidak ditemukan. Silakan mulai ulang dengan /start"
                )
                return ConversationHandler.END
            
            report_data = session['data']
            
            # Info foto
            photo_info = ""
            if session.get('photos') and len(session['photos']) > 0:
                photo_info = f"\n📷 **Foto Eviden:** {len(session['photos'])} foto\n"
                for i, photo in enumerate(session['photos'], 1):
                    photo_info += f"   {i}. {photo['name']}\n"
            else:
                photo_info = "\n📷 **Foto Eviden:** Belum ada foto\n"
            
            confirmation_text = (
                f"📋 **KONFIRMASI DATA LAPORAN**\n\n"
                f"🏷️ **Report Type:** {report_data['report_type']}\n"
                f"🎫 **ID Ticket:** {report_data['id_ticket']}\n"
                f"👤 **Customer Name:** {report_data['customer_name']}\n"
                f"📞 **Service No:** {report_data['service_no']}\n"
                f"🏢 **Segment:** {report_data['segment']}\n"
                f"🔧 **Teknisi 1:** {report_data['teknisi_1']}\n"
                f"🔧 **Teknisi 2:** {report_data['teknisi_2']}\n"
                f"🏪 **STO:** {report_data['sto']}\n"
                f"🆔 **Valins ID:** {report_data['valins_id']}"
                f"{photo_info}\n"
                f"Pilih tindakan selanjutnya:"
            )
            
            keyboard = [
                [KeyboardButton("✅ Kirim Laporan"), KeyboardButton("📝 Edit Data")],
                [KeyboardButton("📷 Upload Foto"), KeyboardButton("❌ Batalkan")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
            return CONFIRM_DATA
            
        except Exception as e:
            print(f"Error in show_confirmation: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan. Silakan mulai ulang dengan /start"
            )
            return ConversationHandler.END

    async def confirm_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle data confirmation"""
        try:
            user_id = update.effective_user.id
            choice = update.message.text.strip()
            session = self.session_service.get_session(user_id)
            
            print(f"User {user_id} chose: '{choice}'")  # Debug log
            
            if not session:
                await update.message.reply_text(
                    "❌ Session tidak ditemukan. Silakan mulai ulang dengan /start"
                )
                return ConversationHandler.END
            
            if choice == "✅ Kirim Laporan":
                return await self.send_report(update, context)
                
            elif choice == "📝 Edit Data":
                return await self.edit_data(update, context)
                
            elif choice == "📷 Upload Foto":
                return await self.start_photo_upload(update, context)
                
            elif choice == "❌ Batalkan":
                return await self.cancel_report(update, context)
            
            else:
                # Invalid choice
                await update.message.reply_text(
                    "❌ Pilihan tidak valid. Silakan pilih salah satu opsi yang tersedia."
                )
                return await self.show_confirmation(update, context)
                
        except Exception as e:
            print(f"Error in confirm_data: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan. Silakan coba lagi."
            )
            return CONFIRM_DATA

    async def send_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send report to spreadsheet"""
        try:
            user_id = update.effective_user.id
            session = self.session_service.get_session(user_id)
            
            if not session or not session.get('data'):
                await update.message.reply_text(
                    "❌ Data tidak ditemukan. Silakan mulai ulang dengan /start"
                )
                return ConversationHandler.END
            
            await update.message.reply_text("⏳ Mengirim laporan ke spreadsheet...")
            
            # Kirim ke spreadsheet
            success = self.google_service.update_spreadsheet(
                self.spreadsheet_id,
                self.spreadsheet_config,
                session['data']
            )
            
            if success:
                photo_count = len(session.get('photos', []))
                success_message = "✅ **LAPORAN BERHASIL DIKIRIM!**\n\n"
                success_message += f"📋 Report Type: {session['data']['report_type']}\n"
                success_message += f"🎫 ID Ticket: {session['data']['id_ticket']}\n"
                if photo_count > 0:
                    success_message += f"📷 {photo_count} foto eviden tersimpan di folder Drive.\n"
                success_message += "\nTerima kasih! 🙏"
                
                await update.message.reply_text(
                    success_message,
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
                )
            else:
                await update.message.reply_text(
                    "❌ **Gagal mengirim laporan ke spreadsheet.**\n"
                    "Silakan coba lagi atau hubungi admin.",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
                )
            
            self.session_service.end_session(user_id)
            return ConversationHandler.END
            
        except Exception as e:
            print(f"Error in send_report: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan saat mengirim laporan. Silakan coba lagi."
            )
            return CONFIRM_DATA

    async def edit_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Edit report data"""
        try:
            user_id = update.effective_user.id
            session = self.session_service.get_session(user_id)
            
            if not session or not session.get('data'):
                await update.message.reply_text(
                    "❌ Data tidak ditemukan. Silakan mulai ulang dengan /start"
                )
                return ConversationHandler.END
            
            # Kirim ulang format untuk diedit
            report_data = session['data']
            report_format = (
                f"📝 **EDIT DATA LAPORAN**\n\n"
                f"📋 Report Type: {report_data['report_type']}\n"
                f"🎫 ID Ticket: {report_data['id_ticket']}\n"
                f"📁 Folder Drive: {report_data['folder_link']}\n\n"
                f"📝 **Salin format di bawah dan edit sesuai kebutuhan:**\n\n"
                f"Customer Name: {report_data['customer_name']}\n"
                f"Service No: {report_data['service_no']}\n"
                f"Segment: {report_data['segment']}\n"
                f"Teknisi 1: {report_data['teknisi_1']}\n"
                f"Teknisi 2: {report_data['teknisi_2']}\n"
                f"STO: {report_data['sto']}\n"
                f"Valins ID: {report_data['valins_id']}"
            )
            
            keyboard = [[KeyboardButton("❌ Batalkan")]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(report_format, reply_markup=reply_markup)
            return INPUT_DATA
            
        except Exception as e:
            print(f"Error in edit_data: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan. Silakan coba lagi."
            )
            return CONFIRM_DATA

    async def start_photo_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start photo upload process"""
        try:
            keyboard = [
                [KeyboardButton("📸 Upload Satu-Satu (Custom Nama)")],
                [KeyboardButton("📷 Upload Banyak (Auto Nama)")],
                [KeyboardButton("🔙 Kembali"), KeyboardButton("❌ Batalkan")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(
                "📷 **UPLOAD FOTO EVIDEN**\n\n"
                "⚠️ **PENTING - Cara Upload:**\n"
                "• **Satu-satu**: Upload 1 foto → input nama custom\n"
                "• **Banyak**: Upload beberapa foto → nama otomatis\n\n"
                "📤 **Pilih metode upload:**",
                reply_markup=reply_markup
            )
            return UPLOAD_PHOTO
            
        except Exception as e:
            print(f"Error in start_photo_upload: {e}")
            return await self.show_confirmation(update, context)

    async def upload_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo upload process"""
        try:
            user_id = update.effective_user.id
            message_text = update.message.text.strip() if update.message.text else ""
            
            # Handle menu choices
            if message_text == "📸 Upload Satu-Satu (Custom Nama)":
                context.user_data['upload_mode'] = 'single'
                keyboard = [
                    [KeyboardButton("✅ Selesai Upload"), KeyboardButton("❌ Batalkan")]
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    "📸 **Mode Upload Satu-Satu**\n\n"
                    "Kirimkan foto satu per satu.\n"
                    "Setiap foto akan diminta nama custom.\n\n"
                    "📤 Kirimkan foto pertama:",
                    reply_markup=reply_markup
                )
                return UPLOAD_PHOTO
                
            elif message_text == "📷 Upload Banyak (Auto Nama)":
                context.user_data['upload_mode'] = 'multiple'
                keyboard = [
                    [KeyboardButton("✅ Selesai Upload"), KeyboardButton("❌ Batalkan")]
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    "📷 **Mode Upload Banyak**\n\n"
                    "Kirimkan beberapa foto sekaligus.\n"
                    "Nama akan otomatis: foto_1, foto_2, dst.\n\n"
                    "📤 Kirimkan foto-foto Anda:",
                    reply_markup=reply_markup
                )
                return UPLOAD_PHOTO
            
            elif message_text == "✅ Selesai Upload":
                # Reset upload mode
                if 'upload_mode' in context.user_data:
                    del context.user_data['upload_mode']
                return await self.show_confirmation(update, context)
            
            elif message_text == "🔙 Kembali":
                return await self.show_confirmation(update, context)
                
            elif message_text == "❌ Batalkan":
                return await self.cancel_report(update, context)
            
            # Handle photo upload
            elif update.message.photo:
                return await self.process_photo(update, context)
            
            else:
                await update.message.reply_text(
                    "❌ Pilihan tidak valid atau silakan kirim foto."
                )
                return UPLOAD_PHOTO
                
        except Exception as e:
            print(f"Error in upload_photo: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan saat upload foto. Silakan coba lagi."
            )
            return UPLOAD_PHOTO

    async def process_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process uploaded photo"""
        try:
            user_id = update.effective_user.id
            upload_mode = context.user_data.get('upload_mode', 'single')
            
            if upload_mode == 'single':
                # Store photo for description input
                photo = update.message.photo[-1]
                context.user_data['temp_photo'] = photo
                
                keyboard = [[KeyboardButton("❌ Batalkan")]]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    "📝 **Masukkan nama untuk foto ini:**\n\n"
                    "Contoh: 'sebelum_perbaikan', 'hasil_instalasi', dll\n\n"
                    "💡 Nama akan digunakan sebagai nama file",
                    reply_markup=reply_markup
                )
                return INPUT_PHOTO_DESC
                
            else:  # multiple mode
                return await self.save_photo_auto(update, context)
                
        except Exception as e:
            print(f"Error in process_photo: {e}")
            await update.message.reply_text(
                "❌ Gagal memproses foto. Silakan coba lagi."
            )
            return UPLOAD_PHOTO

    async def save_photo_auto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save photo with automatic naming"""
        try:
            user_id = update.effective_user.id
            session = self.session_service.get_session(user_id)
            
            if not session or not session.get('folder_id'):
                await update.message.reply_text(
                    "❌ Session tidak valid. Silakan mulai ulang."
                )
                return ConversationHandler.END
            
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            
            # Generate automatic filename
            photo_count = len(session.get('photos', [])) + 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"foto_{photo_count}_{timestamp}.jpg"
            filepath = f"temp_{filename}"
            
            await update.message.reply_text("⏳ Mengupload foto...")
            await file.download_to_drive(filepath)
            
            file_id = self.google_service.upload_to_drive(filepath, filename, session['folder_id'])
            
            # Cleanup temp file
            if os.path.exists(filepath):
                os.remove(filepath)
            
            if file_id:
                # Add to photo list
                if 'photos' not in session:
                    session['photos'] = []
                session['photos'].append({
                    'id': file_id,
                    'name': filename
                })
                
                keyboard = [
                    [KeyboardButton("✅ Selesai Upload"), KeyboardButton("❌ Batalkan")]
                ]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                
                await update.message.reply_text(
                    f"✅ **Foto berhasil diupload!**\n"
                    f"📄 Nama file: {filename}\n"
                    f"📷 Total foto: {len(session['photos'])}\n\n"
                    f"Kirim foto lain atau pilih 'Selesai Upload'",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    "❌ Gagal mengupload foto. Silakan coba lagi."
                )
            
            return UPLOAD_PHOTO
            
        except Exception as e:
            print(f"Error in save_photo_auto: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan saat mengupload foto."
            )
            return UPLOAD_PHOTO

    async def input_photo_desc(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo description input"""
        try:
            user_id = update.effective_user.id
            description = update.message.text.strip()
            
            if description == "❌ Batalkan":
                return await self.cancel_report(update, context)
            
            if not description or len(description) < 2:
                await update.message.reply_text(
                    "❌ Nama foto terlalu pendek. Silakan masukkan nama yang lebih deskriptif:"
                )
                return INPUT_PHOTO_DESC
            
            # Clean description for filename
            clean_desc = re.sub(r'[^\w\s-]', '', description).strip()
            clean_desc = re.sub(r'[\s]+', '_', clean_desc)
            
            session = self.session_service.get_session(user_id)
            temp_photo = context.user_data.get('temp_photo')
            
            if temp_photo and session and session.get('folder_id'):
                try:
                    file = await context.bot.get_file(temp_photo.file_id)
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{clean_desc}_{timestamp}.jpg"
                    filepath = f"temp_{filename}"
                    
                    await update.message.reply_text("⏳ Mengupload foto...")
                    await file.download_to_drive(filepath)
                    
                    file_id = self.google_service.upload_to_drive(filepath, filename, session['folder_id'])
                    
                    # Cleanup temp file
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    
                    if file_id:
                        # Add to photo list
                        if 'photos' not in session:
                            session['photos'] = []
                        session['photos'].append({
                            'id': file_id,
                            'name': filename
                        })
                        
                        keyboard = [
                            [KeyboardButton("✅ Selesai Upload"), KeyboardButton("❌ Batalkan")]
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        
                        await update.message.reply_text(
                            f"✅ **Foto berhasil diupload!**\n"
                            f"📄 Nama file: {filename}\n"
                            f"📷 Total foto: {len(session['photos'])}\n\n"
                            f"Kirim foto lain atau pilih 'Selesai Upload'",
                            reply_markup=reply_markup
                        )
                    else:
                        await update.message.reply_text(
                            "❌ Gagal mengupload foto. Silakan coba lagi."
                        )
                        
                except Exception as e:
                    print(f"Error uploading photo with custom name: {e}")
                    await update.message.reply_text(
                        "❌ Terjadi kesalahan saat mengupload foto."
                    )
            
            # Clear temp photo
            if 'temp_photo' in context.user_data:
                del context.user_data['temp_photo']
            
            return UPLOAD_PHOTO
            
        except Exception as e:
            print(f"Error in input_photo_desc: {e}")
            await update.message.reply_text(
                "❌ Terjadi kesalahan. Silakan coba lagi."
            )
            return INPUT_PHOTO_DESC

    async def cancel_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current report and cleanup"""
        try:
            user_id = update.effective_user.id
            
            # Delete folder if exists
            self.delete_folder_if_exists(user_id)
            
            # End session
            self.session_service.end_session(user_id)
            
            # Clear context data
            context.user_data.clear()
            
            await update.message.reply_text(
                "❌ **Laporan dibatalkan.**\n\n"
                "Semua data dan folder yang dibuat telah dihapus.\n"
                "Silakan mulai lagi jika diperlukan.",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
            )
            return ConversationHandler.END
            
        except Exception as e:
            print(f"Error in cancel_report: {e}")
            await update.message.reply_text(
                "Laporan dibatalkan.",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
            )
            return ConversationHandler.END

    async def fallback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fallback handler for unexpected messages"""
        try:
            await update.message.reply_text(
                "❌ Perintah tidak dikenali.\n"
                "Silakan mulai ulang dengan /start",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
            )
            return ConversationHandler.END
        except:
            return ConversationHandler.END

    def setup_handlers(self, application):
        """Setup handlers for the bot application"""
        print("🤖 Setting up Telegram Bot handlers...")
        
        # Conversation handler with improved error handling
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('start', self.start)
            ],
            states={
                SELECT_REPORT_TYPE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.select_report_type
                    )
                ],
                INPUT_ID: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.input_id
                    )
                ],
                INPUT_DATA: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.input_data
                    )
                ],
                CONFIRM_DATA: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.confirm_data
                    )
                ],
                UPLOAD_PHOTO: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.upload_photo
                    ),
                    MessageHandler(
                        filters.PHOTO,
                        self.upload_photo
                    )
                ],
                INPUT_PHOTO_DESC: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.input_photo_desc
                    )
                ]
            },
            fallbacks=[
                CommandHandler('start', self.start),
                MessageHandler(filters.ALL, self.fallback_handler)
            ],
            allow_reentry=True,
            name="report_conversation",
            persistent=False
        )
        
        # Add handlers
        application.add_handler(conv_handler)
        
        # Add error handler
        async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            """Log errors caused by Updates."""
            print(f"Exception while handling an update: {context.error}")
            
            # Try to send error message to user if update is available
            if isinstance(update, Update) and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "❌ Terjadi kesalahan sistem. Silakan coba lagi dengan /start"
                    )
                except:
                    pass
        
        application.add_error_handler(error_handler)
        print("✅ Bot handlers setup complete!")

    # Method for local testing (optional)
    def run_polling(self):
        """Run the bot with polling (for local testing only)"""
        print("🤖 Starting Telegram Bot with polling...")
        
        application = Application.builder().token(self.token).build()
        self.setup_handlers(application)
        
        print("🤖 Bot is running... Press Ctrl+C to stop")
        application.run_polling()
