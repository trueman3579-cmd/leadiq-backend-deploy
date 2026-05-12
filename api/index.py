import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="LeadIQ API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://leadiq-dashboard.vercel.app", "https://leadiq-dashboard-*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health/live")
async def liveness():
    return {"status": "alive"}

@app.get("/api/health")
async def health():
    return {"status": "healthy", "version": "2.0.0"}
