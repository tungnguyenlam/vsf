import pytest

from src.pipeline.SafeTooling import (
    PermissionGate,
    RoleBasedPermissionGate,
    UserContext,
    ToolPermission,
    PermissionAction,
    PermissionDecision,
    PermissionConfig,
    load_permission_config,
)


class TestUserContext:
    def test_anonymous_user(self):
        user = UserContext.anonymous()
        assert user.user_id == "anonymous"
        assert user.roles == ("anonymous",)
        assert user.permissions == ()
        assert user.has_role("anonymous")
        assert not user.has_role("user")

    def test_admin_user(self):
        user = UserContext.admin("test_admin")
        assert user.user_id == "test_admin"
        assert "admin" in user.roles
        assert "user" in user.roles
        assert "all" in user.permissions
        assert user.has_permission("any_permission")

    def test_custom_user(self):
        user = UserContext(
            user_id="test_user",
            roles=("user", "reviewer"),
            permissions=("pii_read", "pii_write"),
        )
        assert user.has_role("user")
        assert user.has_role("reviewer")
        assert not user.has_role("admin")
        assert user.has_permission("pii_read")
        assert not user.has_permission("unknown")


class TestToolPermission:
    def test_allows_any_role_when_empty(self):
        perm = ToolPermission(tool_name="test", required_roles=())
        assert perm.allows_role("any_role")

    def test_allows_specific_role(self):
        perm = ToolPermission(tool_name="test", required_roles=("admin", "reviewer"))
        assert perm.allows_role("admin")
        assert perm.allows_role("reviewer")
        assert not perm.allows_role("user")

    def test_allows_any_permission_when_empty(self):
        perm = ToolPermission(tool_name="test", required_permissions=())
        assert perm.allows_permission("any_permission")

    def test_allows_specific_permission(self):
        perm = ToolPermission(tool_name="test", required_permissions=("pii_read",))
        assert perm.allows_permission("pii_read")
        assert not perm.allows_permission("pii_write")


class TestRoleBasedPermissionGate:
    @pytest.fixture
    def gate(self):
        permissions = {
            "tool_a": ToolPermission(
                tool_name="tool_a",
                required_roles=("user", "admin"),
                action=PermissionAction.ALLOW,
            ),
            "tool_b": ToolPermission(
                tool_name="tool_b",
                required_roles=("admin",),
                action=PermissionAction.ALLOW,
            ),
            "tool_c": ToolPermission(
                tool_name="tool_c",
                required_roles=("admin",),
                action=PermissionAction.REQUIRE_APPROVAL,
            ),
            "tool_d": ToolPermission(
                tool_name="tool_d",
                required_roles=("user",),
                action=PermissionAction.DENY,
            ),
        }
        return RoleBasedPermissionGate(permissions)

    def test_allow_user_tool(self, gate):
        user = UserContext(user_id="user1", roles=("user",))
        decision = gate.check_permission("tool_a", user)
        assert decision.allowed
        assert decision.action == PermissionAction.ALLOW

    def test_deny_user_no_role(self, gate):
        user = UserContext(user_id="user1", roles=("user",))
        decision = gate.check_permission("tool_b", user)
        assert not decision.allowed
        assert decision.action == PermissionAction.DENY

    def test_allow_admin_tool(self, gate):
        user = UserContext.admin("admin1")
        decision = gate.check_permission("tool_b", user)
        assert decision.allowed
        assert decision.action == PermissionAction.ALLOW

    def test_require_approval(self, gate):
        user = UserContext.admin("admin1")
        decision = gate.check_permission("tool_c", user)
        assert not decision.allowed
        assert decision.action == PermissionAction.REQUIRE_APPROVAL

    def test_explicit_deny(self, gate):
        user = UserContext(user_id="user1", roles=("user",))
        decision = gate.check_permission("tool_d", user)
        assert not decision.allowed
        assert decision.action == PermissionAction.DENY
        assert "explicitly denied" in decision.reason

    def test_unknown_tool_uses_default(self, gate):
        user = UserContext(user_id="user1", roles=("user",))
        decision = gate.check_permission("unknown_tool", user)
        assert decision.allowed
        assert "default" in decision.reason.lower() or "unknown" in decision.reason.lower()

    def test_anonymous_user_denied(self, gate):
        user = UserContext.anonymous()
        decision = gate.check_permission("tool_a", user)
        assert not decision.allowed

    def test_get_tool_permission(self, gate):
        perm = gate.get_tool_permission("tool_a")
        assert perm is not None
        assert perm.tool_name == "tool_a"
        assert gate.get_tool_permission("nonexistent") is None

    def test_list_tool_permissions(self, gate):
        perms = gate.list_tool_permissions()
        assert "tool_a" in perms
        assert "tool_b" in perms
        assert len(perms) == 4

    def test_register_unregister(self, gate):
        new_perm = ToolPermission(
            tool_name="new_tool",
            required_roles=("user",),
            action=PermissionAction.ALLOW,
        )
        gate.register_tool_permission(new_perm)
        assert gate.get_tool_permission("new_tool") == new_perm
        gate.unregister_tool_permission("new_tool")
        assert gate.get_tool_permission("new_tool") is None

    def test_permission_decision_fields(self, gate):
        user = UserContext(user_id="test", roles=("user",))
        decision = gate.check_permission("tool_a", user)
        assert decision.tool_name == "tool_a"
        assert decision.user_id == "test"
        assert decision.required_roles == ("user", "admin")
        assert decision.user_roles == ("user",)
        assert decision.timestamp is not None

    def test_permission_decision_to_dict(self, gate):
        user = UserContext(user_id="test", roles=("user",))
        decision = gate.check_permission("tool_a", user)
        d = decision.to_dict()
        assert d["allowed"] is True
        assert d["tool_name"] == "tool_a"
        assert d["user_id"] == "test"
        assert d["action"] == "allow"
        assert "timestamp" in d


