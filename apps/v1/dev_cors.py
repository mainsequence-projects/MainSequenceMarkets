from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from apps.v1.main import create_app

app = create_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
