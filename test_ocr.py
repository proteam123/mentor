import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

def test_ocr(image_path):
    print(f"Testing OCR with {image_path}...")
    try:
        # Use gemini-2.0-flash as it's the latest and should support multimodal well
        model = genai.GenerativeModel("gemini-2.0-flash")
        
        # Upload the file
        print("Uploading file to Gemini...")
        gen_file = genai.upload_file(path=image_path)
        print(f"File uploaded: {gen_file.name}")
        
        # Generate content
        print("Generating summary...")
        response = model.generate_content([
            "Read this document and summarize the key information a parent should know in 2 clear Malayalam sentences. Be extremely concise.",
            gen_file
        ])
        
        print(f"Raw response: {response.text}")
        
        # Cleanup
        genai.delete_file(gen_file.name)
        print("File deleted from Gemini.")
        
    except Exception as e:
        print(f"OCR Test Failed: {e}")

if __name__ == "__main__":
    # If there's an image in uploads, test it. Otherwise, mention no file found.
    uploads_dir = "uploads"
    files = [f for f in os.listdir(uploads_dir) if os.path.isfile(os.path.join(uploads_dir, f))]
    if files:
        test_ocr(os.path.join(uploads_dir, files[0]))
    else:
        print("No files found in uploads directory to test.")