class TestPermissionConfig:
    def test_default_config(self):
        config = PermissionConfig()
        assert "pii_analyze" in config.tool_permissions
        assert "safety_router" in config.tool_permissions
        assert config.tool_permissions["safety_router"].action == PermissionAction.REQUIRE_APPROVAL

    def test_to_dict_roundtrip(self):
        config = PermissionConfig()
        data = config.to_dict()
        config2 = PermissionConfig.from_dict(data)
        assert set(config.tool_permissions.keys()) == set(config2.tool_permissions.keys())
        for name in config.tool_permissions:
            assert config.tool_permissions[name].tool_name == config2.tool_permissions[name].tool_name
            assert config.tool_permissions[name].action == config2.tool_permissions[name].action

    def test_save_load(self, tmp_path):
        config = PermissionConfig()
        path = tmp_path / "perms.json"
        config.save(str(path))
        loaded = PermissionConfig.load(str(path))
        assert set(config.tool_permissions.keys()) == set(loaded.tool_permissions.keys())


class TestLoadPermissionConfig:
    def test_load_default(self):
        config = load_permission_config()
        assert isinstance(config, PermissionConfig)
        assert "pii_analyze" in config.tool_permissions

    def test_load_from_file(self, tmp_path):
        config = PermissionConfig()
        path = tmp_path / "custom_perms.json"
        config.save(str(path))
        loaded = load_permission_config(str(path))
        assert isinstance(loaded, PermissionConfig)


class TestPermissionDecision:
    def test_decision_creation(self):
        decision = PermissionDecision(
            allowed=True,
            tool_name="test_tool",
            user_id="test_user",
            action=PermissionAction.ALLOW,
            reason="Access granted",
            required_roles=("user",),
            user_roles=("user", "admin"),
        )
        assert decision.allowed
        assert decision.tool_name == "test_tool"

    def test_decision_to_dict_includes_all_fields(self):
        decision = PermissionDecision(
            allowed=False,
            tool_name="test_tool",
            user_id="test_user",
            action=PermissionAction.DENY,
            reason="No permission",
            required_roles=("admin",),
            required_permissions=("special",),
            user_roles=("user",),
            user_permissions=("basic",),
            metadata={"extra": "info"},
        )
        d = decision.to_dict()
        assert d["allowed"] is False
        assert d["required_roles"] == ["admin"]
        assert d["required_permissions"] == ["special"]
        assert d["user_roles"] == ["user"]
        assert d["user_permissions"] == ["basic"]
        assert d["metadata"] == {"extra": "info"}


