"""
ORM models representing a single code analysis run.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, default="untitled.py")
    language = Column(String, default="python")
    score = Column(Float, nullable=False)
    lines_of_code = Column(Integer, default=0)
    num_functions = Column(Integer, default=0)
    num_classes = Column(Integer, default=0)
    avg_complexity = Column(Float, default=0.0)
    issues_json = Column(Text, default="[]")       # list of issue dicts, JSON-encoded
    issue_counts_json = Column(Text, default="{}")  # {category: count}, JSON-encoded
    created_at = Column(DateTime(timezone=True), server_default=func.now())
