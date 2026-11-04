from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import current_app, g

from .errors import ConflictError, IntegrationError, NotFoundError, ValidationError
from .identity import DELETE_CHUNK_CONFIRMATION_TEXT, DELETE_CONFIRMATION_TEXT
from .permission_service import (
    is_master,
    require_edit,
    require_final_manager,
    require_force_unlock,
    require_master,
    require_review,
)


class SupabaseWorkspaceService:
    """User-JWT scoped Supabase repository. All workflow writes use database RPCs."""

    def __init__(self, bucket: str):
        self.bucket = bucket

    @staticmethod
    def _client():
        client = getattr(g, "supabase_client", None)
        if client is None:
            raise IntegrationError("사용자 범위 Supabase 연결이 없습니다. 다시 로그인하세요.")
        return client

    def list_teams(self) -> list[dict]:
        return self._client().table("teams").select("*").order("name").execute().data or []

    def list_profiles(self) -> list[dict]:
        rows = (
            self._client()
            .table("profiles")
            .select("*, team:teams(name)")
            .order("name")
            .execute()
            .data
            or []
        )
        return [self._profile_view(row) for row in rows]

    def get_profile(self, profile_id: str) -> dict | None:
        response = (
            self._client()
            .table("profiles")
            .select("*, team:teams(name)")
            .eq("id", profile_id)
            .maybe_single()
            .execute()
        )
        data = getattr(response, "data", None)
        return self._profile_view(data) if data else None

    def list_documents(self) -> list[dict]:
        documents = (
            self._client().table("documents").select("*").order("created_at", desc=True).execute().data
            or []
        )
        chunks = self._client().table("chunks").select("document_id,status").execute().data or []
        for document in documents:
            rows = [row for row in chunks if row["document_id"] == document["id"]]
            approved = sum(row["status"] == "approved" for row in rows)
            document["chunk_count"] = len(rows)
            document["approved_count"] = approved
            document["progress"] = round((approved / len(rows)) * 100) if rows else 0
        return documents

    def get_document(self, document_id: str) -> dict:
        response = (
            self._client()
            .table("documents")
            .select("*")
            .eq("id", document_id)
            .maybe_single()
            .execute()
        )
        data = getattr(response, "data", None)
        if not data:
            raise NotFoundError("자료를 찾을 수 없습니다.")
        return data

    def list_chunks(self, document_id: str, team_id: str = "", status: str = "") -> list[dict]:
        self.get_document(document_id)
        query = (
            self._client()
            .table("chunks")
            .select(
                "*, team:teams(name), document:documents(title), "
                "lock_owner:profiles!chunks_locked_by_fkey(name)"
            )
            .eq("document_id", document_id)
            .order("display_order")
        )
        if team_id:
            query = query.eq("team_id", team_id)
        if status:
            query = query.eq("status", status)
        rows = query.execute().data or []
        return [self._chunk_view(row) for row in rows]

    def get_chunk(self, chunk_id: str) -> dict:
        response = (
            self._client()
            .table("chunks")
            .select(
                "*, team:teams(name), document:documents(title), "
                "lock_owner:profiles!chunks_locked_by_fkey(name)"
            )
            .eq("id", chunk_id)
            .maybe_single()
            .execute()
        )
        data = getattr(response, "data", None)
        if not data:
            raise NotFoundError("문서 조각을 찾을 수 없습니다.")
        return self._chunk_view(data)

    def list_versions(self, chunk_id: str) -> list[dict]:
        self.get_chunk(chunk_id)
        rows = (
            self._client()
            .table("chunk_versions")
            .select(
                "*, uploader:profiles!chunk_versions_uploaded_by_fkey"
                "(name, team:teams(name))"
            )
            .eq("chunk_id", chunk_id)
            .order("version_no", desc=True)
            .execute()
            .data
            or []
        )
        return [self._version_view(row) for row in rows]

    def get_version(self, version_id: str) -> dict:
        response = (
            self._client()
            .table("chunk_versions")
            .select(
                "*, uploader:profiles!chunk_versions_uploaded_by_fkey"
                "(name, team:teams(name))"
            )
            .eq("id", version_id)
            .maybe_single()
            .execute()
        )
        data = getattr(response, "data", None)
        if not data:
            raise NotFoundError("버전을 찾을 수 없습니다.")
        return self._version_view(data)

    def list_review_queue(self, user: dict) -> list[dict]:
        if user.get("role") != "reviewer":
            return []
        document_ids = [row["id"] for row in self.list_documents()]
        result = []
        for document_id in document_ids:
            result.extend(self.list_chunks(document_id, user["team_id"], "submitted"))
        return result

    def dashboard(self, document_id: str, team_id: str = "", status: str = "") -> dict:
        document = self.get_document(document_id)
        all_chunks = self.list_chunks(document_id)
        filtered = all_chunks
        if team_id:
            filtered = [row for row in filtered if row["team_id"] == team_id]
        if status:
            filtered = [row for row in filtered if row["status"] == status]
        counts = {name: 0 for name in ("not_started", "editing", "submitted", "approved", "rejected")}
        for chunk in all_chunks:
            counts[chunk["status"]] += 1
        required = [row for row in all_chunks if row["is_required"]]
        approved = sum(row["status"] == "approved" for row in required)
        return {
            "document": document,
            "chunks": filtered,
            "counts": counts,
            "total": len(all_chunks),
            "required_total": len(required),
            "progress": round((approved / len(required)) * 100) if required else 100,
            "can_confirm": bool(required) and approved == len(required) and document["status"] != "confirmed",
            "confirmations": self.list_confirmations(document_id),
        }

    def list_confirmations(self, document_id: str) -> list[dict]:
        rows = (
            self._client()
            .table("document_confirmations")
            .select(
                "*, confirmer:profiles!document_confirmations_confirmed_by_fkey(name), "
                "items:document_confirmation_items(*)"
            )
            .eq("document_id", document_id)
            .order("confirmed_at", desc=True)
            .execute()
            .data
            or []
        )
        for row in rows:
            row["confirmed_by_name"] = (row.pop("confirmer", None) or {}).get("name", "")
        return rows

    def checkout_chunk(self, user: dict, chunk_id: str) -> dict:
        chunk = self.get_chunk(chunk_id)
        require_edit(user, chunk)
        if is_master(user):
            admin = self._admin_client()
            document = (
                admin.table("documents")
                .select("status")
                .eq("id", chunk["document_id"])
                .maybe_single()
                .execute()
                .data
            )
            if not document:
                raise NotFoundError("자료를 찾을 수 없습니다.")
            if document["status"] == "confirmed":
                raise ConflictError("최종확정된 자료는 수정할 수 없습니다.")
            if chunk.get("locked_by") and chunk["locked_by"] != user["id"]:
                owner = chunk.get("locked_by_name") or "다른 사용자"
                raise ConflictError(f"현재 {owner}님이 편집 중입니다.")
            updated = (
                admin.table("chunks")
                .update(
                    {
                        "locked_by": user["id"],
                        "locked_at": datetime.now(UTC).isoformat(),
                        "locked_version_no": chunk["current_version"],
                        "status": "editing",
                    }
                )
                .eq("id", chunk_id)
                .execute()
                .data
                or []
            )
            if not updated:
                raise ConflictError("편집 잠금을 획득하지 못했습니다.")
            self._sync_document_status_admin(admin, chunk["document_id"])
            self._log_admin(admin, user, "checkout", chunk["document_id"], chunk_id)
            return self.get_chunk(chunk_id)
        self._rpc("checkout_chunk", {"p_chunk_id": chunk_id})
        return self.get_chunk(chunk_id)

    def checkin_chunk(self, user: dict, chunk_id: str, upload, change_reason: str, kordoc) -> dict:
        if not change_reason.strip():
            raise ValidationError("변경 사유를 입력하세요.")
        chunk = self.get_chunk(chunk_id)
        require_edit(user, chunk)
        if is_master(user):
            return self._checkin_chunk_as_master(
                user, chunk, upload, change_reason.strip(), kordoc
            )
        versions = self.list_versions(chunk_id)
        previous = next((row for row in versions if row["version_no"] == chunk["current_version"]), None)
        previous_content = None
        if previous:
            previous_content = self._client().storage.from_(self.bucket).download(previous["storage_path"])

        object_name = f"{uuid4()}{upload.extension}"
        storage_path = f"documents/{chunk['document_id']}/chunks/{chunk_id}/{object_name}"
        try:
            self._client().storage.from_(self.bucket).upload(
                storage_path,
                upload.content,
                file_options={
                    "content-type": (
                        "application/haansofthwpx" if upload.extension == ".hwpx" else "application/x-hwp"
                    ),
                    "upsert": "false",
                },
            )
            data = self._rpc(
                "checkin_chunk",
                {
                    "p_chunk_id": chunk_id,
                    "p_storage_path": storage_path,
                    "p_change_reason": change_reason.strip(),
                    "p_expected_version": chunk["current_version"],
                    "p_original_filename": upload.filename,
                    "p_file_size": upload.size,
                    "p_sha256": upload.sha256,
                },
            )
        except Exception:
            try:
                self._client().storage.from_(self.bucket).remove([storage_path])
            except Exception:
                pass
            raise

        version_id = self._rpc_row_id(data)
        comparison = kordoc.compare_bytes(
            previous_content,
            upload.content,
            Path(previous["original_filename"]).suffix if previous else upload.extension,
            upload.extension,
        )
        self._record_diff(version_id, comparison)
        return self.get_version(version_id)

    def retry_diff(self, user: dict, version_id: str, kordoc) -> dict:
        version = self.get_version(version_id)
        chunk = self.get_chunk(version["chunk_id"])
        require_edit(user, chunk)
        versions = self.list_versions(chunk["id"])
        previous = next((row for row in versions if row["version_no"] == version["version_no"] - 1), None)
        if is_master(user):
            admin = self._admin_client()
            old_content = (
                admin.storage.from_(self.bucket).download(previous["storage_path"])
                if previous
                else None
            )
            new_content = admin.storage.from_(self.bucket).download(version["storage_path"])
            comparison = kordoc.compare_bytes(
                old_content,
                new_content,
                Path(previous["original_filename"]).suffix if previous else ".hwpx",
                Path(version["original_filename"]).suffix,
            )
            self._record_diff_admin(admin, version_id, comparison)
            return self.get_version(version_id)
        old_content = (
            self._client().storage.from_(self.bucket).download(previous["storage_path"])
            if previous
            else None
        )
        new_content = self._client().storage.from_(self.bucket).download(version["storage_path"])
        comparison = kordoc.compare_bytes(
            old_content,
            new_content,
            Path(previous["original_filename"]).suffix if previous else ".hwpx",
            Path(version["original_filename"]).suffix,
        )
        self._record_diff(version_id, comparison)
        return self.get_version(version_id)

    def review_chunk(self, user: dict, chunk_id: str, action: str, comment: str) -> dict:
        chunk = self.get_chunk(chunk_id)
        require_review(user, chunk)
        self._rpc(
            "review_chunk",
            {"p_chunk_id": chunk_id, "p_action": action, "p_comment": comment.strip() or None},
        )
        return self.get_chunk(chunk_id)

    def force_unlock(self, user: dict, chunk_id: str, comment: str = "") -> dict:
        chunk = self.get_chunk(chunk_id)
        require_force_unlock(user, chunk)
        if is_master(user):
            if not chunk.get("locked_by"):
                raise ConflictError("현재 잠금 상태가 아닙니다.")
            admin = self._admin_client()
            updated = (
                admin.table("chunks")
                .update(
                    {
                        "status": "not_started" if chunk["current_version"] == 0 else "rejected",
                        "approved_version_id": None,
                        "locked_by": None,
                        "locked_at": None,
                        "locked_version_no": None,
                    }
                )
                .eq("id", chunk_id)
                .execute()
                .data
                or []
            )
            if not updated:
                raise ConflictError("잠금을 해제하지 못했습니다.")
            self._sync_document_status_admin(admin, chunk["document_id"])
            self._log_admin(
                admin,
                user,
                "force_unlock",
                chunk["document_id"],
                chunk_id,
                {"previous_locked_by": chunk["locked_by"], "comment": comment.strip() or None},
            )
            return self.get_chunk(chunk_id)
        self._rpc(
            "force_unlock_chunk",
            {"p_chunk_id": chunk_id, "p_comment": comment.strip() or None},
        )
        return self.get_chunk(chunk_id)

    def confirm_document(self, user: dict, document_id: str) -> dict:
        require_final_manager(user)
        data = self._rpc("confirm_document", {"p_document_id": document_id})
        confirmation_id = self._rpc_row_id(data)
        return next(
            row for row in self.list_confirmations(document_id) if row["id"] == confirmation_id
        )

    def download_version(self, version_id: str) -> tuple[bytes, str]:
        version = self.get_version(version_id)
        content = self._client().storage.from_(self.bucket).download(version["storage_path"])
        return content, version["original_filename"]

    def set_profile_active(self, user: dict, profile_id: str, active: bool) -> dict:
        require_final_manager(user)
        self._rpc("set_profile_active", {"p_profile_id": profile_id, "p_active": active})
        profile = self.get_profile(profile_id)
        if not profile:
            raise NotFoundError("사용자를 찾을 수 없습니다.")
        return profile

    def create_document(self, user: dict, title: str, description: str) -> dict:
        require_final_manager(user)
        data = self._rpc(
            "create_document",
            {"p_title": title.strip(), "p_description": description.strip() or None},
        )
        return self.get_document(self._rpc_row_id(data))

    def create_chunk(self, user: dict, document_id: str, code: str, title: str, team_id: str) -> dict:
        require_final_manager(user)
        data = self._rpc(
            "create_chunk",
            {
                "p_document_id": document_id,
                "p_chunk_code": code.strip(),
                "p_title": title.strip(),
                "p_team_id": team_id,
            },
        )
        return self.get_chunk(self._rpc_row_id(data))

    def update_document_title(self, user: dict, document_id: str, title: str) -> dict:
        require_master(user)
        new_title = title.strip()
        if not new_title:
            raise ValidationError("자료명을 입력하세요.")
        admin = self._admin_client()
        document = (
            admin.table("documents")
            .select("*")
            .eq("id", document_id)
            .maybe_single()
            .execute()
            .data
        )
        if not document:
            raise NotFoundError("자료를 찾을 수 없습니다.")
        if document["status"] == "confirmed":
            raise ValidationError("최종확정된 자료의 이름은 변경할 수 없습니다.")
        updated = (
            admin.table("documents")
            .update({"title": new_title})
            .eq("id", document_id)
            .execute()
            .data
            or []
        )
        if not updated:
            raise ConflictError("자료명을 변경하지 못했습니다.")
        self._log_admin(
            admin,
            user,
            "update_document_title",
            document_id,
            metadata={"old_title": document["title"], "new_title": new_title},
        )
        return self.get_document(document_id)

    def update_chunk_title(self, user: dict, chunk_id: str, title: str) -> dict:
        require_master(user)
        new_title = title.strip()
        if not new_title:
            raise ValidationError("조각명을 입력하세요.")
        admin = self._admin_client()
        chunk = (
            admin.table("chunks")
            .select("*")
            .eq("id", chunk_id)
            .maybe_single()
            .execute()
            .data
        )
        if not chunk:
            raise NotFoundError("문서 조각을 찾을 수 없습니다.")
        document = (
            admin.table("documents")
            .select("status")
            .eq("id", chunk["document_id"])
            .maybe_single()
            .execute()
            .data
        )
        if not document:
            raise NotFoundError("자료를 찾을 수 없습니다.")
        if document["status"] == "confirmed":
            raise ValidationError("최종확정된 자료의 조각명은 변경할 수 없습니다.")
        updated = (
            admin.table("chunks")
            .update({"title": new_title})
            .eq("id", chunk_id)
            .execute()
            .data
            or []
        )
        if not updated:
            raise ConflictError("조각명을 변경하지 못했습니다.")
        self._log_admin(
            admin,
            user,
            "update_chunk_title",
            chunk["document_id"],
            chunk_id,
            {"old_title": chunk["title"], "new_title": new_title},
        )
        return self.get_chunk(chunk_id)

    def delete_chunk(self, user: dict, chunk_id: str, confirmation_text: str) -> dict:
        require_master(user)
        if confirmation_text.strip() != DELETE_CHUNK_CONFIRMATION_TEXT:
            raise ValidationError(
                f"조각을 영구 삭제하려면 '{DELETE_CHUNK_CONFIRMATION_TEXT}'를 정확히 입력하세요."
            )
        admin = self._admin_client()
        chunk = (
            admin.table("chunks")
            .select("*")
            .eq("id", chunk_id)
            .maybe_single()
            .execute()
            .data
        )
        if not chunk:
            raise NotFoundError("삭제할 문서 조각을 찾을 수 없습니다.")
        document = (
            admin.table("documents")
            .select("status")
            .eq("id", chunk["document_id"])
            .maybe_single()
            .execute()
            .data
        )
        if not document:
            raise NotFoundError("자료를 찾을 수 없습니다.")
        if document["status"] == "confirmed":
            raise ValidationError("최종확정된 자료의 조각은 삭제할 수 없습니다.")
        if chunk.get("locked_by"):
            raise ConflictError("편집 중인 조각은 잠금을 해제한 후 삭제하세요.")

        versions = (
            admin.table("chunk_versions")
            .select("id,storage_path")
            .eq("chunk_id", chunk_id)
            .execute()
            .data
            or []
        )
        storage_paths = [str(row["storage_path"]) for row in versions if row.get("storage_path")]
        self._log_admin(
            admin,
            user,
            "delete_chunk",
            chunk["document_id"],
            chunk_id,
            {
                "deleted_chunk_id": chunk_id,
                "chunk_code": chunk["chunk_code"],
                "title": chunk["title"],
                "version_file_count": len(storage_paths),
            },
        )
        admin.table("reviews").delete().eq("chunk_id", chunk_id).execute()
        if chunk.get("approved_version_id"):
            admin.table("chunks").update({"approved_version_id": None}).eq("id", chunk_id).execute()
        deleted = admin.table("chunks").delete().eq("id", chunk_id).execute().data or []
        if not deleted:
            raise ConflictError("문서 조각을 삭제하지 못했습니다.")
        self._sync_document_status_admin(admin, chunk["document_id"])

        cleanup_failed = False
        if storage_paths:
            try:
                admin.storage.from_(self.bucket).remove(storage_paths)
            except Exception:
                cleanup_failed = True
        return {
            "id": chunk_id,
            "document_id": chunk["document_id"],
            "title": chunk["title"],
            "storage_cleanup_failed": cleanup_failed,
        }

    def delete_document(self, user: dict, document_id: str, confirmation_text: str) -> dict:
        require_master(user)
        if confirmation_text.strip() != DELETE_CONFIRMATION_TEXT:
            raise ValidationError(f"영구 삭제하려면 '{DELETE_CONFIRMATION_TEXT}'를 정확히 입력하세요.")

        admin = self._admin_client()
        document_response = (
            admin.table("documents")
            .select("*")
            .eq("id", document_id)
            .maybe_single()
            .execute()
        )
        document = getattr(document_response, "data", None)
        if not document:
            raise NotFoundError("삭제할 자료를 찾을 수 없습니다.")
        if document.get("status") == "confirmed":
            raise ValidationError("최종확정된 자료는 영구 삭제할 수 없습니다.")

        successor = (
            admin.table("documents")
            .select("id")
            .eq("previous_document_id", document_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if successor:
            raise ValidationError("후속 개정 자료가 존재하는 자료는 영구 삭제할 수 없습니다.")

        chunks = (
            admin.table("chunks").select("id").eq("document_id", document_id).execute().data
            or []
        )
        chunk_ids = [str(row["id"]) for row in chunks]
        storage_paths: list[str] = []
        if chunk_ids:
            versions = (
                admin.table("chunk_versions")
                .select("storage_path")
                .in_("chunk_id", chunk_ids)
                .execute()
                .data
                or []
            )
            storage_paths = [str(row["storage_path"]) for row in versions if row.get("storage_path")]

        admin.table("activity_logs").insert(
            {
                "user_id": user["id"],
                "action": "delete_document",
                "document_id": document_id,
                "metadata": {
                    "deleted_document_id": document_id,
                    "title": document.get("title", ""),
                    "chunk_count": len(chunk_ids),
                    "version_file_count": len(storage_paths),
                },
            }
        ).execute()

        deleted = admin.table("documents").delete().eq("id", document_id).execute().data or []
        if not deleted:
            raise ConflictError("자료를 삭제하지 못했습니다.")

        cleanup_failed = False
        if storage_paths:
            try:
                admin.storage.from_(self.bucket).remove(storage_paths)
            except Exception:
                cleanup_failed = True

        return {
            "id": document_id,
            "title": document.get("title", ""),
            "storage_cleanup_failed": cleanup_failed,
        }

    def _checkin_chunk_as_master(self, user: dict, chunk: dict, upload, change_reason: str, kordoc) -> dict:
        admin = self._admin_client()
        raw_chunk = (
            admin.table("chunks")
            .select("*")
            .eq("id", chunk["id"])
            .maybe_single()
            .execute()
            .data
        )
        if not raw_chunk:
            raise NotFoundError("문서 조각을 찾을 수 없습니다.")
        if raw_chunk.get("locked_by") != user["id"]:
            raise ConflictError("체크아웃한 사용자만 수정본을 제출할 수 있습니다.")
        if raw_chunk.get("locked_version_no") != raw_chunk["current_version"]:
            raise ConflictError("편집 중 새 버전이 생성되었습니다. 최신 버전으로 다시 시작하세요.")
        document = (
            admin.table("documents")
            .select("status")
            .eq("id", raw_chunk["document_id"])
            .maybe_single()
            .execute()
            .data
        )
        if not document:
            raise NotFoundError("자료를 찾을 수 없습니다.")
        if document["status"] == "confirmed":
            raise ConflictError("최종확정된 자료는 수정할 수 없습니다.")

        previous = None
        previous_content = None
        if raw_chunk["current_version"] > 0:
            previous = (
                admin.table("chunk_versions")
                .select("*")
                .eq("chunk_id", raw_chunk["id"])
                .eq("version_no", raw_chunk["current_version"])
                .maybe_single()
                .execute()
                .data
            )
            if not previous:
                raise ConflictError("현재 버전 파일 정보를 찾을 수 없습니다.")
            previous_content = admin.storage.from_(self.bucket).download(previous["storage_path"])

        version_no = raw_chunk["current_version"] + 1
        object_name = f"{uuid4()}{upload.extension}"
        storage_path = (
            f"documents/{raw_chunk['document_id']}/chunks/{raw_chunk['id']}/{object_name}"
        )
        version_id = ""
        committed = False
        try:
            admin.storage.from_(self.bucket).upload(
                storage_path,
                upload.content,
                file_options={
                    "content-type": (
                        "application/haansofthwpx"
                        if upload.extension == ".hwpx"
                        else "application/x-hwp"
                    ),
                    "upsert": "false",
                },
            )
            inserted = (
                admin.table("chunk_versions")
                .insert(
                    {
                        "chunk_id": raw_chunk["id"],
                        "version_no": version_no,
                        "storage_path": storage_path,
                        "original_filename": upload.filename,
                        "file_size": upload.size,
                        "sha256": upload.sha256,
                        "uploaded_by": user["id"],
                        "change_reason": change_reason,
                        "diff_status": (
                            "not_applicable" if raw_chunk["current_version"] == 0 else "pending"
                        ),
                        "diff_summary": (
                            "최초 버전으로 비교 대상이 없습니다."
                            if raw_chunk["current_version"] == 0
                            else None
                        ),
                    }
                )
                .execute()
                .data
                or []
            )
            if not inserted:
                raise ConflictError("새 버전 정보를 저장하지 못했습니다.")
            version_id = str(inserted[0]["id"])
            updated = (
                admin.table("chunks")
                .update(
                    {
                        "current_version": version_no,
                        "status": "submitted",
                        "approved_version_id": None,
                        "locked_by": None,
                        "locked_at": None,
                        "locked_version_no": None,
                    }
                )
                .eq("id", raw_chunk["id"])
                .eq("locked_by", user["id"])
                .eq("current_version", raw_chunk["current_version"])
                .execute()
                .data
                or []
            )
            if not updated:
                raise ConflictError("편집 중 버전 상태가 변경되었습니다. 다시 시도하세요.")
            committed = True
            self._sync_document_status_admin(admin, raw_chunk["document_id"])
            self._log_admin(
                admin,
                user,
                "checkin",
                raw_chunk["document_id"],
                raw_chunk["id"],
                {"version_id": version_id, "version_no": version_no},
            )
        except Exception:
            if not committed:
                if version_id:
                    try:
                        admin.table("chunk_versions").delete().eq("id", version_id).execute()
                    except Exception:
                        pass
                try:
                    admin.storage.from_(self.bucket).remove([storage_path])
                except Exception:
                    pass
            raise

        comparison = kordoc.compare_bytes(
            previous_content,
            upload.content,
            Path(previous["original_filename"]).suffix if previous else upload.extension,
            upload.extension,
        )
        self._record_diff_admin(admin, version_id, comparison)
        return self.get_version(version_id)

    @staticmethod
    def _record_diff_admin(admin, version_id: str, comparison: dict) -> None:
        admin.table("chunk_versions").update(
            {
                "diff_status": comparison["status"],
                "diff_summary": comparison["summary"],
                "diff_data": comparison["data"],
                "diff_error": comparison["error"],
            }
        ).eq("id", version_id).execute()

    @staticmethod
    def _sync_document_status_admin(admin, document_id: str) -> None:
        document = (
            admin.table("documents")
            .select("status")
            .eq("id", document_id)
            .maybe_single()
            .execute()
            .data
        )
        if not document or document["status"] == "confirmed":
            return
        chunks = (
            admin.table("chunks")
            .select("status,is_required,approved_version_id")
            .eq("document_id", document_id)
            .execute()
            .data
            or []
        )
        required = [row for row in chunks if row["is_required"]]
        if required and all(
            row["status"] == "approved" and row.get("approved_version_id") for row in required
        ):
            status = "ready_to_confirm"
        elif any(row["status"] != "not_started" for row in required):
            status = "in_progress"
        else:
            status = "draft"
        admin.table("documents").update({"status": status}).eq("id", document_id).execute()

    @staticmethod
    def _log_admin(
        admin,
        user: dict,
        action: str,
        document_id: str | None = None,
        chunk_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        admin.table("activity_logs").insert(
            {
                "user_id": user["id"],
                "action": action,
                "document_id": document_id,
                "chunk_id": chunk_id,
                "metadata": metadata or {},
            }
        ).execute()

    @staticmethod
    def _admin_client():
        try:
            from supabase import create_client
        except ImportError as exc:
            raise IntegrationError("supabase Python 패키지가 설치되지 않았습니다.") from exc
        url = current_app.config.get("SUPABASE_URL", "")
        secret_key = current_app.config.get("SUPABASE_SECRET_KEY", "")
        if not url or not secret_key:
            raise IntegrationError("master1 관리 기능에는 SUPABASE_SECRET_KEY 설정이 필요합니다.")
        return create_client(url, secret_key)

    def _record_diff(self, version_id: str, comparison: dict) -> None:
        self._rpc(
            "record_version_diff",
            {
                "p_version_id": version_id,
                "p_status": comparison["status"],
                "p_summary": comparison["summary"],
                "p_data": comparison["data"],
                "p_error": comparison["error"],
            },
        )

    def _rpc(self, name: str, params: dict) -> Any:
        try:
            return self._client().rpc(name, params).execute().data
        except Exception as exc:
            message = self._error_message(exc)
            if "찾을 수 없" in message:
                raise NotFoundError(message) from exc
            if "권한" in message or "소속 팀" in message or "총괄자" in message:
                from .errors import AuthorizationError

                raise AuthorizationError(message) from exc
            raise ConflictError(message) from exc

    @staticmethod
    def _rpc_row_id(data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return str(data.get("id") or data.get("version_id") or data.get("confirmation_id"))
        if isinstance(data, list) and data:
            return SupabaseWorkspaceService._rpc_row_id(data[0])
        raise IntegrationError("Supabase RPC 결과에서 ID를 확인할 수 없습니다.")

    @staticmethod
    def _error_message(exc: Exception) -> str:
        message = getattr(exc, "message", None) or str(exc) or "Supabase 요청 처리 실패"
        return str(message)[:1000]

    def _chunk_view(self, row: dict) -> dict:
        view = dict(row)
        view["team_name"] = (view.pop("team", None) or {}).get("name", "")
        view["document_title"] = (view.pop("document", None) or {}).get("title", "")
        view["locked_by_name"] = (view.pop("lock_owner", None) or {}).get("name")
        latest_response = (
            self._client()
            .table("chunk_versions")
            .select("id,created_at,uploader:profiles!chunk_versions_uploaded_by_fkey(name)")
            .eq("chunk_id", row["id"])
            .eq("version_no", row["current_version"])
            .maybe_single()
            .execute()
        )
        latest = getattr(latest_response, "data", None) or {}
        view["latest_version_id"] = latest.get("id")
        view["latest_uploaded_by_name"] = (latest.get("uploader") or {}).get("name")
        view["latest_updated_at"] = latest.get("created_at")
        return view

    @staticmethod
    def _version_view(row: dict) -> dict:
        view = dict(row)
        uploader = view.pop("uploader", None) or {}
        view["uploaded_by_name"] = uploader.get("name", "")
        view["uploaded_by_team_name"] = (uploader.get("team") or {}).get("name", "")
        return view

    @staticmethod
    def _profile_view(row: dict) -> dict:
        view = dict(row)
        view["team_name"] = (view.pop("team", None) or {}).get("name", "")
        return view
