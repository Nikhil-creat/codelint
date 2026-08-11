"""
AI Code Review Assistant — FastAPI backend.

Endpoints:
  POST /api/analyze         Analyze a code snippet, persist the result, return it.
  GET  /api/history         List past analyses (most recent first).
  GET  /api/analysis/{id}   Full detail for one past analysis.
  GET  /api/stats           Aggregate stats powering the dashboard.
  DELETE /api/analysis/{id} Remove a past analysis.
"""
import json
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from database import Base, engine, get_db
from models import Analysis
from analyzer import CodeAnalyzer

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Code Review Assistant", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    code: str
    filename: Optional[str] = "untitled.py"
    language: Optional[str] = "python"


@app.post("/api/analyze")
def analyze_code(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty.")

    result = CodeAnalyzer(payload.code).analyze()

    if result.get("syntax_error"):
        raise HTTPException(status_code=422, detail=f"Syntax error: {result['syntax_error']}")

    record = Analysis(
        filename=payload.filename or "untitled.py",
        language=payload.language or "python",
        score=result["score"],
        lines_of_code=result["lines_of_code"],
        num_functions=result["num_functions"],
        num_classes=result["num_classes"],
        avg_complexity=result["avg_complexity"],
        issues_json=json.dumps(result["issues"]),
        issue_counts_json=json.dumps(result["issue_counts"]),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "id": record.id,
        "filename": record.filename,
        "created_at": record.created_at,
        **result,
    }


@app.get("/api/history")
def get_history(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(Analysis)
        .order_by(Analysis.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "language": r.language,
            "score": r.score,
            "lines_of_code": r.lines_of_code,
            "num_functions": r.num_functions,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@app.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: int, db: Session = Depends(get_db)):
    r = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return {
        "id": r.id,
        "filename": r.filename,
        "language": r.language,
        "score": r.score,
        "lines_of_code": r.lines_of_code,
        "num_functions": r.num_functions,
        "num_classes": r.num_classes,
        "avg_complexity": r.avg_complexity,
        "issues": json.loads(r.issues_json),
        "issue_counts": json.loads(r.issue_counts_json),
        "created_at": r.created_at,
    }


@app.delete("/api/analysis/{analysis_id}")
def delete_analysis(analysis_id: int, db: Session = Depends(get_db)):
    r = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    db.delete(r)
    db.commit()
    return {"deleted": analysis_id}


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    rows = db.query(Analysis).order_by(Analysis.created_at.asc()).all()
    if not rows:
        return {
            "total_analyses": 0,
            "avg_score": 0,
            "score_trend": [],
            "issue_category_totals": {"bug": 0, "security": 0, "style": 0, "complexity": 0},
        }

    avg_score = db.query(sqlfunc.avg(Analysis.score)).scalar() or 0
    category_totals = {"bug": 0, "security": 0, "style": 0, "complexity": 0}
    for r in rows:
        counts = json.loads(r.issue_counts_json)
        for k, v in counts.items():
            category_totals[k] = category_totals.get(k, 0) + v

    return {
        "total_analyses": len(rows),
        "avg_score": round(avg_score, 1),
        "score_trend": [
            {"id": r.id, "filename": r.filename, "score": r.score, "created_at": r.created_at}
            for r in rows
        ],
        "issue_category_totals": category_totals,
    }


@app.get("/")
def root():
    return {"status": "ok", "message": "AI Code Review Assistant API is running."}
