import models
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./n-vision.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def check_project():
    db = SessionLocal()
    # Alle aktiven Projekte mit has_steering_board=True
    projects = db.query(models.Project).filter(models.Project.has_steering_board == True).all()
    print(f"Total projects in steering board: {len(projects)}")
    for p in projects:
        print(f"ID={p.id}, Name='{p.name}', Status={p.status}")
    db.close()

if __name__ == "__main__":
    check_project()
