import sqlite3

def check_db(db_file):
    print(f"Checking {db_file}...")
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM projects WHERE name LIKE '%Dynamischer Tarif%' OR name LIKE '%UseCase2%';")
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(f"Found: {row[0]}")
        else:
            print("No matches found.")
        conn.close()
    except Exception as e:
        print(f"Error checking {db_file}: {e}")

check_db('n-vision.db')
check_db('prms.db')
