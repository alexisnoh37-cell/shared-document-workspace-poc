from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .demo_data import (
    CHUNK_SPECS,
    DEPARTMENT_NAME,
    DOCUMENT_TITLE,
    TEAM_SPECS,
    USER_SPECS,
    sample_filename,
    stable_id,
)
from .errors import ConflictError, NotFoundError, ValidationError
from .identity import DELETE_CHUNK_CONFIRMATION_TEXT, DELETE_CONFIRMATION_TEXT
from .permission_service import (
    require_edit,
    require_final_manager,
    require_force_unlock,
    require_master,
    require_review,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MemoryWorkspaceService:
    """Process-local demo backend that mirrors the Supabase workflow contract."""

    def __init__(self, project_root: Path, idle_lock_minutes: int | None = None):
        self.project_root = project_root
        self.idle_lock_minutes = idle_lock_minutes
        self._lock = RLock()
        self.departments: dict[str, dict] = {}
        self.teams: dict[str, dict] = {}
        self.profiles: dict[str, dict] = {}
        self.documents: dict[str, dict] = {}
        self.chunks: dict[str, dict] = {}
        self.versions: dict[str, dict] = {}
        self.version_content: dict[str, bytes] = {}
        self.reviews: dict[str, dict] = {}
        self.confirmation_rows: dict[str, dict] = {}
        self.confirmation_items: list[dict] = []
        self.activity_logs: list[dict] = []
        self._seed()

    def _seed(self) -> None:
        department_id = stable_id("department", DEPARTMENT_NAME)
        self.departments[department_id] = {
            "id": department_id,
            "name": DEPARTMENT_NAME,
            "created_at": _now(),
        }

        team_ids: dict[str, str] = {}
        for key, name in TEAM_SPECS:
            team_id = stable_id("team", key)
            team_ids[key] = team_id
            self.teams[team_id] = {
                "id": team_id,
                "department_id": department_id,
                "name": name,
                "created_at": _now(),
            }

        profile_ids: dict[str, str] = {}
        for email, name, team_key, role, is_final_manager in USER_SPECS:
            profile_id = stable_id("profile", email)
            profile_ids[email] = profile_id
            self.profiles[profile_id] = {
                "id": profile_id,
                "auth_user_id": stable_id("auth-user", email),
                "email": email,
                "name": name,
                "team_id": team_ids[team_key],
                "role": role,
                "is_final_manager": is_final_manager,
                "active": True,
                "created_at": _now(),
                "updated_at": _now(),
            }

        document_id = stable_id("document", DOCUMENT_TITLE)
        manager_id = profile_ids["policy1@example.com"]
        self.documents[document_id] = {
            "id": document_id,
            "series_id": stable_id("series", DOCUMENT_TITLE),
            "revision_no": 1,
            "previous_document_id": None,
            "title": DOCUMENT_TITLE,
            "description": "전산부서 시연을 위한 비실제 샘플 자료입니다.",
            "status": "draft",
            "created_by": manager_id,
            "created_at": _now(),
            "confirmed_by": None,
            "confirmed_at": None,
        }

        samples = self.project_root / "sample_files"
        for order, (code, title, team_key) in enumerate(CHUNK_SPECS, start=1):
            chunk_id = stable_id("chunk", code)
            sample_path = samples / sample_filename(code)
            has_sample = sample_path.exists()
            self.chunks[chunk_id] = {
                "id": chunk_id,
                "document_id": document_id,
                "chunk_code": code,
                "title": title,
                "team_id": team_ids[team_key],
                "status": "not_started",
                "current_version": 1 if has_sample else 0,
                "approved_version_id": None,
                "locked_by": None,
                "locked_at": None,
                "locked_version_no": None,
                "is_required": True,
                "display_order": order,
                "created_at": _now(),
            }
            if has_sample:
                version_id = stable_id("initial-version", code)
                content = sample_path.read_bytes()
                self.versions[version_id] = {
                    "id": version_id,
                    "chunk_id": chunk_id,
                    "version_no": 1,
                    "storage_path": f"demo://{chunk_id}/{version_id}.hwpx",
                    "original_filename": sample_path.name,
                    "file_size": len(content),
                    "sha256": "seed",
                    "uploaded_by": manager_id,
                    "change_reason": "초기 배포본",
                    "diff_status": "not_applicable",
                    "diff_summary": "최초 버전으로 비교 대상이 없습니다.",
                    "diff_data": None,
                    "diff_error": None,
                    "created_at": _now(),
                }
                self.version_content[version_id] = content

    # ---------- Read models ----------

    def list_teams(self) -> list[dict]:
        return sorted((deepcopy(row) for row in self.teams.values()), key=lambda row: row["name"])

    def list_profiles(self) -> list[dict]:
        return sorted((self._profile_view(row) for row in self.profiles.values()), key=lambda row: row["name"])

    def get_profile(self, profile_id: str) -> dict | None:
        row = self.profiles.get(profile_id)
        return self._profile_view(row) if row else None

    def get_profile_by_email(self, email: str) -> dict | None:
        for row in self.profiles.values():
            if row["email"].lower() == email.lower():
                return self._profile_view(row)
        return None

    def list_documents(self) -> list[dict]:
        result = []
        for document in self.documents.values():
            view = deepcopy(document)
            document_chunks = self._document_chunk_rows(document["id"])
            approved = sum(item["status"] == "approved" for item in document_chunks)
            view["chunk_count"] = len(document_chunks)
            view["approved_count"] = approved
            view["progress"] = round((approved / len(document_chunks)) * 100) if document_chunks else 0
            result.append(view)
        return sorted(result, key=lambda row: row["created_at"], reverse=True)

    def get_document(self, document_id: str) -> dict:
        row = self.documents.get(document_id)
        if not row:
            raise NotFoundError("자료를 찾을 수 없습니다.")
        return deepcopy(row)

    def list_chunks(self, document_id: str, team_id: str = "", status: str = "") -> list[dict]:
        self.get_document(document_id)
        self._release_idle_locks(document_id)
        rows = self._document_chunk_rows(document_id)
        if team_id:
            rows = [row for row in rows if row["team_id"] == team_id]
        if status:
            rows = [row for row in rows if row["status"] == status]
        return [self._chunk_view(row) for row in rows]

    def get_chunk(self, chunk_id: str) -> dict:
        row = self.chunks.get(chunk_id)
        if not row:
            raise NotFoundError("문서 조각을 찾을 수 없습니다.")
        self._release_idle_locks(row["document_id"])
        return self._chunk_view(row)

    def list_versions(self, chunk_id: str) -> list[dict]:
        self.get_chunk(chunk_id)
        rows = [row for row in self.versions.values() if row["chunk_id"] == chunk_id]
        return [self._version_view(row) for row in sorted(rows, key=lambda item: item["version_no"], reverse=True)]

    def get_version(self, version_id: str) -> dict:
        row = self.versions.get(version_id)
        if not row:
            raise NotFoundError("버전을 찾을 수 없습니다.")
        return self._version_view(row)

    def list_review_queue(self, user: dict) -> list[dict]:
        if user.get("role") != "reviewer":
            return []
        rows = [
            self._chunk_view(row)
            for row in self.chunks.values()
            if row["team_id"] == user["team_id"] and row["status"] == "submitted"
        ]
        return sorted(rows, key=lambda row: (row["document_title"], row["display_order"]))

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
        required = [chunk for chunk in all_chunks if chunk["is_required"]]
        approved = sum(chunk["status"] == "approved" for chunk in required)
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
        rows = [row for row in self.confirmation_rows.values() if row["document_id"] == document_id]
        result = []
        for row in sorted(rows, key=lambda item: item["confirmed_at"], reverse=True):
            view = deepcopy(row)
            view["confirmed_by_name"] = self.profiles[row["confirmed_by"]]["name"]
            view["items"] = [deepcopy(item) for item in self.confirmation_items if item["confirmation_id"] == row["id"]]
            result.append(view)
        return result

    def list_document_locks(self, document_id: str, current_user: dict) -> list[dict]:
        with self._lock:
            self.get_document(document_id)
            self._release_idle_locks(document_id)
            rows = self._document_chunk_rows(document_id)
            return [
                {
                    "id": chunk["id"],
                    "locked": bool(chunk["locked_by"]),
                    "locked_by_name": (
                        self.profiles[chunk["locked_by"]]["name"] if chunk["locked_by"] else None
                    ),
                    "locked_at": chunk["locked_at"],
                    "is_mine": chunk["locked_by"] == current_user["id"],
                }
                for chunk in rows
            ]

    # ---------- Workflow ----------

    def checkout_chunk(self, user: dict, chunk_id: str) -> dict:
        with self._lock:
            chunk = self._raw_chunk(chunk_id)
            # sweep scoped to this chunk's document; may clear this very chunk's
            # own stale lock, which is the desired effect
            self._release_idle_locks(chunk["document_id"])
            require_edit(user, chunk)
            self._require_open_document(chunk["document_id"])
            if chunk["locked_by"] and chunk["locked_by"] != user["id"]:
                owner = self.profiles[chunk["locked_by"]]["name"]
                raise ConflictError(f"현재 {owner}님이 편집 중입니다.")
            chunk.update(
                {
                    "locked_by": user["id"],
                    "locked_at": _now(),
                    "locked_version_no": chunk["current_version"],
                    "status": "editing",
                }
            )
            self._sync_document_status(chunk["document_id"])
            self._log(user, "checkout", chunk["document_id"], chunk_id)
            return self._chunk_view(chunk)

    def touch_lock(self, chunk_id: str, user: dict) -> bool:
        with self._lock:
            chunk = self.chunks.get(chunk_id)
            if not chunk or chunk["locked_by"] != user["id"]:
                return False
            chunk["locked_at"] = _now()
            return True

    def checkin_chunk(self, user: dict, chunk_id: str, upload, change_reason: str, kordoc) -> dict:
        reason = change_reason.strip()
        if not reason:
            raise ValidationError("변경 사유를 입력하세요.")
        with self._lock:
            chunk = self._raw_chunk(chunk_id)
            require_edit(user, chunk)
            self._require_open_document(chunk["document_id"])
            if chunk["locked_by"] != user["id"]:
                raise ConflictError("체크아웃한 사용자만 수정본을 제출할 수 있습니다.")
            if chunk["locked_version_no"] != chunk["current_version"]:
                raise ConflictError("편집 중 새 버전이 생성되었습니다. 최신 버전으로 다시 시작하세요.")

            previous = self._version_by_number(chunk_id, chunk["current_version"])
            previous_content = self.version_content.get(previous["id"]) if previous else None
            next_version = chunk["current_version"] + 1
            version_id = str(uuid4())
            version = {
                "id": version_id,
                "chunk_id": chunk_id,
                "version_no": next_version,
                "storage_path": f"demo://{chunk_id}/{version_id}{upload.extension}",
                "original_filename": upload.filename,
                "file_size": upload.size,
                "sha256": upload.sha256,
                "uploaded_by": user["id"],
                "change_reason": reason,
                "diff_status": "pending" if previous else "not_applicable",
                "diff_summary": None,
                "diff_data": None,
                "diff_error": None,
                "created_at": _now(),
            }
            self.versions[version_id] = version
            self.version_content[version_id] = upload.content
            chunk.update(
                {
                    "current_version": next_version,
                    "approved_version_id": None,
                    "status": "submitted",
                    "locked_by": None,
                    "locked_at": None,
                    "locked_version_no": None,
                }
            )
            self._sync_document_status(chunk["document_id"])
            self._log(
                user,
                "checkin",
                chunk["document_id"],
                chunk_id,
                {"version_id": version_id, "version_no": next_version, "change_reason": reason},
            )

        comparison = kordoc.compare_bytes(
            previous_content,
            upload.content,
            Path(previous["original_filename"]).suffix if previous else upload.extension,
            upload.extension,
        )
        with self._lock:
            version.update(
                {
                    "diff_status": comparison["status"],
                    "diff_summary": comparison["summary"],
                    "diff_data": comparison["data"],
                    "diff_error": comparison["error"],
                }
            )
            return self._version_view(version)

    def retry_diff(self, user: dict, version_id: str, kordoc) -> dict:
        with self._lock:
            version = self.versions.get(version_id)
            if not version:
                raise NotFoundError("버전을 찾을 수 없습니다.")
            chunk = self._raw_chunk(version["chunk_id"])
            require_edit(user, chunk)
            previous = self._version_by_number(chunk["id"], version["version_no"] - 1)
            old_content = self.version_content.get(previous["id"]) if previous else None
            new_content = self.version_content[version_id]
        comparison = kordoc.compare_bytes(
            old_content,
            new_content,
            Path(previous["original_filename"]).suffix if previous else ".hwpx",
            Path(version["original_filename"]).suffix,
        )
        with self._lock:
            version.update(
                {
                    "diff_status": comparison["status"],
                    "diff_summary": comparison["summary"],
                    "diff_data": comparison["data"],
                    "diff_error": comparison["error"],
                }
            )
            self._log(user, "retry_diff", chunk["document_id"], chunk["id"], {"version_id": version_id})
            return self._version_view(version)

    def review_chunk(self, user: dict, chunk_id: str, action: str, comment: str) -> dict:
        if action not in {"approve", "reject"}:
            raise ValidationError("올바른 검토 작업이 아닙니다.")
        if action == "reject" and not comment.strip():
            raise ValidationError("반려 사유를 입력하세요.")
        with self._lock:
            chunk = self._raw_chunk(chunk_id)
            require_review(user, chunk)
            self._require_open_document(chunk["document_id"])
            if chunk["status"] != "submitted":
                raise ConflictError("제출완료 상태의 조각만 검토할 수 있습니다.")
            version = self._version_by_number(chunk_id, chunk["current_version"])
            if not version:
                raise ConflictError("검토할 제출 버전이 없습니다.")
            review_id = str(uuid4())
            self.reviews[review_id] = {
                "id": review_id,
                "chunk_id": chunk_id,
                "version_id": version["id"],
                "reviewer_id": user["id"],
                "action": action,
                "comment": comment.strip() or None,
                "created_at": _now(),
            }
            chunk["status"] = "approved" if action == "approve" else "rejected"
            chunk["approved_version_id"] = version["id"] if action == "approve" else None
            self._sync_document_status(chunk["document_id"])
            self._log(
                user,
                action,
                chunk["document_id"],
                chunk_id,
                {"version_id": version["id"], "comment": comment.strip()},
            )
            return self._chunk_view(chunk)

    def force_unlock(self, user: dict, chunk_id: str, comment: str = "") -> dict:
        with self._lock:
            chunk = self._raw_chunk(chunk_id)
            require_force_unlock(user, chunk)
            self._require_open_document(chunk["document_id"])
            if not chunk["locked_by"]:
                raise ConflictError("현재 잠금 상태가 아닙니다.")
            previous_owner = chunk["locked_by"]
            chunk.update(
                {
                    "status": "not_started" if chunk["current_version"] == 0 else "rejected",
                    "locked_by": None,
                    "locked_at": None,
                    "locked_version_no": None,
                }
            )
            self._sync_document_status(chunk["document_id"])
            self._log(
                user,
                "force_unlock",
                chunk["document_id"],
                chunk_id,
                {"previous_locked_by": previous_owner, "comment": comment.strip()},
            )
            return self._chunk_view(chunk)

    def confirm_document(self, user: dict, document_id: str) -> dict:
        require_final_manager(user)
        with self._lock:
            document = self.documents.get(document_id)
            if not document:
                raise NotFoundError("자료를 찾을 수 없습니다.")
            if document["status"] == "confirmed":
                raise ConflictError("이미 최종확정된 자료입니다.")
            required = [row for row in self._document_chunk_rows(document_id) if row["is_required"]]
            if not required or any(
                row["status"] != "approved" or not row["approved_version_id"] for row in required
            ):
                raise ConflictError("모든 필수 조각이 승인되어야 최종확정할 수 있습니다.")
            confirmation_id = str(uuid4())
            snapshot = []
            for chunk in required:
                version = self.versions[chunk["approved_version_id"]]
                item = {
                    "id": str(uuid4()),
                    "confirmation_id": confirmation_id,
                    "chunk_id": chunk["id"],
                    "version_id": version["id"],
                    "version_no": version["version_no"],
                }
                self.confirmation_items.append(item)
                snapshot.append({key: item[key] for key in ("chunk_id", "version_id", "version_no")})
            confirmed_at = _now()
            confirmation = {
                "id": confirmation_id,
                "document_id": document_id,
                "confirmed_by": user["id"],
                "confirmed_at": confirmed_at,
                "snapshot_data": snapshot,
            }
            self.confirmation_rows[confirmation_id] = confirmation
            document.update(
                {
                    "status": "confirmed",
                    "confirmed_by": user["id"],
                    "confirmed_at": confirmed_at,
                }
            )
            self._log(user, "confirm_document", document_id, None, {"confirmation_id": confirmation_id})
            return deepcopy(confirmation)

    def download_version(self, version_id: str) -> tuple[bytes, str]:
        version = self.versions.get(version_id)
        content = self.version_content.get(version_id)
        if not version or content is None:
            raise NotFoundError("다운로드할 파일을 찾을 수 없습니다.")
        return content, version["original_filename"]

    # ---------- Final-manager administration ----------

    def set_profile_active(self, user: dict, profile_id: str, active: bool) -> dict:
        require_final_manager(user)
        with self._lock:
            profile = self.profiles.get(profile_id)
            if not profile:
                raise NotFoundError("사용자를 찾을 수 없습니다.")
            if profile_id == user["id"] and not active:
                raise ValidationError("현재 로그인한 총괄자 계정은 비활성화할 수 없습니다.")
            profile["active"] = active
            profile["updated_at"] = _now()
            self._log(user, "set_profile_active", None, None, {"profile_id": profile_id, "active": active})
            return self._profile_view(profile)

    def create_document(self, user: dict, title: str, description: str) -> dict:
        require_final_manager(user)
        if not title.strip():
            raise ValidationError("자료명을 입력하세요.")
        with self._lock:
            document_id = str(uuid4())
            row = {
                "id": document_id,
                "series_id": str(uuid4()),
                "revision_no": 1,
                "previous_document_id": None,
                "title": title.strip(),
                "description": description.strip() or None,
                "status": "draft",
                "created_by": user["id"],
                "created_at": _now(),
                "confirmed_by": None,
                "confirmed_at": None,
            }
            self.documents[document_id] = row
            self._log(user, "create_document", document_id, None)
            return deepcopy(row)

    def create_chunk(self, user: dict, document_id: str, code: str, title: str, team_id: str) -> dict:
        require_final_manager(user)
        if not code.strip() or not title.strip() or team_id not in self.teams:
            raise ValidationError("조각코드, 조각명, 담당팀을 올바르게 입력하세요.")
        with self._lock:
            self._require_open_document(document_id)
            if any(
                row["document_id"] == document_id and row["chunk_code"].lower() == code.strip().lower()
                for row in self.chunks.values()
            ):
                raise ConflictError("같은 자료에 이미 존재하는 조각코드입니다.")
            order = max(
                (row["display_order"] for row in self.chunks.values() if row["document_id"] == document_id),
                default=0,
            ) + 1
            chunk_id = str(uuid4())
            row = {
                "id": chunk_id,
                "document_id": document_id,
                "chunk_code": code.strip(),
                "title": title.strip(),
                "team_id": team_id,
                "status": "not_started",
                "current_version": 0,
                "approved_version_id": None,
                "locked_by": None,
                "locked_at": None,
                "locked_version_no": None,
                "is_required": True,
                "display_order": order,
                "created_at": _now(),
            }
            self.chunks[chunk_id] = row
            self._sync_document_status(document_id)
            self._log(user, "create_chunk", document_id, chunk_id)
            return self._chunk_view(row)

    def update_document_title(self, user: dict, document_id: str, title: str) -> dict:
        require_master(user)
        new_title = title.strip()
        if not new_title:
            raise ValidationError("자료명을 입력하세요.")
        with self._lock:
            document = self.documents.get(document_id)
            if not document:
                raise NotFoundError("자료를 찾을 수 없습니다.")
            if document["status"] == "confirmed":
                raise ValidationError("최종확정된 자료의 이름은 변경할 수 없습니다.")
            old_title = document["title"]
            document["title"] = new_title
            self._log(
                user,
                "update_document_title",
                document_id,
                None,
                {"old_title": old_title, "new_title": new_title},
            )
            return deepcopy(document)

    def update_chunk_title(self, user: dict, chunk_id: str, title: str) -> dict:
        require_master(user)
        new_title = title.strip()
        if not new_title:
            raise ValidationError("조각명을 입력하세요.")
        with self._lock:
            chunk = self._raw_chunk(chunk_id)
            self._require_open_document(chunk["document_id"])
            old_title = chunk["title"]
            chunk["title"] = new_title
            self._log(
                user,
                "update_chunk_title",
                chunk["document_id"],
                chunk_id,
                {"old_title": old_title, "new_title": new_title},
            )
            return self._chunk_view(chunk)

    def delete_chunk(self, user: dict, chunk_id: str, confirmation_text: str) -> dict:
        require_master(user)
        if confirmation_text.strip() != DELETE_CHUNK_CONFIRMATION_TEXT:
            raise ValidationError(
                f"조각을 영구 삭제하려면 '{DELETE_CHUNK_CONFIRMATION_TEXT}'를 정확히 입력하세요."
            )
        with self._lock:
            chunk = self._raw_chunk(chunk_id)
            self._require_open_document(chunk["document_id"])
            if chunk.get("locked_by"):
                raise ConflictError("편집 중인 조각은 잠금을 해제한 후 삭제하세요.")
            document_id = chunk["document_id"]
            version_ids = {
                row["id"] for row in self.versions.values() if row["chunk_id"] == chunk_id
            }
            self._log(
                user,
                "delete_chunk",
                document_id,
                chunk_id,
                {
                    "deleted_chunk_id": chunk_id,
                    "chunk_code": chunk["chunk_code"],
                    "title": chunk["title"],
                    "version_file_count": len(version_ids),
                },
            )
            self.reviews = {
                key: row for key, row in self.reviews.items() if row["chunk_id"] != chunk_id
            }
            self.confirmation_items = [
                row for row in self.confirmation_items if row["chunk_id"] != chunk_id
            ]
            for version_id in version_ids:
                self.versions.pop(version_id, None)
                self.version_content.pop(version_id, None)
            self.chunks.pop(chunk_id, None)
            self._sync_document_status(document_id)
            return {
                "id": chunk_id,
                "document_id": document_id,
                "title": chunk["title"],
                "storage_cleanup_failed": False,
            }

    def delete_document(self, user: dict, document_id: str, confirmation_text: str) -> dict:
        require_master(user)
        if confirmation_text.strip() != DELETE_CONFIRMATION_TEXT:
            raise ValidationError(f"영구 삭제하려면 '{DELETE_CONFIRMATION_TEXT}'를 정확히 입력하세요.")
        with self._lock:
            document = self.documents.get(document_id)
            if not document:
                raise NotFoundError("삭제할 자료를 찾을 수 없습니다.")
            if document["status"] == "confirmed":
                raise ValidationError("최종확정된 자료는 영구 삭제할 수 없습니다.")
            if any(row.get("previous_document_id") == document_id for row in self.documents.values()):
                raise ValidationError("후속 개정 자료가 존재하는 자료는 영구 삭제할 수 없습니다.")

            chunk_ids = {
                row["id"] for row in self.chunks.values() if row["document_id"] == document_id
            }
            version_ids = {
                row["id"] for row in self.versions.values() if row["chunk_id"] in chunk_ids
            }
            self._log(
                user,
                "delete_document",
                document_id,
                None,
                {
                    "deleted_document_id": document_id,
                    "title": document["title"],
                    "chunk_count": len(chunk_ids),
                    "version_file_count": len(version_ids),
                },
            )

            self.reviews = {
                key: row
                for key, row in self.reviews.items()
                if row["chunk_id"] not in chunk_ids
            }
            for version_id in version_ids:
                self.versions.pop(version_id, None)
                self.version_content.pop(version_id, None)
            for chunk_id in chunk_ids:
                self.chunks.pop(chunk_id, None)
            self.documents.pop(document_id, None)
            return {
                "id": document_id,
                "title": document["title"],
                "storage_cleanup_failed": False,
            }

    # ---------- Internal helpers ----------

    def _release_idle_locks(self, document_id: str | None = None) -> None:
        """Release locks idle past the threshold.

        NOTE (PoC tradeoff): this is a mutating write invoked from read paths
        (list_chunks / get_chunk / list_document_locks). A plain page read can
        therefore flip a stale-locked chunk to rejected/not_started and demote the
        document status on a timer. Pass ``document_id`` to bound the sweep to the
        document actually being read; ``None`` keeps the legacy all-chunks scan.
        """
        if self.idle_lock_minutes is None:
            return
        cutoff = datetime.now(UTC) - timedelta(minutes=self.idle_lock_minutes)
        with self._lock:
            if document_id is None:
                candidates = list(self.chunks.values())
            else:
                candidates = self._document_chunk_rows(document_id)
            for chunk in candidates:
                locked_by = chunk.get("locked_by")
                locked_at = chunk.get("locked_at")
                if not locked_by or not locked_at:
                    continue
                try:
                    when = datetime.fromisoformat(locked_at)
                except ValueError:
                    continue
                if when >= cutoff:
                    continue
                owner = self.profiles.get(locked_by)
                chunk.update(
                    {
                        "status": "not_started" if chunk["current_version"] == 0 else "rejected",
                        "locked_by": None,
                        "locked_at": None,
                        "locked_version_no": None,
                    }
                )
                self._sync_document_status(chunk["document_id"])
                if owner:
                    self._log(
                        owner,
                        "lock_idle_released",
                        chunk["document_id"],
                        chunk["id"],
                        {"idle_minutes": self.idle_lock_minutes},
                    )

    def _raw_chunk(self, chunk_id: str) -> dict:
        row = self.chunks.get(chunk_id)
        if not row:
            raise NotFoundError("문서 조각을 찾을 수 없습니다.")
        return row

    def _document_chunk_rows(self, document_id: str) -> list[dict]:
        return sorted(
            (row for row in self.chunks.values() if row["document_id"] == document_id),
            key=lambda row: row["display_order"],
        )

    def _version_by_number(self, chunk_id: str, version_no: int) -> dict | None:
        return next(
            (
                row
                for row in self.versions.values()
                if row["chunk_id"] == chunk_id and row["version_no"] == version_no
            ),
            None,
        )

    def _profile_view(self, row: dict) -> dict:
        view = deepcopy(row)
        view["team_name"] = self.teams[row["team_id"]]["name"]
        return view

    def _chunk_view(self, row: dict) -> dict:
        view = deepcopy(row)
        view["team_name"] = self.teams[row["team_id"]]["name"]
        view["document_title"] = self.documents[row["document_id"]]["title"]
        view["locked_by_name"] = self.profiles[row["locked_by"]]["name"] if row["locked_by"] else None
        latest = self._version_by_number(row["id"], row["current_version"])
        view["latest_version_id"] = latest["id"] if latest else None
        view["latest_uploaded_by_name"] = self.profiles[latest["uploaded_by"]]["name"] if latest else None
        view["latest_updated_at"] = latest["created_at"] if latest else None
        return view

    def _version_view(self, row: dict) -> dict:
        view = deepcopy(row)
        profile = self.profiles[row["uploaded_by"]]
        view["uploaded_by_name"] = profile["name"]
        view["uploaded_by_team_name"] = self.teams[profile["team_id"]]["name"]
        return view

    def _require_open_document(self, document_id: str) -> dict:
        document = self.documents.get(document_id)
        if not document:
            raise NotFoundError("자료를 찾을 수 없습니다.")
        if document["status"] == "confirmed":
            raise ConflictError("최종확정된 자료는 수정할 수 없습니다.")
        return document

    def _sync_document_status(self, document_id: str) -> None:
        document = self.documents[document_id]
        if document["status"] == "confirmed":
            return
        required = [row for row in self._document_chunk_rows(document_id) if row["is_required"]]
        if required and all(row["status"] == "approved" and row["approved_version_id"] for row in required):
            document["status"] = "ready_to_confirm"
        elif any(row["status"] != "not_started" for row in required):
            document["status"] = "in_progress"
        else:
            document["status"] = "draft"

    def _log(
        self,
        user: dict,
        action: str,
        document_id: str | None,
        chunk_id: str | None,
        metadata: dict | None = None,
    ) -> None:
        self.activity_logs.append(
            {
                "id": str(uuid4()),
                "user_id": user["id"],
                "action": action,
                "document_id": document_id,
                "chunk_id": chunk_id,
                "metadata": metadata or {},
                "created_at": _now(),
            }
        )
