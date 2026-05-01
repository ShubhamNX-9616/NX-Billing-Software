import os
import shutil
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DB_PATH    = "/home/shubhamnxtailoring/NX-Billing-Software/billing.db"
CREDS_PATH = "/home/shubhamnxtailoring/service_account.json"
FOLDER_ID  = "1YroGJPHQg6ZKDQxdRtk7R02fadb-qOT8"
KEEP_DAYS  = 7
SCOPES     = ["https://www.googleapis.com/auth/drive"]


def _service():
    creds = service_account.Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _upload(svc, path, name):
    metadata = {"name": name, "parents": [FOLDER_ID]}
    media = MediaFileUpload(path, mimetype="application/x-sqlite3", resumable=False)
    svc.files().create(body=metadata, media_body=media).execute()
    print(f"Uploaded: {name}")


def _purge_old(svc):
    cutoff = (datetime.utcnow() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = svc.files().list(
        q=f"'{FOLDER_ID}' in parents and createdTime < '{cutoff}' and trashed = false",
        fields="files(id, name)",
    ).execute()
    for f in res.get("files", []):
        svc.files().delete(fileId=f["id"]).execute()
        print(f"Deleted old backup: {f['name']}")


def main():
    timestamp   = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename    = f"billing_{timestamp}.db"
    tmp_path    = f"/tmp/{filename}"

    shutil.copy2(DB_PATH, tmp_path)

    svc = _service()
    _upload(svc, tmp_path, filename)
    _purge_old(svc)

    os.remove(tmp_path)
    print(f"Backup complete: {filename}")


if __name__ == "__main__":
    main()
