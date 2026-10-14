import os
import subprocess
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Drive Video to Audio Converter")

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
    return {"status": "ok", "message": "Backend is active and ready"}

@app.post("/api/convert")
def process_video_to_mp3(payload: ConversionPayload):
    # نام کے اسپیس یا اردو حروف سے بچنے کے لیے لوکل فائل کا سادہ نام
    input_file = f"/tmp/input_{payload.file_id}.mp4"
    output_path = f"/tmp/output_{payload.file_id}.mp3"
    
    # ڈرائیو پر بننے والی فائل کا اصل نام (MP3 ایکسٹینشن کے ساتھ)
    base_name = os.path.splitext(payload.file_name)[0]
    output_filename = f"{base_name}.mp3"

    try:
        creds = Credentials(token=payload.access_token)
        drive_service = build('drive', 'v3', credentials=creds)

        logger.info(f"Downloading file ID: {payload.file_id}")
        
        # 1. ڈرائیو سے فائل کو ڈسک پر محفوظ طریقے سے اسٹریم ڈاؤن لوڈ کرنا
        request = drive_service.files().get_media(fileId=payload.file_id)
        with open(input_file, "wb") as f:
            downloader = MediaIoBaseDownload(f, request, chunksize=1024 * 1024 * 8) # 8MB چنک
            done = False
            while not done:
                _, done = downloader.next_chunk()

        logger.info("Executing FFmpeg conversion...")

        # 2. FFmpeg کمانڈ: ویڈیو ڈسک سے پڑے گی اس لیے انڈیکسنگ/moov atom کا کوئی ایرر نہیں آئے گا
        cmd = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-vn",
            "-acodec", "libmp3lame",
            "-b:a", "192k",
            output_path
        ]
        
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            error_details = res.stderr.decode('utf-8', errors='ignore')
            logger.error(f"FFmpeg error: {error_details}")
            raise HTTPException(status_code=500, detail=f"FFmpeg failed: {error_details[-250:]}")

        logger.info(f"Uploading output to Google Drive: {output_filename}")

        # 3. تیار شدہ MP3 کو صارف کی گوگل ڈرائیو میں اپلوڈ کرنا
        metadata = {'name': output_filename, 'mimeType': 'audio/mp3'}
        media = MediaFileUpload(output_path, mimetype='audio/mp3', resumable=True)
        created_file = drive_service.files().create(
            body=metadata,
            media_body=media,
            fields='id'
        ).execute()

        return {
            "status": "success",
            "message": "Conversion completed successfully",
            "file_id": created_file.get("id")
        }

    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Unexpected error: {str(err)}")
        raise HTTPException(status_code=500, detail=str(err))

    finally:
        # پروسیسنگ ختم ہوتے ہی عارضی فائلوں کو فوری ڈیلیٹ کرنا تاکہ سرور صاف رہے
        for temp_file in [input_file, output_path]:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
