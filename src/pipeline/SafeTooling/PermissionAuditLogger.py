import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.pipeline.SafeTooling.PermissionGate import PermissionAction, PermissionDecision


AUDIT_LOG_PATH = Path("webdemo/logs/permission_audit.jsonl")


class PermissionAuditLogger:
    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or AUDIT_LOG_PATH

    def log_decision(self, decision: PermissionDecision, context: dict = None) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = decision.to_dict()
        if context:
            record["context"] = context
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_denial(
        self,
        tool_name: str,
        user_id: str,
        reason: str,
        user_roles: tuple[str, ...] = (),
        user_permissions: tuple[str, ...] = (),
        context: dict = None,
    ) -> None:
        decision = PermissionDecision(
            allowed=False,
            tool_name=tool_name,
            user_id=user_id,
            action=PermissionAction.DENY,
            reason=reason,
            user_roles=user_roles,
            user_permissions=user_permissions,
            metadata=context or {},
        )
        self.log_decision(decision)

    def log_approval(
        self,
        tool_name: str,
        user_id: str,
        user_roles: tuple[str, ...] = (),
        user_permissions: tuple[str, ...] = (),
        context: dict = None,
    ) -> None:
        decision = PermissionDecision(
            allowed=True,
            tool_name=tool_name,
            user_id=user_id,
            action=PermissionAction.ALLOW,
            reason=f"Access granted to {tool_name}",
            user_roles=user_roles,
            user_permissions=user_permissions,
            metadata=context or {},
        )
        self.log_decision(decision)

    def read_recent(self, limit: int = 100) -> list[dict]:
        if not self.log_path.exists():
            return []
        records = []
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return list(reversed(records))[:limit]

    def clear(self) -> None:
        if self.log_path.exists():
            self.log_path.unlink()