class TestPermissionGateInterface:
    def test_abstract_methods(self):
        class TestGate(PermissionGate):
            def check_permission(self, tool_name, user):
                return PermissionDecision(
                    allowed=True, tool_name=tool_name, user_id=user.user_id,
                    action=PermissionAction.ALLOW, reason="test"
                )

            def get_tool_permission(self, tool_name):
                return None

            def list_tool_permissions(self):
                return {}

        gate = TestGate()
        user = UserContext(user_id="test", roles=("user",))
        decision = gate.check_permission("tool", user)
        assert decision.allowed


class TestWebdemoUserResolution:
    """Pin the webdemo demo-default behaviour for missing auth headers.

    A header-less request is treated as a trusted single-user demo
    (``roles=("user",)``) so the local browser workflow keeps working without
    a real auth layer. Setting ``WEBDEMO_ANON_FORCE_DENY`` (or
    ``anon_force_deny=True`` to the factory) switches the default to
    ``UserContext.anonymous()`` so the permission gate denies access to
    every tool that requires a higher role.
    """

    def _resolve(self, headers, **kwargs):
        from webdemo.app import resolve_user_from_headers

        return resolve_user_from_headers(headers, **kwargs)

    def test_header_less_request_gets_demo_user_role(self):
        user = self._resolve({})
        assert user.user_id == "demo_user"
        assert user.roles == ("user",)
        assert user.permissions == ()

    def test_explicit_user_id_and_roles(self):
        user = self._resolve(
            {
                "X-User-ID": "alice",
                "X-User-Roles": "reviewer,user",
                "X-User-Permissions": "pii_read,pii_write",
            }
        )
        assert user.user_id == "alice"
        assert user.roles == ("reviewer", "user")
        assert user.permissions == ("pii_read", "pii_write")

    def test_anon_force_deny_flag_returns_anonymous(self):
        user = self._resolve({}, anon_force_deny=True)
        assert user.user_id == "anonymous"
        assert user.roles == ("anonymous",)

    def test_anon_force_deny_respects_explicit_user_id(self):
        # The flag only flips the default; an authenticated client is still
        # honoured verbatim. Any of the three auth headers is enough to opt out.
        for headers in (
            {"X-User-ID": "alice", "X-User-Roles": "admin"},
            {"X-User-Roles": "admin"},
            {"X-User-Permissions": "pii_read"},
        ):
            user = self._resolve(headers, anon_force_deny=True)
            assert user.user_id != "anonymous", headers
            assert "anonymous" not in user.roles, headers

    def test_anonymous_user_is_denied_for_pii_tool(self):
        """End-to-end through the default config: an anonymous request
        cannot reach any tool that requires the ``user`` role."""
        config = load_permission_config()
        gate = RoleBasedPermissionGate(config.tool_permissions)
        decision = gate.check_permission("pii_analyze", UserContext.anonymous())
        assert not decision.allowed
        assert decision.action == PermissionAction.DENY
        assert "user" in decision.reason

    def test_anonymous_user_is_denied_for_safety_router(self):
        config = load_permission_config()
        gate = RoleBasedPermissionGate(config.tool_permissions)
        user = UserContext.anonymous()
        decision = gate.check_permission("safety_router", user)
        assert not decision.allowed
        # safety_router requires explicit approval, which is the stronger
        # reject reason for that tool.
        assert decision.action == PermissionAction.REQUIRE_APPROVAL

    def test_get_current_user_respects_env_flag(self, monkeypatch):
        from webdemo import app as webdemo_app

        with webdemo_app.app.test_request_context("/", headers={}):
            monkeypatch.setenv("WEBDEMO_ANON_FORCE_DENY", "1")
            user = webdemo_app.get_current_user()
            assert user.user_id == "anonymous"

        with webdemo_app.app.test_request_context("/", headers={}):
            monkeypatch.delenv("WEBDEMO_ANON_FORCE_DENY", raising=False)
            user = webdemo_app.get_current_user()
            assert user.user_id == "demo_user"
            assert user.roles == ("user",)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])