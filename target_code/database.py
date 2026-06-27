import sqlite3

def get_connection():
    return sqlite3.connect("app.db")

def save_user(user_id, username):
    """Saves user credentials and username to the local sqlite database."""
    conn = get_connection()
    cursor = conn.cursor()
    # Writes metadata to the 'users' table
    cursor.execute("INSERT INTO users (id, name) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()
    print(f"[DB] User {username} saved.")
#qwefefyjfghada