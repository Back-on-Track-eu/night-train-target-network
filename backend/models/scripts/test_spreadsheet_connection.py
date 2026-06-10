import os
import gspread
from google.oauth2.service_account import Credentials

creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
print(f"Credentials path: {creds_path}")

scopes = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
client = gspread.authorize(creds)

# Replace with your actual spreadsheet ID from the URL
spreadsheet = client.open_by_key("14fQ2Ee7KIEGtzNipZ1xt6i8p-K1mysPt3_txTGFEORA")
print(f"Connected to: {spreadsheet.title}")
print(f"Sheets: {[ws.title for ws in spreadsheet.worksheets()]}")