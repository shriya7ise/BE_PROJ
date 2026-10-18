from fastapi import APIRouter
from app.schemas.company import Company

router = APIRouter()

SAMPLE_DATA = [
    {
        "id": 1,
        "name": "Vigilance Biotech",
        "description": "Advanced egg study company",
        "eggStudies": [
            {"id": 1, "phase": "Preclinical", "durationMonths": 18, "success": True},
            {"id": 2, "phase": "Clinical", "durationMonths": 24, "success": False}
        ],
        "financialHistory": [
            {"quarter": "Q1-2025", "revenue": 2.4, "rnd": 1.8},
            {"quarter": "Q2-2025", "revenue": 3.1, "rnd": 2.1}
        ],
        "signals": [{"value": 78, "type": "momentum"}]
    },
    {
        "id": 2,
        "name": "BioMed Research",
        "description": "Leading egg study platform",
        "eggStudies": [{"id": 3, "phase": "Preclinical", "durationMonths": 15, "success": True}],
        "financialHistory": [{"quarter": "Q1-2025", "revenue": 1.2, "rnd": 0.9}],
        "signals": []
    }
]

@router.get("/companies")
def get_companies():
    return SAMPLE_DATA

@router.get("/companies/{company_id}")
def get_company(company_id: int):
    for c in SAMPLE_DATA:
        if c["id"] == company_id:
            return c
    return {"error": "Company not found"}
