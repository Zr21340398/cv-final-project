"""Explicit, content-bound run authorization without claiming human source QA."""

import json
from pathlib import Path

from .recording import file_hash

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVIEW_BASIS = "user_authorized_after_technical_and_ai_review"
DATA_CHECKSUMS = "data/manifests/gso-data-sha256.txt"


def _match_hash(label, expected, actual):
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(c not in "0123456789abcdef" for c in expected)
        or expected != actual
    ):
        raise ValueError(f"Run approval {label} SHA256 does not match the current evidence")


def validate_run_approval(path, manifest, selection, audit, split):
    """Validate user authorization; the caller must retain the unchanged QA audit.

    Evidence paths are relative to the project root for portable, frozen HPC
    bundles. This checks the checksum inventory's identity, not every data file
    listed in it; the deployment CPU preflight performs that full verification.
    """
    if not audit.get("technical_ready") or any(
        not isinstance(error, dict) or error.get("code") != "source_not_accepted"
        for error in audit.get("errors", [])
    ):
        raise ValueError("Run approval cannot bypass technical dataset errors")
    path = Path(path)
    approval_bytes = path.read_bytes()
    approval = json.loads(approval_bytes)
    if not isinstance(approval, dict) or approval.get("schema_version") != 1:
        raise ValueError("Run approval requires schema_version 1")
    if split != "dev" or approval.get("scope") != "dev":
        raise ValueError("Run approval is restricted to the dev split")
    if (
        not isinstance(approval.get("user_instruction"), str)
        or not approval["user_instruction"].strip()
        or approval.get("authorized_by") != "user"
        or approval.get("review_basis") != REVIEW_BASIS
        or approval.get("human_visual_qa_completed") is not False
    ):
        raise ValueError("Run approval must record explicit user authorization without claiming human QA")
    for label, actual in (
        ("manifest", file_hash(manifest)),
        ("selection", file_hash(selection)),
        ("roster", audit.get("roster_sha256")),
        ("render_protocol", audit.get("render_protocol_sha256")),
        ("data_checksums", file_hash(PROJECT_ROOT / DATA_CHECKSUMS)),
    ):
        _match_hash(label, approval.get(label + "_sha256"), actual)
    evidence = approval.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {"cpu", "ai"}:
        raise ValueError("Run approval requires both cpu and ai review evidence")
    root = PROJECT_ROOT.resolve()
    for role, record in evidence.items():
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError(f"Run approval {role} evidence requires a relative path and SHA256")
        relative = Path(record["path"])
        target = (root / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(root) or not target.is_file():
            raise ValueError(f"Run approval {role} evidence must be an existing file inside the project")
        _match_hash(role, record.get("sha256"), file_hash(target))
    # Bind the exact bytes that were validated, rather than rereading a mutable
    # approval file between validation and freezing the experiment context.
    import hashlib

    return hashlib.sha256(approval_bytes).hexdigest()
