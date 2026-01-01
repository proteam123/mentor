
from flask import Flask, request, render_template, jsonify, url_for
from twilio.rest import Client
import os
import google.generativeai as genai
from dotenv import load_dotenv
import database
from gtts import gTTS
import uuid

# Load env before anything else
load_dotenv()

app = Flask(__name__)
database.init_db()

# Ensure static folder exists
os.makedirs('static', exist_ok=True)


from groq import Groq

def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("WARNING: GROQ_API_KEY not set.")
        return None
    return Groq(api_key=api_key)



SYSTEM_PROMPT = """
You are a helpful Malayalam AI tutor and Faculty Advisor for Class S8 ADS. 
Respond in Malayalam. 

DATA CONTEXT (Student Records):
{student_context}

UPLOADED DOCUMENT CONTEXT (LATEST CIRCULAR/NEWS):
{doc_context}


INSTRUCTIONS:
1. **ROLE**: You are the warm, knowledgeable Faculty Advisor. You know every student's details by heart.
2. **TONE**: Speak in **NATURAL, SPOKEN MALAYALAM**. Avoid "bookish" or complex words. Use a respectful, warm tone suitable for talking to a parent on the phone. Keep sentences short and clear for the voice assistant to read easily.
3. **PRIORITY 1: THE UPLOADED DOCUMENT**: If {doc_context} is not empty, you MUST mention this FIRST. "Sir/Madam, I just received this circular: [Summary of doc_context]."
4. **PRIORITY 2: THE STUDENT**: 
   - Ask "Who is this parent?" to verify identity.
   - Once identified (e.g., Basheer), look up their child (Abdullah).
   - **SYNTHESIZE**: Combine the Document info with the Student's data. 
     *Example: "The circular warns about exam fees. Since Abdullah has passed all subjects, he just needs to pay the standard fee."*
   - Report the student's Marks, Discipline, and Attendance CLEARLY.
5. **PRIORITY 3: RSVP**: Always end by asking if they will attend the meeting on Jan 25th.

Keep responses conversational but accurate.
FORMATTING: Do NOT use markdown. Plain text only.

METADATA: At the end of EVERY response, append:
[[META: ParentName|AttendanceStatus]]
"""


import re
from werkzeug.utils import secure_filename

# Ensure uploads folder exists
os.makedirs('uploads', exist_ok=True)

from flask import send_from_directory

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)





import base64


from pdf2image import convert_from_path
import io

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def process_file_monitor(filepath):
    """
    Analyzes file using Groq Vision.
    Converts PDF to images first.
    Returns: (extracted_text, error_message)
    """
    try:
        # Determine file type
        ext = filepath.lower().split('.')[-1]
        
        base64_image = None
        
        if ext in ['jpg', 'jpeg', 'png', 'webp']:
            base64_image = encode_image(filepath)
            
        elif ext == 'pdf':
            print("PDF detected. Converting to image for Groq Vision...")
            try:
                # Convert first page to image
                images = convert_from_path(filepath)
                if not images:
                    return None, "Empty PDF."
                
                # Take first page
                img = images[0]
                
                # Save to bytes
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG')
                img_byte_arr = img_byte_arr.getvalue()
                
                base64_image = base64.b64encode(img_byte_arr).decode('utf-8')
                print("PDF converted to image successfully.")
                
            except Exception as pdf_err:
                 return None, f"PDF Conversion Error: {str(pdf_err)}. Install poppler."
        else:
            return None, "Unsupported file format. Please use JPG, PNG, or PDF."

        if base64_image:
            # Use Groq Vision (Llama 3.2 11B Vision)
            client = get_groq_client()
            if not client:
                return None, "Groq API Key missing."


            chat_completion = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyze this student document. Extract Name, Marks, Attendance, and Disciplinary info. Summarize in 2-3 Malayalam sentences."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                },
                            },
                        ],
                    }
                ],
                model="meta-llama/llama-4-maverick-17b-128e-instruct",
            )
            extracted_text = chat_completion.choices[0].message.content
            print(f"Groq Vision extracted: {extracted_text}")

            # Update Context
            database.add_document_context(extracted_text)
            return extracted_text, None
            
        return None, "Processing failed."

    except Exception as e:
        return None, f"Analysis Error: {str(e)}"



