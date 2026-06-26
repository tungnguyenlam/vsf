from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class PermissionAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class ToolPermission:
    tool_name: str
    required_roles: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    action: PermissionAction = PermissionAction.ALLOW
    description: str = ""
    metadata: dict = field(default_factory=dict)

    def allows_role(self, role: str) -> bool:
        if not self.required_roles:
            return True
        return role in self.required_roles

    def allows_permission(self, permission: str) -> bool:
        if not self.required_permissions:
            return True
        return permission in self.required_permissions


@dataclass(frozen=True)
class UserContext:
    user_id: str
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)

    @classmethod
    def anonymous(cls) -> "UserContext":
        return cls(user_id="anonymous", roles=("anonymous",), permissions=())

    @classmethod
    def admin(cls, user_id: str = "admin") -> "UserContext":
        return cls(
            user_id=user_id,
            roles=("admin", "user"),
            permissions=("all",),
        )

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or "all" in self.permissions


@dataclass
class PermissionDecision:
    allowed: bool
    tool_name: str
    user_id: str
    action: PermissionAction
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    required_roles: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    user_roles: tuple[str, ...] = ()
    user_permissions: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "tool_name": self.tool_name,
            "user_id": self.user_id,
            "action": self.action.value,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "required_roles": list(self.required_roles),
            "required_permissions": list(self.required_permissions),
            "user_roles": list(self.user_roles),
            "user_permissions": list(self.user_permissions),
            "metadata": self.metadata,
        }


class PermissionGate(ABC):
    @abstractmethod
    def check_permission(self, tool_name: str, user: UserContext) -> PermissionDecision:
        pass

    @abstractmethod
    def get_tool_permission(self, tool_name: str) -> Optional[ToolPermission]:
        pass

    @abstractmethod
    def list_tool_permissions(self) -> dict[str, ToolPermission]:
        pass

    def require_permission(self, tool_name: str, user: UserContext) -> None:
        decision = self.check_permission(tool_name, user)
        if not decision.allowed:
            raise PermissionError(f"Access denied to {tool_name}: {decision.reason}")