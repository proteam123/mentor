
import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
import google.generativeai as genai
from app import get_ai_response, process_file_monitor  # Reusing logic from app.py

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN or not API_KEY:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY in .env")


from groq import Groq

# ... (Previous imports)

# Remove or comment out Gemini configure for STT if mostly using Groq now
# genai.configure(api_key=API_KEY) # We might keep gemini for file upload summarizing in app.py, but here we use Groq

async def transcribe_audio(file_path):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    try:
        print(f"Uploading {file_path} to Groq Whisper...")
        with open(file_path, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(file_path, file.read()),
                model="distil-whisper-large-v3-en",
                # prompt="The language is Malayalam.", # Optional, but distil-whisper is mainly English focused. 
                # Groq has "whisper-large-v3" which is multi-lingual.
                # Let's use whisper-large-v3 for Malayalam support.
            )
            return transcription.text.strip()
            
    except Exception as e:
        print(f"Groq Whisper Error: {e}")
        # Build logic here or just fail. 
        # Groq Whisper "on-demand" might fail if model not correct.
        # Retry with "whisper-large-v3"
        try: 
            with open(file_path, "rb") as file:
                transcription = client.audio.transcriptions.create(
                  file=(file_path, file.read()),
                  model="whisper-large-v3"
                )
            return transcription.text.strip()
        except Exception as e2:
            logging.error(f"Whisper Backup Error: {e2}")
            return None


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logging.info(f"Received voice from {user.first_name}")

    # 1. Download Voice File
    voice_file = await update.message.voice.get_file()
    # Save as .ogg (Telegram default)
    file_path = f"temp_voice_{user.id}.ogg"
    await voice_file.download_to_drive(file_path)
    
    try:
        await update.message.reply_text("🎤 Listening and processing...")

        # 2. Transcribe
        transcribed_text = await transcribe_audio(file_path)
        
        if not transcribed_text:
            await update.message.reply_text("Sorry, I couldn't understand that.")
            return

        logging.info(f"Transcribed: {transcribed_text}")
        await update.message.reply_text(f"🗣 You said: {transcribed_text}")

        # 3. Get AI Response (using app.py logic)
        # Note: get_ai_response is synchronous, so we run it directly (blocking is fine for low volume/demo)
        result, error = get_ai_response(transcribed_text)
        
        if error:
            await update.message.reply_text(f"Error: {error}")
            return
            
        ai_text = result['response']
        audio_web_path = result['audio_url'] # e.g., /static/response_xyz.mp3
        
        # 4. Convert web path to local system path
        # Remove leading slash if present
        if audio_web_path.startswith('/'):
            audio_web_path = audio_web_path[1:]
            
        local_audio_path = os.path.join(os.getcwd(), audio_web_path)
        
        # 5. Send Voice Reply
        if os.path.exists(local_audio_path):
            await update.message.reply_voice(voice=open(local_audio_path, 'rb'), caption=ai_text)
        else:
            await update.message.reply_text(f"Response: {ai_text} (Audio generation failed)")

    except Exception as e:
        logging.error(f"Handler Error: {e}")
        await update.message.reply_text("Something went wrong.")
    finally:
        # Cleanup temp upload
        if os.path.exists(file_path):
            os.remove(file_path)


async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logging.info(f"Received file from {user.first_name}")

    try:
        # Determine file type
        file_obj = None
        file_name = "downloaded_file"
        
        if update.message.document:
            file_obj = await update.message.document.get_file()
            file_name = update.message.document.file_name or "document.pdf"
        elif update.message.photo:
            file_obj = await update.message.photo[-1].get_file() # Get largest photo
            file_name = f"photo_{file_obj.file_unique_id}.jpg"
        else:
            await update.message.reply_text("Unsupported file type.")
            return

        await update.message.reply_text("📥 Downloading and analyzing...")

        # Ensure filename is safe (basic)
        local_path = os.path.join("uploads", file_name)
        os.makedirs("uploads", exist_ok=True)
        
        # Download
        await file_obj.download_to_drive(local_path)
        
        # Process (OCR/Analysis) - Reusing app.py logic
        # Note: We run this synchronously for now, or could offload to thread if needed
        # process_file_monitor deals with context updates
        extracted_text, error = process_file_monitor(local_path)
        
        if error:
            await update.message.reply_text(f"❌ Analysis Failed: {error}")
        else:
            # Shorten text if too long for caption/message
            display_text = extracted_text[:4000] 
            await update.message.reply_text(f"✅ Context Updated!\n\n**Learned Info:**\n{display_text}")

        # Cleanup handled by process_file_monitor (delete prompt file) 
        # but we also have the local downloaded file.
        # Let's clean it up to save space.
        if os.path.exists(local_path):
            os.remove(local_path)

    except Exception as e:
        logging.error(f"File Handler Error: {e}")
        await update.message.reply_text("Error processing file.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("I heard you! Please send a voice note for the AI interaction.")

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    
    voice_msg_handler = MessageHandler(filters.VOICE, voice_handler)
    text_msg_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler)
    file_msg_handler = MessageHandler(filters.Document.ALL | filters.PHOTO, file_handler)
    
    application.add_handler(voice_msg_handler)
    application.add_handler(text_msg_handler)
    application.add_handler(file_msg_handler)
    
    print("Telegram Bot Started...")
    application.run_polling()
