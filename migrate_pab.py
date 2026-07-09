import sqlite3

def migrate():
    conn = sqlite3.connect('n-vision.db')
    cursor = conn.cursor()
    
    try:
        # Add columns if they don't exist
        cursor.execute("ALTER TABLE projects ADD COLUMN pab_status VARCHAR(20) DEFAULT 'EVALUATION'")
    except sqlite3.OperationalError:
        print("Column pab_status already exists or error.")
        
    try:
        cursor.execute("ALTER TABLE projects ADD COLUMN pab_rank INTEGER DEFAULT 999")
    except sqlite3.OperationalError:
        print("Column pab_rank already exists or error.")

    # Create project_comments table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        author_id INTEGER,
        text TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_pab_relevant BOOLEAN DEFAULT 1,
        FOREIGN KEY(project_id) REFERENCES projects(id),
        FOREIGN KEY(author_id) REFERENCES users(id)
    )
    """)
    
    # Initialize data
    cursor.execute("SELECT id FROM projects ORDER BY priority ASC")
    projects = cursor.fetchall()
    for index, (p_id,) in enumerate(projects):
        cursor.execute("UPDATE projects SET pab_rank = ?, pab_status = 'EVALUATION' WHERE id = ?", (index + 1, p_id))
        
    conn.commit()
    conn.close()
    print("Migration erfolgreich.")

if __name__ == "__main__":
    migrate()
