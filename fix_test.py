with open('tests/unit/auth/test_auth_router.py', 'r') as f:
    content = f.read()

# Find and replace the test function
old_func = '''    def test_list_project_permissions_success(self, client, mock_rbac_manager):
        """Test listing project permissions with access."""
        mock_rbac_manager.check_project_access.return_value = True

        mock_perm1 = MagicMock()
        mock_perm1.user_id = 1
        mock_perm1.project_id = 1
        mock_perm1.role = "editor"

        mock_perm2 = MagicMock()
        mock_perm2.user_id = 2
        mock_perm2.project_id = 1
        mock_perm2.role = "viewer"

        from src.audiobook_studio.models.user import ProjectPermission
        from sqlalchemy.orm import Session
        from unittest.mock import MagicMock

        mock_perm1 = MagicMock()
        mock_rbac_manager.get_user.side_effect = [
            MagicMock(username="user1"),
            MagicMock(username="user2"),
        ]

        app = client.app
        def mock_active_user():
            user = MagicMock()
            user.id = 1
            user.is_active = True
            return user

        # Override the get_db dependency
        def mock_get_db():
            try:
                yield mock_session
            finally:
                pass

        from src.audiobook_studio.database import get_db
        app.dependency_overrides[get_db] = mock_get_db
        app.dependency_overrides[get_current_active_user] = mock_active_user

        response = client.get("/api/auth/projects/1/permissions")

        if get_db in app.dependency_overrides:
            del app.dependency_overrides[get_db]
        if get_current_active_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_active_user]'''

new_func = '''    def test_list_project_permissions_success(self, client, mock_rbac_manager):
        """Test listing project permissions with access."""
        mock_rbac_manager.check_project_access.return_value = True

        from src.audiobook_studio.models.user import ProjectPermission
        from sqlalchemy.orm import Session
        from unittest.mock import MagicMock

        mock_perm1 = MagicMock()
        mock_perm1.user_id = 1
        mock_perm1.project_id = 1
        mock_perm1.role = "editor"

        mock_perm2 = MagicMock()
        mock_perm2.user_id = 2
        mock_perm2.project_id = 1
        mock_perm2.role = "viewer"

        # Create a mock session
        mock_session = MagicMock(spec=Session)
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_perm1, mock_perm2]
        mock_rbac_manager.get_user.side_effect = [
            MagicMock(username="user1"),
            MagicMock(username="user2"),
        ]

        app = client.app
        def mock_active_user():
            user = MagicMock()
            user.id = 1
            user.is_active = True
            return user

        # Override the get_db dependency
        def mock_get_db():
            try:
                yield mock_session
            finally:
                pass

        from src.audiobook_studio.database import get_db
        app.dependency_overrides[get_db] = mock_get_db
        app.dependency_overrides[get_current_active_user] = mock_active_user

        response = client.get("/api/auth/projects/1/permissions")

        if get_db in app.dependency_overrides:
            del app.dependency_overrides[get_db]
        if get_current_active_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_active_user]

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open('tests/unit/auth/test_auth_router.py', 'w') as f:
        f.write(content)
    print('Fixed!')
else:
    print('Pattern not found')