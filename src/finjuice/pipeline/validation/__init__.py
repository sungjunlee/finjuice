"""
Schema validation for Banksalad XLSX files.

Provides pre-import validation to catch schema mismatches and provide
helpful error messages before the ingestion pipeline starts.
"""

from .validators import ValidationError, ValidationResult, validate_banksalad_xlsx

__all__ = ["ValidationError", "ValidationResult", "validate_banksalad_xlsx"]
