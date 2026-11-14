from src.database import engine, Base
from src import models

Base.metadata.create_all(bind=engine)

print("Database tables created successfully.")