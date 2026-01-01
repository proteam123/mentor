
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

def get_model():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("WARNING: GEMINI_API_KEY not set. Chat features will not work.")
        return None
        
    genai.configure(api_key=api_key)
    
    # Get LATEST context every time
    student_context = database.get_student_context()
    doc_context = database.get_latest_document_context()
    
    system_prompt = f"""
    You are a helpful Malayalam AI tutor and Faculty Advisor for Class S8 ADS. 
    Respond in Malayalam. 
    
    DATA CONTEXT (Student Records):
    {student_context}

    UPLOADED DOCUMENT CONTEXT (If any):
    {doc_context}
    
    INSTRUCTIONS:
    1. **INTERACTIVE MODE**: Do NOT dump all information at once. Break it down.
    2. **Step 1: IDENTIFY**: Ask "Who is this parent?" first. Verify against the list.
    3. **Step 2: NEW UPDATES**: If UPLOADED DOCUMENT CONTEXT is provided, summarize it and share it with the parent first after identification.
    4. **Step 3: ACADEMICS**: Find the SPECIFIC child for that parent (e.g., Basheer -> Abdullah). Report ONLY that child's results.
    5. **Step 4: DISCIPLINE**: Discuss ONLY that child's disciplinary record.
    6. **Step 5: ANNOUNCE**: Finally, mention the Parent Meeting on Jan 25th 2026.
    
    Keep responses SHORT (1-2 sentences). Wait for the parent to respond before moving to the next topic.
    FORMATTING: Do NOT use markdown (like **bold**). Use plain text only.

    METADATA: At the very end of EVERY response, you MUST append a metadata tag in this EXACT format:
    [[META: ParentName|AttendanceStatus]]
    - ParentName: Basheer, Rafeek, Aimu, or Unknown.
    - AttendanceStatus: Confirmed, Declined, or Unknown.
    Example: നമസ്കാരം! നിങ്ങളുടെ കുട്ടിയുടെ മാർക്കുകൾ പറയാം. [[META: Basheer|Unknown]]
    """
    
    return genai.GenerativeModel(
        "gemini-flash-lite-latest",  # Lite is fine for chat and saves quota
        system_instruction=system_prompt
    )

import re
from werkzeug.utils import secure_filename

# Ensure uploads folder exists
os.makedirs('uploads', exist_ok=True)

from flask import send_from_directory

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)

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

    try:
        # 1. Upload to Gemini
        gen_file = genai.upload_file(path=filepath)
        
        # 2. Polling for file state (Important for PDFs)
        import time
        for _ in range(10):  # Wait up to 20 seconds
            gen_file = genai.get_file(gen_file.name)
            if gen_file.state.name == "ACTIVE":
                break
            if gen_file.state.name == "FAILED":
                raise Exception("File processing failed on Google side.")
            print(f"File state: {gen_file.state.name}. Waiting...")
            time.sleep(2)

        # 3. Ask AI to summarize/OCR
        try:
            summary_model = genai.GenerativeModel("gemini-2.0-flash")
            response = summary_model.generate_content([
                "Read this document and summarize the key information a parent should know in 2 clear Malayalam sentences. Be extremely concise. Focus on names and specific instructions.",
                gen_file
            ])
        except Exception as model_err:
            print(f"Primary model failed (2.0-flash): {model_err}. Trying fallback...")
            summary_model = genai.GenerativeModel("gemini-flash-latest")
            response = summary_model.generate_content([
                "Read this document and summarize the key information a parent should know in 2 clear Malayalam sentences. Be extremely concise. Focus on names and specific instructions.",
                gen_file
            ])
        
        extracted_text = response.text
        if not extracted_text:
            raise Exception("AI returned empty summary. Try again.")
            
        print(f"Extracted info: {extracted_text}")
        
        # 4. Save to DB context
        database.add_document_context(extracted_text)
        
        # Clean up
        genai.delete_file(gen_file.name)
        
        return jsonify({
            "message": "File uploaded and context updated!",
            "learned": extracted_text,
            "file_url": url_for('uploaded_file', filename=filename)
        })
    except Exception as e:
        error_str = str(e)
        print(f"Upload Error: {error_str}")
        if "429" in error_str:
            return jsonify({"error": "Quota exceeded. Please wait 1 minute and try again."}), 429
        return jsonify({"error": f"OCR Error: {error_str}"}), 500

client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
twilio_number = os.getenv("TWILIO_PHONE_NUMBER")

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
    parent_number = request.form['parent_number']
    message = "നമസ്കാരം! നിങ്ങളുടെ കുട്ടി ഇന്നത്തെ ക്ലാസിൽ പങ്കെടുക്കാനായില്ല."

    call = client.calls.create(
        from_=twilio_number,
        to=parent_number,
        twiml=f'<Response><Say language="ml-IN" voice="Google.ml-IN-Standard-A">{message}</Say></Response>'
    )
    return f"Call initiated! SID: {call.sid}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_text = data.get('text')
    if not user_text:
        return jsonify({"error": "No text provided"}), 400

    model = get_model()
    if not model:
        return jsonify({"error": "Gemini API key not configured on server"}), 500

    try:
        # 1. Fetch recent history from DB
        past_convos = database.get_conversations()
        history = []
        recent_convos = past_convos[:10][::-1]
        for row in recent_convos:
            history.append({"role": "user", "parts": [row[1]]})
            history.append({"role": "model", "parts": [row[2]]})

        # 2. Start chat session
        chat_session = model.start_chat(history=history)
        
        # 3. Generate response (Single Call!)
        response = chat_session.send_message(user_text)
        raw_ai_response = response.text
        
        # 4. Extract Metadata
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

        # 5. Save turn to DB
        database.add_conversation(user_text, ai_response)
        
        audio_url = generate_audio(ai_response)
        
        return jsonify({
            "response": ai_response,
            "audio_url": audio_url
        })
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Resource has been exhausted" in error_msg:
            return jsonify({"error": "Quota exceeded. Please wait ~1 minute and try again."}), 429
        return jsonify({"error": f"Server Error: {error_msg}"}), 500

@app.route('/get_context')
def get_context():
    text = database.get_latest_document_context()
    return jsonify({"context": text})

@app.route('/report')
def report():
    students = database.get_attendance_report()
    return render_template('report.html', students=students)

if __name__ == '__main__':
    app.run(port=5000, debug=True)
