# Google Sheets Entegrasyonu

## 1. Google Cloud

1. [Google Cloud Console](https://console.cloud.google.com/) → proje oluşturun.
2. **Google Sheets API** ve **Google Drive API** etkinleştirin.
3. **Service Account** oluşturun → JSON indirin → `kimlik.json` olarak kaydedin.

## 2. Tabloyu paylaşın

1. Google Sheets’te yeni tablo oluşturun.
2. URL’deki ID’yi kopyalayın:  
   `https://docs.google.com/spreadsheets/d/BURASI_ID/edit`
3. Tabloyu service account e-postasıyla **Düzenleyici** olarak paylaşın.

## 3. .env

```env
GOOGLE_SHEETS_ID=spreadsheet_id_buraya
GOOGLE_CREDENTIALS_FILE=kimlik.json
```

## 4. Test

Uygulamada tarama yapın → **Sheets'e Gönder**.

Sütunlar: Başlık, Platform, Kategori, Konum, Link
