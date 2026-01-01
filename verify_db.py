import database
try:
    print(database.get_student_context())
except Exception as e:
    print(f"Error: {e}")