@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join('uploads', filename)
    file.save(filepath)

    extracted_text, error = process_file_monitor(filepath)
    
    if error:
        err_str = str(error)
        print(f"Upload Error: {err_str}")
        if "429" in err_str:
            return jsonify({"error": "Quota exceeded. Please wait 1 minute and try again."}), 429
        return jsonify({"error": f"OCR Error: {err_str}"}), 500
        
    return jsonify({
        "message": "File uploaded and context updated!",
        "learned": extracted_text,
        "file_url": url_for('uploaded_file', filename=filename)
    })


# Twilio Setup
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
api_key_sid = os.getenv("TWILIO_API_KEY_SID")
api_secret = os.getenv("TWILIO_API_KEY_SECRET")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_number = os.getenv("TWILIO_PHONE_NUMBER")

if api_key_sid and api_secret:
    client = Client(api_key_sid, api_secret, account_sid)
else:
    client = Client(account_sid, auth_token)


def generate_audio(text):
    try:
        # Generate unique filename to avoid browser caching issues during testing
        filename = f"response_{uuid.uuid4().hex[:6]}.mp3"
        filepath = os.path.join('static', filename)
        
        # Clean up old files (optional, simple safeguard)
        for f in os.listdir('static'):
            if f.endswith('.mp3'):
                try:
                    os.remove(os.path.join('static', f))
                except:
                    pass

        tts = gTTS(text=text, lang='ml')
        tts.save(filepath)
        return f"/static/{filename}"
    except Exception as e:
        print(f"TTS Error: {e}")
        return None

@app.route('/start_conversation', methods=['POST'])
def start_conversation():
    # Initial greeting logic
    greeting_text = "നമസ്കാരം! ഇത് ആരാണ്? ഏത് കുട്ടിയുടെ രക്ഷിതാവാണ്?"
    
    # Store initial AI message in DB
    database.add_conversation("System Start", greeting_text)
    
    audio_url = generate_audio(greeting_text)
    
    return jsonify({
        "response": greeting_text,
        "audio_url": audio_url
    })


@app.route('/notify_parent', methods=['POST'])
def notify_parent():
    parent_number = request.form.get('parent_number')
    if not parent_number:
         return "Error: parent_number required", 400

    # Ensure we have a public URL for Twilio to reach us
    # If using ngrok, user should set PUBLIC_URL or we rely on request.url_root if proxied correctly
    # For local dev without env var, this might fail on Twilio side (HTTP 11200)
    
    # We use the /twilio/voice endpoint as the handler
    webhook_url = url_for('twilio_voice_webhook', _external=True)
    
    # If running locally behind ngrok manually, url_for might still say localhost.
    # Allow override via env
    public_url_base = os.getenv("PUBLIC_URL")
    if public_url_base:
        webhook_url = f"{public_url_base}/twilio/voice"

    print(f"Initiating call to {parent_number} with webhook: {webhook_url}")

    try:
        call = client.calls.create(
            from_=twilio_number,
            to=parent_number,
            url=webhook_url
        )
        return f"Call initiated! SID: {call.sid}"
    except Exception as e:
        return f"Failed to initiate call: {str(e)}", 500


