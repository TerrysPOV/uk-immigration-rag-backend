"""
T024: PromotionService
Business logic layer for controlled prompt promotion to production

Service Methods:
- preview_promotion(version_id): Preview promotion impact before confirming
- promote_to_production(version_id, user_id, confirmation): Promote with S3 backup and audit

Promotion Workflow:
1. Validate version exists and is not deleted
2. Preview changes (diff between current production and new version)
3. User confirms promotion
4. Backup current production prompt to S3/Spaces
5. Update production_prompt row (optimistic locking prevents conflicts)
6. Create audit log entry
7. Return promotion result with metrics

S3 Backup Path Pattern:
s3://gov-ai-vectorization/prompt-backups/{timestamp}.md
Example: s3://gov-ai-vectorization/prompt-backups/2025-11-02T14:30:00Z.md

Optimistic Locking:
- production_prompt.version auto-increments on update
- Concurrent promotions raise StaleDataError → 409 Conflict
- User must retry with latest version
"""

from typing import Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import StaleDataError
import uuid
import boto3
from botocore.exceptions import ClientError
import os

from ..models.prompt_version import PromptVersion, PromptVersionInDB
from ..models.production_prompt import (
    ProductionPrompt,
    ProductionPromptInDB,
    ProductionPromptUpdate,
    PromotionResult,
)
from ..models.playground_audit_log import (
    PlaygroundAuditLog,
    PlaygroundAuditLogCreate,
    AuditEventType,
    AuditOutcome,
)


