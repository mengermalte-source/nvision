import models
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./n-vision.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_pab_data():
    db = SessionLocal()
    try:
        projects = db.query(models.Project).all()
        for index, project in enumerate(projects):
            if project.pab_rank == 999 or project.pab_rank is None:
                project.pab_rank = index + 1
            if project.pab_status is None:
                project.pab_status = models.PABStatus.EVALUATION
        db.commit()
        print(f"PAB Daten für {len(projects)} Projekte initialisiert.")
    except Exception as e:
        print(f"Fehler: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_pab_data()