@app.route('/twilio/voice', methods=['POST'])
def twilio_voice_webhook():
    """Handles the TwiML for the interactive voice call."""
    user_speech = request.form.get('SpeechResult')
    
    # Construct absolute URL for the action
    # This prevents any localhost/relative path issues
    public_url_base = os.getenv("PUBLIC_URL")
    if public_url_base:
        # Ensure no trailing slash
        if public_url_base.endswith('/'):
            public_url_base = public_url_base[:-1]
        action_url = f"{public_url_base}/twilio/voice"
    else:
        # Fallback to external url_for (works if Host header is forwarded correctly)
        action_url = url_for('twilio_voice_webhook', _external=True)

    
    if not user_speech:
        # Case A: Start of Call OR No Input Detected (Twilio Loop)
        # Check if this is a "re-prompt" due to no input (Twilio sends digits/speech empty)
        # We can check 'CallStatus'. But simpler: if no speech, just greet or re-prompt.
        
        # We can differntiate Start vs Loop using a query param or cookie, but simple is fine:
        # If it's the very first request (Start), we greet.
        # IF it's a loop (user stayed silent), we ask "Are you there?" (Simple logic: Random/Context)
        # For simplicity: Just Greet/Prompt always.
        
        ai_text = "നമസ്കാരം! ഇത് ആരാണ്? ഏത് കുട്ടിയുടെ രക്ഷിതാവാണ്? (Hello! Who is this?)"
        print("AI: Greeting/Prompting...")
    else:
        # Case B: User Spoke
        print(f"User said (Call): {user_speech}")
        
        # Get AI Response
        result, error = get_ai_response(user_speech)
        
        if error:
            ai_text = "ക്ഷമിക്കണം, സാങ്കേതിക തകരാർ സംഭവിച്ചു." 
            print(f"Call AI Error: {error}")
        else:
            ai_text = result['response']

    print(f"AI Replying (Call): {ai_text}")

    # Build TwiML
    # 1. Say Response
    # 2. Gather (Listen)
    # 3. If no input -> Loop back to this webhook (Twilio executes next verb)
    #    Actually, <Gather> action handles success. 
    #    If *no* input, it falls through. We should Redirect back to Prompt? 
    #    Or say "Goodbye". Let's Redirect back to listen again once.
    


    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="ml-IN" voice="Google.ml-IN-Standard-A">{ai_text}</Say>
    <Gather input="speech" action="{action_url}" language="ml-IN" timeout="5" speechTimeout="auto">
    </Gather>
    <Say language="ml-IN">Are you there? I did not hear you.</Say>
    <Redirect>{action_url}</Redirect>
</Response>"""
    
    return twiml_response, 200, {'Content-Type': 'application/xml'}



@app.route('/')
def index():
    return render_template('index.html')




def get_ai_response(user_text):
    # Retrieve Gemini Key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None, "Gemini API key not configured"
    
    genai.configure(api_key=api_key)

    try:
        # 1. Fetch recent history from DB
        past_convos = database.get_conversations()
        
        # Build History for Gemini (User/Model format)
        history = []
        recent_convos = past_convos[:10][::-1]
        for row in recent_convos:
            history.append({"role": "user", "parts": [row[1]]})
            history.append({"role": "model", "parts": [row[2]]})
            
        # Dynamic System Prompt
        student_context = database.get_student_context()
        doc_context = database.get_latest_document_context()
        formatted_system_prompt = SYSTEM_PROMPT.format(
            student_context=student_context,
            doc_context=doc_context
        )



        # 2. Call Gemini
        # Use a model known for good multilingual support
        model = genai.GenerativeModel(
            "gemini-2.0-flash", # Switch to correct 2.0 flash
            system_instruction=formatted_system_prompt
        )
        
        chat_session = model.start_chat(history=history)
        response = chat_session.send_message(user_text)
        
        raw_ai_response = response.text
        
        # 3. Extract Metadata
        ai_response = raw_ai_response
        meta_match = re.search(r'\[\[META:\s*(.*?)\|(.*?)\]\]', raw_ai_response)
        
        if meta_match:
            p_name = meta_match.group(1).strip()
            status = meta_match.group(2).strip()
            
            # Update DB if we have valid data
            if p_name in ['Basheer', 'Rafeek', 'Aimu'] and status in ['Confirmed', 'Declined']:
                database.update_attendance(p_name, status)
            
            # Clean response for user/TTS
            ai_response = re.sub(r'\[\[META:.*?\]\]', '', raw_ai_response).strip()

        # 4. Save turn to DB
        database.add_conversation(user_text, ai_response)
        
        audio_url = generate_audio(ai_response)
        
        return {
            "response": ai_response,
            "audio_url": audio_url
        }, None
    except Exception as e:
        return None, str(e)


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_text = data.get('text')
    if not user_text:
        return jsonify({"error": "No text provided"}), 400

    result, error = get_ai_response(user_text)
    
    if error:
        if "429" in error or "Resource has been exhausted" in error:
            return jsonify({"error": "Quota exceeded. Please wait ~1 minute and try again."}), 429
        return jsonify({"error": f"Server Error: {error}"}), 500

    return jsonify(result)

@app.route('/get_context')
def get_context():
    text = database.get_latest_document_context()
    return jsonify({"context": text})

@app.route('/report')
def report():
    students = database.get_attendance_report()
    return render_template('report.html', students=students)

if __name__ == '__main__':
    app.run(port=5001, debug=True)
