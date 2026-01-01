from dotenv import load_dotenv
import os

print("Current CWD:", os.getcwd())
loaded = load_dotenv(verbose=True)
print("load_dotenv returned:", loaded)
print("OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY"))
