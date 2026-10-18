from pydantic import BaseModel
from typing import List

class EggStudy(BaseModel):
    id: int
    phase: str
    durationMonths: int
    success: bool

class Company(BaseModel):
    id: int
    name: str
    description: str
    eggStudies: List[EggStudy]
    financialHistory: list
    signals: list
