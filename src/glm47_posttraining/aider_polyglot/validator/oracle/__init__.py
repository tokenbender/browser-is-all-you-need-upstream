"""Mandatory reference-oracle certification for Aider shadow tasks."""

from .oracle_cache import OracleReceiptCache
from .oracle_receipt import (
    ORACLE_RECEIPT_KIND,
    ORACLE_VALIDATOR_VERSION,
    OracleCertificationReceipt,
    OracleValidationConfig,
    assert_receipt_integrity,
)
from .oracle_report import OracleCertificationReport, write_oracle_certification_report
from .oracle_runner import (
    OracleCertificationError,
    certify_task_oracle,
    load_reference_solution,
    require_certified_oracle,
)

__all__ = [
    "ORACLE_RECEIPT_KIND",
    "ORACLE_VALIDATOR_VERSION",
    "OracleCertificationError",
    "OracleCertificationReceipt",
    "OracleCertificationReport",
    "OracleReceiptCache",
    "OracleValidationConfig",
    "assert_receipt_integrity",
    "certify_task_oracle",
    "load_reference_solution",
    "require_certified_oracle",
    "write_oracle_certification_report",
]
