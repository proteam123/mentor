import sqlite3
import datetime

DB_NAME = "conversations.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_text TEXT NOT NULL,
            ai_response TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            parent_name TEXT NOT NULL,
            class_info TEXT DEFAULT 'S8 ADS',
            roll_number INTEGER,
            academic_info TEXT,
            disciplinary_info TEXT,
            attendance_status TEXT DEFAULT 'Unknown'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS document_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            extracted_text TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    seed_data()

def add_document_context(text):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Replace existing context with newest one
    c.execute('DELETE FROM document_context')
    c.execute('INSERT INTO document_context (extracted_text) VALUES (?)', (text,))
    conn.commit()
    conn.close()

def get_latest_document_context():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT extracted_text FROM document_context ORDER BY timestamp DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""

def seed_data():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Check if empty - simplistic check, might need to drop table manually if schema changed
    c.execute('SELECT count(*) FROM students')
    if c.fetchone()[0] == 0:
        students = [
            # Name, Parent, Class, Roll, Academic, Disciplinary
            ('Abdullah', 'Basheer', 'S8 ADS', 1, 'Maths:PASS, Physics:PASS, Java:PASS, DS:FAIL', 'Ragging juniors'),
            ('Raaniya', 'Rafeek', 'S8 ADS', 2, 'Maths:PASS, Physics:PASS, Java:PASS, DS:PASS', 'Disobeying hostel rules'),
            ('Abu', 'Aimu', 'S8 ADS', 3, 'Maths:PASS, Physics:PASS, Java:PASS, DS:PASS', 'None')
        ]
        c.executemany('''
            INSERT INTO students (student_name, parent_name, class_info, roll_number, academic_info, disciplinary_info) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', students)
        conn.commit()
    conn.close()

def get_student_context():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT student_name, parent_name, class_info, academic_info, disciplinary_info FROM students')
    rows = c.fetchall()
    conn.close()
    
    context = "Class List (S8 ADS) - Student Records:\n"
    for row in rows:
        context += f"""
        - Student: {row[0]} (Parent: {row[1]})
          - Academic: {row[3]}
          - Disciplinary Issues: {row[4]}
        """
    
    announcements = "\n\n[GLOBAL ANNOUNCEMENT]\n- PARENT MEETING: 25 January 2026. Notify ALL parents about this compulsory meeting."
    
    return context + announcements

def add_conversation(user_text, ai_response):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('INSERT INTO conversations (user_text, ai_response) VALUES (?, ?)', (user_text, ai_response))
    conn.commit()
    conn.close()

def get_conversations():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT * FROM conversations ORDER BY timestamp DESC')
    rows = c.fetchall()
    conn.close()
    return rows

def update_attendance(parent_name, status):
    """Updates attendance status for a specific parent's student."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE students SET attendance_status = ? WHERE parent_name = ?', (status, parent_name))
    conn.commit()
    conn.close()

def get_attendance_report():
    """Returns a list of all students and their meeting attendance status."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT student_name, parent_name, roll_number, attendance_status FROM students')
    rows = c.fetchall()
    conn.close()
    return rows
