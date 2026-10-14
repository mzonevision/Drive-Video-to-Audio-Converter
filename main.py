import os
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

app = FastAPI(title="Drive Video to Audio Converter")

# فرنٹ اینڈ کے لیے تمام راستے کھولنا (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConversionPayload(BaseModel):
    access_token: str
    file_id: str
    file_name: str

@app.get("/")
def home():
    return {"message": "D-VAC Backend API is running successfully!"}

@app.post("/api/convert")
def process_video_to_mp3(payload: ConversionPayload):
    creds = Credentials(token=payload.access_token)
    drive_service = build('drive', 'v3', credentials=creds)

    input_file = f"/tmp/{payload.file_id}_temp"
    output_filename = os.path.splitext(payload.file_name)[0] + ".mp3"
    output_path = f"/tmp/{payload.file_id}.mp3"

    try:
        # 1. ڈرائیو سے ویڈیو ڈاؤن لوڈ کرنا
        req = drive_service.files().get_media(fileId=payload.file_id)
        with open(input_file, "wb") as f:
            downloader = MediaIoBaseDownload(f, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        # 2. FFmpeg کے ذریعے آڈیو نکال کر 192kbps MP3 بنانا
        cmd = [
            "ffmpeg", "-y", "-i", input_file,
            "-vn", "-acodec", "libmp3lame", "-b:a", "192k",
            output_path
        ]
        subprocess.run(cmd, check=True)

        # 3. تیار شدہ MP3 کو صارف کی ڈرائیو میں محفوظ کرنا
        metadata = {'name': output_filename, 'mimeType': 'audio/mp3'}
        media = MediaFileUpload(output_path, mimetype='audio/mp3')
        created_file = drive_service.files().create(
            body=metadata,
            media_body=media,
            fields='id'
        ).execute()

        return {
            "status": "success",
            "message": "Conversion completed",
            "file_id": created_file.get("id")
        }

    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))

    finally:
        # پروسیسنگ مکمل ہوتے ہی سرور سے عارضی فائلیں فوراً صاف کرنا
        if os.path.exists(input_file):
            os.remove(input_file)
        if os.path.exists(output_path):
            os.remove(output_path)
