from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app import models  # noqa: F401  (ensures models are registered before create_all)
from app.routers import auth, ingest, reconciliation, explain, pages

app = FastAPI(title="Reconciliation Dashboard")
Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(reconciliation.router)
app.include_router(explain.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}