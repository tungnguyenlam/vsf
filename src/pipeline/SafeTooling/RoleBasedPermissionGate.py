from typing import Optional

from src.pipeline.SafeTooling.PermissionGate import (
    PermissionGate,
    PermissionDecision,
    ToolPermission,
    UserContext,
    PermissionAction,
)


class RoleBasedPermissionGate(PermissionGate):
    def __init__(self, tool_permissions: dict[str, ToolPermission] = None):
        self._tool_permissions = tool_permissions or {}
        self._default_permission = ToolPermission(
            tool_name="*",
            required_roles=("user",),
            action=PermissionAction.ALLOW,
            description="Default permission for unknown tools",
        )

    def check_permission(self, tool_name: str, user: UserContext) -> PermissionDecision:
        tool_perm = self._tool_permissions.get(tool_name, self._default_permission)

        if tool_perm.action == PermissionAction.DENY:
            return PermissionDecision(
                allowed=False,
                tool_name=tool_name,
                user_id=user.user_id,
                action=PermissionAction.DENY,
                reason=f"Tool {tool_name} is explicitly denied",
                required_roles=tool_perm.required_roles,
                required_permissions=tool_perm.required_permissions,
                user_roles=user.roles,
                user_permissions=user.permissions,
            )

        if tool_perm.action == PermissionAction.REQUIRE_APPROVAL:
            return PermissionDecision(
                allowed=False,
                tool_name=tool_name,
                user_id=user.user_id,
                action=PermissionAction.REQUIRE_APPROVAL,
                reason=f"Tool {tool_name} requires explicit approval",
                required_roles=tool_perm.required_roles,
                required_permissions=tool_perm.required_permissions,
                user_roles=user.roles,
                user_permissions=user.permissions,
            )

        if tool_perm.required_roles:
            role_allowed = False
            for role in user.roles:
                if tool_perm.allows_role(role):
                    role_allowed = True
                    break
        else:
            role_allowed = True

        if tool_perm.required_permissions:
            perm_allowed = False
            for perm in user.permissions:
                if tool_perm.allows_permission(perm):
                    perm_allowed = True
                    break
        else:
            perm_allowed = True

        allowed = role_allowed and perm_allowed

        if not allowed:
            reason_parts = []
            if tool_perm.required_roles:
                reason_parts.append(f"requires role in {tool_perm.required_roles}")
            if tool_perm.required_permissions:
                reason_parts.append(f"requires permission in {tool_perm.required_permissions}")
            reason = f"Insufficient permissions for {tool_name}: " + "; ".join(reason_parts)
        else:
            reason = f"Access granted to {tool_name}"

        return PermissionDecision(
            allowed=allowed,
            tool_name=tool_name,
            user_id=user.user_id,
            action=PermissionAction.ALLOW if allowed else PermissionAction.DENY,
            reason=reason,
            required_roles=tool_perm.required_roles,
            required_permissions=tool_perm.required_permissions,
            user_roles=user.roles,
            user_permissions=user.permissions,
        )

    def get_tool_permission(self, tool_name: str) -> Optional[ToolPermission]:
        return self._tool_permissions.get(tool_name)

    def list_tool_permissions(self) -> dict[str, ToolPermission]:
        return dict(self._tool_permissions)

    def register_tool_permission(self, permission: ToolPermission) -> None:
        self._tool_permissions[permission.tool_name] = permission

    def unregister_tool_permission(self, tool_name: str) -> bool:
        if tool_name in self._tool_permissions:
            del self._tool_permissions[tool_name]
            return True
        return False

    def set_default_permission(self, permission: ToolPermission) -> None:
        self._default_permission = permission