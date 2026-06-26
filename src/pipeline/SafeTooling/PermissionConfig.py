import json
import os
from pathlib import Path
from typing import Optional

from src.pipeline.SafeTooling.PermissionGate import (
    ToolPermission,
    PermissionAction,
)
from src.pipeline.SafeTooling.RoleBasedPermissionGate import RoleBasedPermissionGate


DEFAULT_PERMISSIONS = {
    "pii_analyze": ToolPermission(
        tool_name="pii_analyze",
        required_roles=("user", "admin"),
        action=PermissionAction.ALLOW,
        description="Analyze text for PII entities",
    ),
    "pii_anonymize": ToolPermission(
        tool_name="pii_anonymize",
        required_roles=("user", "admin"),
        action=PermissionAction.ALLOW,
        description="Anonymize PII in text",
    ),
    "prompt_injection_screen": ToolPermission(
        tool_name="prompt_injection_screen",
        required_roles=("user", "admin"),
        action=PermissionAction.ALLOW,
        description="Screen text for prompt injection attacks",
    ),
    "image_analyze": ToolPermission(
        tool_name="image_analyze",
        required_roles=("user", "admin"),
        action=PermissionAction.ALLOW,
        description="Analyze images for PII via OCR",
    ),
    "safety_router": ToolPermission(
        tool_name="safety_router",
        required_roles=("admin",),
        action=PermissionAction.REQUIRE_APPROVAL,
        description="Run VLM safety router (paid API call)",
    ),
    "data_review": ToolPermission(
        tool_name="data_review",
        required_roles=("reviewer", "admin"),
        action=PermissionAction.ALLOW,
        description="Access safety_v0 review queue and data",
    ),
    "override_labels": ToolPermission(
        tool_name="override_labels",
        required_roles=("reviewer", "admin"),
        action=PermissionAction.ALLOW,
        description="Save human label overrides",
    ),
    "export_data": ToolPermission(
        tool_name="export_data",
        required_roles=("admin",),
        action=PermissionAction.REQUIRE_APPROVAL,
        description="Export datasets and annotations",
    ),
    "admin_config": ToolPermission(
        tool_name="admin_config",
        required_roles=("admin",),
        action=PermissionAction.ALLOW,
        description="Modify permission configuration",
    ),
}


class PermissionConfig:
    def __init__(
        self,
        tool_permissions: dict[str, ToolPermission] = None,
        config_path: Optional[str] = None,
    ):
        self.tool_permissions = tool_permissions or dict(DEFAULT_PERMISSIONS)
        self.config_path = config_path

    def to_dict(self) -> dict:
        return {
            name: {
                "tool_name": perm.tool_name,
                "required_roles": list(perm.required_roles),
                "required_permissions": list(perm.required_permissions),
                "action": perm.action.value,
                "description": perm.description,
                "metadata": perm.metadata,
            }
            for name, perm in self.tool_permissions.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PermissionConfig":
        permissions = {}
        for name, perm_data in data.items():
            permissions[name] = ToolPermission(
                tool_name=perm_data.get("tool_name", name),
                required_roles=tuple(perm_data.get("required_roles", ())),
                required_permissions=tuple(perm_data.get("required_permissions", ())),
                action=PermissionAction(perm_data.get("action", "allow")),
                description=perm_data.get("description", ""),
                metadata=perm_data.get("metadata", {}),
            )
        return cls(tool_permissions=permissions)

    def save(self, path: Optional[str] = None) -> None:
        save_path = Path(path or self.config_path)
        if not save_path:
            raise ValueError("No config path specified")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: str) -> "PermissionConfig":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Permission config not found: {path}")
        data = json.loads(config_path.read_text(encoding="utf-8"))
        config = cls.from_dict(data)
        config.config_path = str(config_path)
        return config


def load_permission_config(config_path: Optional[str] = None) -> PermissionConfig:
    if config_path and Path(config_path).exists():
        return PermissionConfig.load(config_path)

    default_paths = [
        Path("config/permissions.json"),
        Path("config/permissions.yaml"),
        Path(".permissions.json"),
    ]

    for path in default_paths:
        if path.exists():
            return PermissionConfig.load(str(path))

    return PermissionConfig()