class PromotionService:
    """
    Service layer for controlled prompt promotion operations.

    Handles promotion preview, S3 backups, optimistic locking, and audit logging.
    """

    def __init__(self, db: Session):
        """
        Initialize PromotionService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

        # Initialize S3/Spaces client
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=os.getenv("SPACES_ENDPOINT", "https://lon1.digitaloceanspaces.com"),
            aws_access_key_id=os.getenv("SPACES_KEY"),
            aws_secret_access_key=os.getenv("SPACES_SECRET"),
            region_name=os.getenv("SPACES_REGION", "lon1"),
        )
        self.bucket_name = os.getenv("SPACES_BUCKET", "gov-ai-vectorization")
        self.backup_prefix = "prompt-backups"

    def preview_promotion(self, version_id: uuid.UUID) -> Dict:
        """
        Preview promotion impact before confirming.

        Args:
            version_id: Prompt version UUID to promote

        Returns:
            Dictionary with preview details:
            {
                "version_id": UUID,
                "version_name": str,
                "current_production": {
                    "prompt_text": str,
                    "promoted_at": datetime,
                    "promoted_by": UUID,
                    "version": int
                },
                "new_version": {
                    "prompt_text": str,
                    "author_id": UUID,
                    "created_at": datetime
                },
                "changes": {
                    "character_diff": int,  # Positive = longer, negative = shorter
                    "line_diff": int,
                    "estimated_backup_size_kb": float
                }
            }

        Raises:
            ValueError: If version not found, deleted, or production not initialized

        Logs:
            - INFO: Preview generated successfully
            - ERROR: Version not found, deleted, or production missing
        """
        # Get version to promote
        version = self.db.query(PromptVersion).filter(PromptVersion.id == version_id).first()

        if not version:
            print(f"[PromotionService] ERROR: Version '{version_id}' not found")
            raise ValueError(f"Version '{version_id}' not found")

        if version.deleted_at:
            print(f"[PromotionService] ERROR: Version '{version.name}' is deleted")
            raise ValueError(f"Cannot promote deleted version '{version.name}'")

        # Get current production prompt
        production = self.db.query(ProductionPrompt).filter(ProductionPrompt.id == 1).first()

        if not production:
            print("[PromotionService] CRITICAL ERROR: Production prompt not initialized (id=1)")
            raise ValueError("Production prompt not initialized - system misconfiguration")

        # Calculate changes
        current_lines = production.prompt_text.count("\n") + 1
        new_lines = version.prompt_text.count("\n") + 1
        char_diff = len(version.prompt_text) - len(production.prompt_text)
        line_diff = new_lines - current_lines
        backup_size_kb = len(production.prompt_text.encode("utf-8")) / 1024

        result = {
            "version_id": str(version_id),
            "version_name": version.name,
            "current_production": {
                "prompt_text": production.prompt_text,
                "promoted_at": production.promoted_at,
                "promoted_by": str(production.promoted_by),
                "version": production.version,
            },
            "new_version": {
                "prompt_text": version.prompt_text,
                "author_id": str(version.author_id),
                "created_at": version.created_at,
            },
            "changes": {
                "character_diff": char_diff,
                "line_diff": line_diff,
                "estimated_backup_size_kb": round(backup_size_kb, 2),
            },
        }

        print(
            f"[PromotionService] Preview generated for '{version.name}' "
            f"(char_diff={char_diff:+d}, line_diff={line_diff:+d}, backup={backup_size_kb:.2f}KB)"
        )
        return result

    def promote_to_production(
        self,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        confirmation: bool = False,
    ) -> PromotionResult:
        """
        Promote prompt version to production with S3 backup and audit.

        Args:
            version_id: Prompt version UUID to promote
            user_id: User ID performing the promotion
            confirmation: Must be True to proceed (safety check)

        Returns:
            PromotionResult with success status, backup path, and audit log ID

        Raises:
            ValueError: If confirmation=False, version not found/deleted, or production missing
            StaleDataError: If concurrent promotion occurred (optimistic locking conflict)
            ClientError: If S3 backup fails

        Logs:
            - INFO: Promotion started, S3 backup created, promotion completed
            - ERROR: Validation failure, S3 error, optimistic locking conflict
        """
        if not confirmation:
            print("[PromotionService] ERROR: Promotion requires explicit confirmation=True")
            raise ValueError("Promotion requires explicit confirmation")

        # Get version to promote
        version = self.db.query(PromptVersion).filter(PromptVersion.id == version_id).first()

        if not version:
            print(f"[PromotionService] ERROR: Version '{version_id}' not found")
            raise ValueError(f"Version '{version_id}' not found")

        if version.deleted_at:
            print(f"[PromotionService] ERROR: Version '{version.name}' is deleted")
            raise ValueError(f"Cannot promote deleted version '{version.name}'")

        # Get current production prompt (with optimistic locking)
        production = self.db.query(ProductionPrompt).filter(ProductionPrompt.id == 1).first()

        if not production:
            print("[PromotionService] CRITICAL ERROR: Production prompt not initialized (id=1)")
            raise ValueError("Production prompt not initialized - system misconfiguration")

        print(
            f"[PromotionService] Starting promotion: '{version.name}' → production "
            f"(user={user_id}, production_version={production.version})"
        )

        try:
            # Step 1: Backup current production to S3/Spaces
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            backup_key = f"{self.backup_prefix}/{timestamp}.md"
            backup_path = f"s3://{self.bucket_name}/{backup_key}"

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=backup_key,
                Body=production.prompt_text.encode("utf-8"),
                ContentType="text/markdown",
                Metadata={
                    "promoted_at": production.promoted_at.isoformat(),
                    "promoted_by": str(production.promoted_by),
                    "version": str(production.version),
                },
            )

            print(f"[PromotionService] S3 backup created: {backup_path}")

            # Step 2: Update production prompt (optimistic locking)
            production.prompt_text = version.prompt_text
            production.promoted_at = datetime.utcnow()
            production.promoted_by = user_id
            production.previous_backup_path = backup_path
            # production.version auto-increments via optimistic locking

            self.db.flush()  # Trigger optimistic locking check

            # Step 3: Create audit log entry
            audit_log = PlaygroundAuditLog(
                event_type=AuditEventType.PROMOTE.value,
                user_id=user_id,
                prompt_version_id=version_id,
                outcome=AuditOutcome.SUCCESS.value,
                context={
                    "version_id": str(version_id),
                    "version_name": version.name,
                    "backup_path": backup_path,
                    "previous_promoter": str(production.promoted_by),
                    "previous_version": production.version,
                },
            )
            self.db.add(audit_log)
            self.db.commit()

            result = PromotionResult(
                success=True,
                production_prompt=ProductionPromptInDB.from_orm(production),
                backup_path=backup_path,
                audit_log_id=audit_log.id,
                quality_metrics=None,  # TODO: Add quality comparison if needed
            )

            print(
                f"[PromotionService] Promotion completed: '{version.name}' → production "
                f"(new_version={production.version}, backup={backup_path}, audit_log={audit_log.id})"
            )
            return result

        except StaleDataError as e:
            # Optimistic locking conflict - another user promoted concurrently
            self.db.rollback()
            print(
                f"[PromotionService] ERROR: Optimistic locking conflict - "
                f"concurrent promotion detected (version={production.version})"
            )

            # Create failure audit log
            audit_log = PlaygroundAuditLog(
                event_type=AuditEventType.PROMOTE.value,
                user_id=user_id,
                prompt_version_id=version_id,
                outcome=AuditOutcome.FAILURE.value,
                context={
                    "version_id": str(version_id),
                    "version_name": version.name,
                    "error": "Optimistic locking conflict - concurrent promotion",
                },
            )
            self.db.add(audit_log)
            self.db.commit()

            raise

        except ClientError as e:
            # S3 backup failure
            self.db.rollback()
            print(f"[PromotionService] ERROR: S3 backup failed: {str(e)}")

            # Create failure audit log
            audit_log = PlaygroundAuditLog(
                event_type=AuditEventType.PROMOTE.value,
                user_id=user_id,
                prompt_version_id=version_id,
                outcome=AuditOutcome.FAILURE.value,
                context={
                    "version_id": str(version_id),
                    "version_name": version.name,
                    "error": f"S3 backup failed: {str(e)}",
                },
            )
            self.db.add(audit_log)
            self.db.commit()

            raise

        except Exception as e:
            # Unexpected error
            self.db.rollback()
            print(f"[PromotionService] ERROR: Promotion failed: {str(e)}")

            # Create failure audit log
            audit_log = PlaygroundAuditLog(
                event_type=AuditEventType.PROMOTE.value,
                user_id=user_id,
                prompt_version_id=version_id,
                outcome=AuditOutcome.FAILURE.value,
                context={
                    "version_id": str(version_id),
                    "version_name": version.name,
                    "error": str(e),
                },
            )
            self.db.add(audit_log)
            self.db.commit()

            raise

    def get_backup_history(
        self,
        limit: int = 10,
    ) -> list[Dict]:
        """
        List recent production prompt backups from S3.

        Args:
            limit: Maximum number of backups to retrieve

        Returns:
            List of backup metadata dictionaries:
            [
                {
                    "key": str,
                    "path": str,
                    "timestamp": datetime,
                    "size_bytes": int,
                    "metadata": dict
                }
            ]

        Logs:
            - INFO: Number of backups retrieved
            - ERROR: S3 listing failure
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=self.backup_prefix,
                MaxKeys=limit,
            )

            backups = []
            for obj in response.get("Contents", []):
                # Get object metadata
                head = self.s3_client.head_object(Bucket=self.bucket_name, Key=obj["Key"])

                backups.append(
                    {
                        "key": obj["Key"],
                        "path": f"s3://{self.bucket_name}/{obj['Key']}",
                        "timestamp": obj["LastModified"],
                        "size_bytes": obj["Size"],
                        "metadata": head.get("Metadata", {}),
                    }
                )

            print(f"[PromotionService] Retrieved {len(backups)} backup(s) from S3")
            return backups

        except ClientError as e:
            print(f"[PromotionService] ERROR: Failed to list S3 backups: {str(e)}")
            raise
