class SpreadsheetConfig:
    def __init__(self):
        # Konfigurasi posisi tabel
        self.table_start_row = 3      # Baris mulai (3 = baris ketiga)
        self.table_start_col = "A"    # Kolom mulai 
        self.table_end_col = "U"      # Kolom terakhir (21 kolom: A-U) - diperluas untuk foto eviden

        # Konfigurasi header/kolom tabel
        self.headers = [
            "Report Type",          # A
            "ID Ticket",            # B  
            "Time",                 # C
            "Reported",             # D
            "Month",                # E
            "Segmen",               # F
            "Category",             # G
            "Customer Name",        # H
            "Service No",           # I
            "Segment",              # J
            "Teknisi 1",            # K
            "Teknisi 2",            # L
            "STO",                  # M
            "Valins ID",            # N
            "Service Type",         # O
            "Status",               # P
            "Resolve",              # Q
            "Solution",             # R
            "Job-ID",               # S
            "Team",                 # T
            "Foto Eviden",          # U - pindahan dari S ke U
        ]
        
        # Opsi report type
        self.report_type_options = {
            'non_b2b': 'Non B2B',
            'bges': 'BGES', 
            'squad': 'Squad'
        }
    
    def get_range(self, row_offset=0):
        """Get range string for spreadsheet operations"""
        start_row = self.table_start_row + row_offset
        return f'Sheet1!{self.table_start_col}{start_row}:{self.table_end_col}{start_row}'
    
    def get_column_range(self):
        """Get column range for reading all data"""
        return f'Sheet1!{self.table_start_col}:{self.table_end_col}'
    
    def get_append_range(self):
        """Get range for appending data"""
        return f'Sheet1!{self.table_start_col}:{self.table_end_col}'
    
    def prepare_row_data(self, laporan_data, row_number):
        """Prepare data row according to header configuration"""
        from datetime import datetime
        
        # Extract time dari reported
        reported_time = laporan_data.get('reported', '')
        if reported_time:
            try:
                time_part = reported_time.split(' ')[1] if ' ' in reported_time else datetime.now().strftime("%H:%M")
            except:
                time_part = datetime.now().strftime("%H:%M")
        else:
            time_part = datetime.now().strftime("%H:%M")
        
        # Auto-generate month
        current_month = datetime.now().strftime("%B")
        
        # Prepare row data sesuai urutan header (21 kolom)
        row_data = [
            laporan_data.get('report_type', ''),           # A - Report Type
            laporan_data.get('id_ticket', ''),             # B - ID Ticket  
            time_part,                                      # C - Time
            laporan_data.get('reported', ''),              # D - Reported
            current_month,                                  # E - Month
            '',                                             # F - Segmen (kosong)
            '',                                             # G - Category (kosong)
            laporan_data.get('customer_name', ''),         # H - Customer Name
            laporan_data.get('service_no', ''),            # I - Service No
            laporan_data.get('segment', ''),               # J - Segment
            laporan_data.get('teknisi_1', ''),             # K - Teknisi 1
            laporan_data.get('teknisi_2', ''),             # L - Teknisi 2
            laporan_data.get('sto', ''),                   # M - STO
            laporan_data.get('valins_id', ''),             # N - Valins ID
            '',                                             # O - Service Type (kosong)
            '',                                             # P - Status (kosong)
            '',                                             # Q - Resolve (kosong)
            '',                                             # R - Solution (kosong)
            '',                                             # S - Job-ID (kosong untuk sementara)
            '',                                             # T - Team (kosong)
            laporan_data.get('folder_link', ''),           # U - Foto Eviden (folder link)
        ]
        
        return row_data