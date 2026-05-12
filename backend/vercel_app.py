"""
Vercel-optimized FastAPI app.
Only includes lightweight routes that work in serverless environment.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import health
from backend.api.routes import auth, profile, leads, stats, jobs, models
from backend.api.routes import schemes, funding, validate

app = FastAPI(title="LeadIQ API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://leadiq-dashboard.vercel.app",
        "https://leadiq-dashboard-*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(leads.router)
app.include_router(stats.router)
app.include_router(jobs.router)
app.include_router(models.router)
app.include_router(schemes.router)
app.include_router(funding.router)
app.include_router(validate.router)
