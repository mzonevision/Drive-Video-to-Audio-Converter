import os
import subprocess
import threading
from io import BytesIO
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload

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
    return {"status": "ok", "message": "Pipe Streaming API is active!"}

@app.post("/api/convert")
def process_video_to_mp3(payload: ConversionPayload):
    # آؤٹ پٹ فائل کو محفوظ ڈسک پاتھ دینا
    base_name = os.path.splitext(payload.file_name)[0]
    output_filename = f"{base_name}.mp3"
    output_path = f"/tmp/{payload.file_id}.mp3"

    try:
        creds = Credentials(token=payload.access_token)
        drive_service = build('drive', 'v3', credentials=creds)

        # 1. FFmpeg سب پروسیس شروع کرنا (جو pipe:0 سے ڈیٹا وصول کرے گا)
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", "pipe:0",           # ان پٹ اسٹینڈرڈ ان پٹ سے آئے گا
            "-vn",                    # ویڈیو ہٹا دو
            "-acodec", "libmp3lame",  # MP3 انکوڈر
            "-b:a", "192k",           # 192kbps بٹ ریٹ
            output_path               # آؤٹ پٹ فائل
        ]

        proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 2. گوگل ڈرائیو سے بائٹس پڑھ کر FFmpeg پائپ میں فیڈ کرنے کا تھریڈ
        def stream_drive_to_ffmpeg():
            try:
                request = drive_service.files().get_media(fileId=payload.file_id)
                downloader = ChunkedStreamReader(request, proc.stdin)
                downloader.start()
            except Exception as e:
                pass
            finally:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()

        stream_thread = threading.Thread(target=stream_drive_to_ffmpeg)
        stream_thread.start()

        # پروسیس مکمل ہونے کا انتظار
        _, stderr_output = proc.communicate()
        stream_thread.join()

        if proc.returncode != 0:
            err_msg = stderr_output.decode('utf-8', errors='ignore')
            raise HTTPException(status_code=500, detail=f"FFmpeg conversion failed: {err_msg[-250:]}")

        # 3. تیار شدہ چھوٹی MP3 فائل کو ڈرائیو میں اپلوڈ کرنا
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
        raise HTTPException(status_code=500, detail=str(err))

    finally:
        # آڈیو فائل اپلوڈ ہوتے ہی فوری صفائی
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass


class ChunkedStreamReader:
    """گوگل ڈرائیو سے چھوٹے بلاکس لے کر براہِ راست پائپ میں پھینکنے والا کنڈکٹر"""
    def __init__(self, request, pipe_in, chunk_size=1024 * 1024 * 4): # 4MB چنک
        self.request = request
        self.pipe_in = pipe_in
        self.chunk_size = chunk_size

    def start(self):
        # MediaIoBaseDownload کے ذریعے بائٹس پائپ پر لکھنا
        buffer = PipeBuffer(self.pipe_in)
        from googleapiclient.http import MediaIoBaseDownload
        downloader = MediaIoBaseDownload(buffer, self.request, chunksize=self.chunk_size)
        done = False
        while not done:
            _, done = downloader.next_chunk()


class PipeBuffer:
    def __init__(self, pipe_stream):
        self.pipe_stream = pipe_stream

    def write(self, data):
        self.pipe_stream.write(data)
        self.pipe_stream.flush()
        return len(data)
