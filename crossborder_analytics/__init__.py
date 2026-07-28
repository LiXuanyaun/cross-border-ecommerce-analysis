"""CrossBorder AI Analytics domain package."""
from .service import AnalysisService, analyze_file
from .phase2_models import (
    AnalysisArtifacts, AnalysisRequest, Anomaly, CrossBorderAnalysisBundle,
    ActionItem, DiagnosisResult, EvidenceBundle, InsightView, MarketOpportunity,
    MetricDefinition, MetricSnapshot, ProductOpportunity, Recommendation,
)

__version__ = "3.1.1"
__all__ = [
    "AnalysisArtifacts", "AnalysisRequest", "AnalysisService", "Anomaly",
    "ActionItem", "CrossBorderAnalysisBundle", "DiagnosisResult", "EvidenceBundle",
    "InsightView", "MarketOpportunity", "MetricDefinition", "MetricSnapshot",
    "ProductOpportunity", "Recommendation", "analyze_file",
]
