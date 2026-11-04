from flask import g

from services.supabase_service import SupabaseWorkspaceService


class EmptyVersionQuery:
    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return None


class EmptyVersionClient:
    def table(self, name):
        assert name == "chunk_versions"
        return EmptyVersionQuery()


def test_chunk_view_handles_chunk_without_any_version(app):
    with app.app_context():
        g.supabase_client = EmptyVersionClient()
        service = SupabaseWorkspaceService("workspace-files")
        view = service._chunk_view(
            {
                "id": "chunk-1",
                "current_version": 0,
                "team": {"name": "수소산업팀"},
                "document": {"title": "새 자료"},
                "lock_owner": None,
            }
        )

    assert view["latest_version_id"] is None
    assert view["latest_uploaded_by_name"] is None
    assert view["latest_updated_at"] is None
