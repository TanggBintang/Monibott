import os
import re
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from datetime import datetime

from config.spreadsheet_config import SpreadsheetConfig
from services.google_service import GoogleService
from services.session_service import SessionService

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
                print(f"âœ… Folder deleted for user {user_id}")
            except Exception as e:
                print(f"âŒ Error deleting folder: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        user_id = update.effective_user.id
        
        # Buat sesi baru
        self.session_service.create_session(user_id)
        
        keyboard = [
            [KeyboardButton("Non B2B"), KeyboardButton("BGES")],
            [KeyboardButton("Squad")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "ðŸ“‹ Pilih Jenis Laporan:",
            reply_markup=reply_markup
        )
        return SELECT_REPORT_TYPE

    async def select_report_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle report type selection"""
        user_id = update.effective_user.id
        message_text = update.message.text
        
        # Handle normal report type selection
        valid_types = ['Non B2B', 'BGES', 'Squad']
        if message_text not in valid_types:
            await update.message.reply_text("Pilihan tidak valid. Silakan pilih jenis laporan yang tersedia.")
            return SELECT_REPORT_TYPE
        
        # Update session
        self.session_service.update_session(user_id, {'report_type': message_text})
        
        await update.message.reply_text(
            "ðŸ†” Masukkan ID Ticket:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("âŒ Batalkan")]], resize_keyboard=True)
        )
        return INPUT_ID

    async def input_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle ID input"""
        user_id = update.effective_user.id
        ticket_id = update.message.text.strip()
        
        if ticket_id == "âŒ Batalkan":
            self.delete_folder_if_exists(user_id)
            self.session_service.end_session(user_id)
            await update.message.reply_text(
                "Laporan dibatalkan.",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
            )
            return ConversationHandler.END
        
        if not ticket_id:
            await update.message.reply_text("ID Ticket tidak boleh kosong. Silakan masukkan ID Ticket:")
            return INPUT_ID
        
        # Update session
        session = self.session_service.get_session(user_id)
        self.session_service.update_session(user_id, {'id_ticket': ticket_id})
        
        # Buat folder di Google Drive
        folder_name = f"{session['report_type']}_{ticket_id}"
        folder_id = self.google_service.create_folder(folder_name)
        
        if not folder_id:
            await update.message.reply_text("Gagal membuat folder. Silakan coba lagi.")
            return INPUT_ID
        
        self.session_service.update_session(user_id, {'folder_id': folder_id})
        
        # Kirim format pengisian
        folder_link = self.google_service.get_folder_link(folder_id)
        report_format = (
            f"ðŸ“‹ Format Berhasil Dibuat\n\n"
            f"Report Type : {session['report_type']}\n"
            f"ID Ticket : {ticket_id}\n"
            f"Folder Drive : {folder_link}\n"
            f"-------------------------------------------------------------\n"
            f"Salin Format Laporan dan isi dibawah ini :\n\n"
            f"Customer Name : \n"
            f"Service No : \n"
            f"Segment : \n"
            f"Teknisi 1 : \n"
            f"Teknisi 2 : \n"
            f"STO : \n"
            f"Valins ID : "
        )
        
        await update.message.reply_text(
            report_format,
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("âŒ Batalkan")]], resize_keyboard=True)
        )
        return INPUT_DATA

    async def input_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle data input"""
        user_id = update.effective_user.id
        message_text = update.message.text
        
        if message_text == "âŒ Batalkan":
            self.delete_folder_if_exists(user_id)
            self.session_service.end_session(user_id)
            await update.message.reply_text(
                "Laporan dibatalkan.",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
            )
            return ConversationHandler.END
        
        # Parse data dari format
        data = {}
        lines = message_text.split('\n')
        
        # Cari bagian setelah "Salin Format Laporan dan isi dibawah ini :"
        start_idx = next((i for i, line in enumerate(lines) if "Salin Format Laporan" in line), len(lines))
        
        for line in lines[start_idx+1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                data[key.strip()] = value.strip()
        
        # Validasi data yang diperlukan
        required_fields = ['Customer Name', 'Service No', 'Segment', 'Teknisi 1', 'Teknisi 2', 'STO', 'Valins ID']
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        
        if missing_fields:
            await update.message.reply_text(
                f"Data tidak lengkap. Field berikut harus diisi: {', '.join(missing_fields)}\n\n"
                f"Silakan kirim ulang format yang sudah diisi dengan lengkap."
            )
            return INPUT_DATA
        
        # Simpan data ke session
        session = self.session_service.get_session(user_id)
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
        
        # Tampilkan konfirmasi dengan info foto
        session = self.session_service.get_session(user_id)
        photo_info = ""
        if session['photos']:
            photo_info = f"\nðŸ“· Foto Terupload: {len(session['photos'])} foto\n"
            for i, photo in enumerate(session['photos'], 1):
                photo_info += f"   {i}. {photo['name']}\n"
        else:
            photo_info = "\nðŸ“· Foto Eviden: Belum ada foto terupload\n"
        
        confirmation_text = (
            f"ðŸ“‹ Konfirmasi Data Laporan\n\n"
            f"Report Type: {report_data['report_type']}\n"
            f"ID Ticket: {report_data['id_ticket']}\n"
            f"Customer Name: {report_data['customer_name']}\n"
            f"Service No: {report_data['service_no']}\n"
            f"Segment: {report_data['segment']}\n"
            f"Teknisi 1: {report_data['teknisi_1']}\n"
            f"Teknisi 2: {report_data['teknisi_2']}\n"
            f"STO: {report_data['sto']}\n"
            f"Valins ID: {report_data['valins_id']}"
            f"{photo_info}\n"
            f"Pilih tindakan:"
        )
        
        keyboard = [
            [KeyboardButton("âœ… Kirim Laporan"), KeyboardButton("ðŸ“ Edit Data")],
            [KeyboardButton("ðŸ“· Upload Foto Eviden"), KeyboardButton("âŒ Batalkan")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
        return CONFIRM_DATA

    async def confirm_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle data confirmation"""
        user_id = update.effective_user.id
        choice = update.message.text
        session = self.session_service.get_session(user_id)
        
        if choice == "âœ… Kirim Laporan":
            # Kirim ke spreadsheet
            success = self.google_service.update_spreadsheet(
                self.spreadsheet_id,
                self.spreadsheet_config,
                session['data']
            )
            
            if success:
                photo_count = len(session['photos'])
                success_message = "âœ… Laporan berhasil dikirim ke spreadsheet!"
                if photo_count > 0:
                    success_message += f"\nðŸ“· {photo_count} foto eviden tersimpan di folder Drive."
                
                await update.message.reply_text(
                    success_message,
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
                )
            else:
                await update.message.reply_text(
                    "âŒ Gagal mengirim laporan. Silakan coba lagi.",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
                )
            
            self.session_service.end_session(user_id)
            return ConversationHandler.END
            
        elif choice == "ðŸ“ Edit Data":
            # Kirim ulang format untuk diedit
            report_format = (
                f"ðŸ“ Edit Data Laporan\n\n"
                f"Report Type : {session['data']['report_type']}\n"
                f"ID Ticket : {session['data']['id_ticket']}\n"
                f"Folder Drive : {session['data']['folder_link']}\n"
                f"-------------------------------------------------------------\n"
                f"Salin Format Laporan dan edit dibawah ini :\n\n"
                f"Customer Name : {session['data']['customer_name']}\n"
                f"Service No : {session['data']['service_no']}\n"
                f"Segment : {session['data']['segment']}\n"
                f"Teknisi 1 : {session['data']['teknisi_1']}\n"
                f"Teknisi 2 : {session['data']['teknisi_2']}\n"
                f"STO : {session['data']['sto']}\n"
                f"Valins ID : {session['data']['valins_id']}"
            )
            
            await update.message.reply_text(
                report_format,
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("âŒ Batalkan")]], resize_keyboard=True)
            )
            return INPUT_DATA
            
        elif choice == "ðŸ“· Upload Foto Eviden":
            await update.message.reply_text(
                "ðŸ“· **Upload Foto Eviden**\n\n"
                "âš ï¸ **PENTING - Cara Upload Foto:**\n"
                "â€¢ **Satu foto**: Kirim 1 foto â†’ input deskripsi custom\n"
                "â€¢ **Beberapa foto sekaligus**: Deskripsi akan otomatis random (foto_1, foto_2, dst)\n\n"
                "ðŸ“ **Pilih metode upload:**",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("ðŸ“¸ Upload Satu-Satu (Custom Nama)")],
                    [KeyboardButton("ðŸ“· Upload Banyak (Auto Nama)")],
                    [KeyboardButton("âŒ Batalkan")]
                ], resize_keyboard=True)
            )
            return UPLOAD_PHOTO
            
        elif choice == "âŒ Batalkan":
            self.delete_folder_if_exists(user_id)
            self.session_service.end_session(user_id)
            await update.message.reply_text(
                "Laporan dibatalkan.",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
            )
            return ConversationHandler.END

    async def upload_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo upload state"""
        user_id = update.effective_user.id
        message_text = update.message.text
        
        # Handle pilihan metode upload
        if message_text == "ðŸ“¸ Upload Satu-Satu (Custom Nama)":
            # Set mode upload satu-satu
            context.user_data['upload_mode'] = 'single'
            await update.message.reply_text(
                "ðŸ“¸ **Mode Upload Satu-Satu**\n\n"
                "Kirimkan foto satu per satu. Setiap foto akan diminta deskripsi custom.\n\n"
                "Kirimkan foto pertama:",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("Selesai Upload"), KeyboardButton("âŒ Batalkan")]
                ], resize_keyboard=True)
            )
            return UPLOAD_PHOTO
            
        elif message_text == "ðŸ“· Upload Banyak (Auto Nama)":
            # Set mode upload banyak
            context.user_data['upload_mode'] = 'multiple'
            await update.message.reply_text(
                "ðŸ“· **Mode Upload Banyak**\n\n"
                "Kirimkan beberapa foto sekaligus. Nama file akan otomatis: foto_1, foto_2, dst.\n\n"
                "Kirimkan foto-foto Anda:",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("Selesai Upload"), KeyboardButton("âŒ Batalkan")]
                ], resize_keyboard=True)
            )
            return UPLOAD_PHOTO
        
        if message_text == "Selesai Upload":
            # Reset upload mode
            if 'upload_mode' in context.user_data:
                del context.user_data['upload_mode']
            
            # Kembali ke konfirmasi data dengan info foto terbaru
            session = self.session_service.get_session(user_id)
            photo_info = ""
            if session['photos']:
                photo_info = f"\nðŸ“· Foto Terupload: {len(session['photos'])} foto\n"
                for i, photo in enumerate(session['photos'], 1):
                    photo_info += f"   {i}. {photo['name']}\n"
            else:
                photo_info = "\nðŸ“· Foto Eviden: Belum ada foto terupload\n"
            
            confirmation_text = (
                f"ðŸ“‹ Konfirmasi Data Laporan\n\n"
                f"Report Type: {session['data']['report_type']}\n"
                f"ID Ticket: {session['data']['id_ticket']}\n"
                f"Customer Name: {session['data']['customer_name']}\n"
                f"Service No: {session['data']['service_no']}\n"
                f"Segment: {session['data']['segment']}\n"
                f"Teknisi 1: {session['data']['teknisi_1']}\n"
                f"Teknisi 2: {session['data']['teknisi_2']}\n"
                f"STO: {session['data']['sto']}\n"
                f"Valins ID: {session['data']['valins_id']}"
                f"{photo_info}\n"
                f"Pilih tindakan:"
            )
            
            keyboard = [
                [KeyboardButton("âœ… Kirim Laporan"), KeyboardButton("ðŸ“ Edit Data")],
                [KeyboardButton("ðŸ“· Upload Foto Eviden"), KeyboardButton("âŒ Batalkan")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
            return CONFIRM_DATA
        
        elif message_text == "âŒ Batalkan":
            # Reset upload mode
            if 'upload_mode' in context.user_data:
                del context.user_data['upload_mode']
            self.delete_folder_if_exists(user_id)
            self.session_service.end_session(user_id)
            await update.message.reply_text(
                "Laporan dibatalkan.",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
            )
            return ConversationHandler.END
        
        # Handle photo message
        if update.message.photo:
            upload_mode = context.user_data.get('upload_mode', 'single')
            
            if upload_mode == 'single':
                # Mode upload satu-satu - minta deskripsi
                photo = update.message.photo[-1]
                context.user_data['temp_photo'] = photo
                
                await update.message.reply_text(
                    "ðŸ“ Masukkan deskripsi untuk foto ini (akan digunakan sebagai nama file):\n\n"
                    "Contoh: 'foto_sebelum_perbaikan', 'hasil_instalasi', dll",
                    reply_markup=ReplyKeyboardMarkup([
                        [KeyboardButton("âŒ Batalkan")]
                    ], resize_keyboard=True)
                )
                return INPUT_PHOTO_DESC
            
            elif upload_mode == 'multiple':
                # Mode upload banyak - langsung proses dengan nama auto
                session = self.session_service.get_session(user_id)
                if not session or not session.get('folder_id'):
                    await update.message.reply_text(
                        "âŒ Session tidak valid. Silakan mulai ulang.",
                        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
                    )
                    return ConversationHandler.END
                
                photo = update.message.photo[-1]
                try:
                    file = await context.bot.get_file(photo.file_id)
                    
                    # Generate nama otomatis
                    photo_count = len(session['photos']) + 1
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"foto_{photo_count}_{timestamp}.jpg"
                    filepath = f"temp_{filename}"
                    
                    await file.download_to_drive(filepath)
                    
                    file_id = self.google_service.upload_to_drive(filepath, filename, session['folder_id'])
                    
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    
                    if file_id:
                        # Tambahkan ke daftar foto
                        session['photos'].append({
                            'id': file_id,
                            'name': filename
                        })
                        
                        await update.message.reply_text(
                            f"âœ… Foto '{filename}' berhasil diupload!\n\n"
                            f"ðŸ“· Total foto terupload: {len(session['photos'])}\n\n"
                            f"Kirim foto lain atau ketik 'Selesai Upload'."
                        )
                    else:
                        await update.message.reply_text(
                            "âŒ Gagal mengupload foto. Silakan coba lagi."
                        )
                        
                except Exception as e:
                    print(f"Error uploading photo: {e}")
                    await update.message.reply_text(
                        "âŒ Terjadi kesalahan saat mengupload foto. Silakan coba lagi."
                    )
                
                return UPLOAD_PHOTO
        else:
            # Belum pilih mode upload
            if 'upload_mode' not in context.user_data:
                await update.message.reply_text(
                    "Silakan pilih metode upload terlebih dahulu."
                )
                return UPLOAD_PHOTO
            else:
                await update.message.reply_text(
                    "Silakan kirim foto atau pilih 'Selesai Upload' jika sudah selesai."
                )
                return UPLOAD_PHOTO

    async def input_photo_desc(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo description input"""
        user_id = update.effective_user.id
        description = update.message.text.strip()
        
        if description == "âŒ Batalkan":
            # Kembali ke upload photo mode single
            await update.message.reply_text(
                "ðŸ“¸ **Mode Upload Satu-Satu**\n\n"
                "Kirimkan foto satu per satu. Setiap foto akan diminta deskripsi custom.\n\n"
                "Kirimkan foto:",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("Selesai Upload"), KeyboardButton("âŒ Batalkan")]
                ], resize_keyboard=True)
            )
            return UPLOAD_PHOTO
        
        if not description:
            await update.message.reply_text("Deskripsi tidak boleh kosong. Silakan masukkan deskripsi foto:")
            return INPUT_PHOTO_DESC
        
        # Clean description untuk nama file
        clean_desc = re.sub(r'[^\w\s-]', '', description).strip()
        clean_desc = re.sub(r'[\s]+', '_', clean_desc)
        
        # Process foto yang disimpan sementara
        session = self.session_service.get_session(user_id)
        temp_photo = context.user_data.get('temp_photo')
        
        if temp_photo and session and session.get('folder_id'):
            try:
                file = await context.bot.get_file(temp_photo.file_id)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{clean_desc}_{timestamp}.jpg"
                filepath = f"temp_{filename}"
                
                await file.download_to_drive(filepath)
                
                file_id = self.google_service.upload_to_drive(filepath, filename, session['folder_id'])
                
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                if file_id:
                    # Tambahkan ke daftar foto
                    session['photos'].append({
                        'id': file_id,
                        'name': filename
                    })
                    
                    await update.message.reply_text(
                        f"âœ… Foto '{filename}' berhasil diupload!\n\n"
                        f"ðŸ“· Total foto terupload: {len(session['photos'])}\n\n"
                        f"Kirim foto lain atau ketik 'Selesai Upload'.",
                        reply_markup=ReplyKeyboardMarkup([
                            [KeyboardButton("Selesai Upload"), KeyboardButton("âŒ Batalkan")]
                        ], resize_keyboard=True)
                    )
                else:
                    await update.message.reply_text(
                        "âŒ Gagal mengupload foto. Silakan coba lagi.",
                        reply_markup=ReplyKeyboardMarkup([
                            [KeyboardButton("Selesai Upload"), KeyboardButton("âŒ Batalkan")]
                        ], resize_keyboard=True)
                    )
            except Exception as e:
                print(f"Error uploading photo: {e}")
                await update.message.reply_text(
                    "âŒ Terjadi kesalahan saat mengupload foto. Silakan coba lagi.",
                    reply_markup=ReplyKeyboardMarkup([
                        [KeyboardButton("Selesai Upload"), KeyboardButton("âŒ Batalkan")]
                    ], resize_keyboard=True)
                )
        
        # Clear temp photo
        if 'temp_photo' in context.user_data:
            del context.user_data['temp_photo']
        
        return UPLOAD_PHOTO

    def setup_handlers(self, application):
        """Setup handlers for the bot application"""
        print("🤖 Setting up Telegram Bot handlers...")
        
        # Conversation handler
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
            fallbacks=[CommandHandler('start', self.start)],
            allow_reentry=True
        )
        
        # Add handlers
        application.add_handler(conv_handler)
        print("✅ Bot handlers setup complete!")

    # Tambahkan method baru untuk run polling (opsional, untuk testing local)
    def run_polling(self):
        """Run the bot with polling (for local testing)"""
        print("🤖 Starting Telegram Bot with polling...")
        
        application = Application.builder().token(self.token).build()
        self.setup_handlers(application)
        
        print("🤖 Bot is running... Press Ctrl+C to stop")
        application.run_polling()

# Hapus seluruh blok if __name__ == "__main__": dan ganti dengan method baru