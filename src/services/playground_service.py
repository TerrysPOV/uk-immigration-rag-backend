"""
T024: PlaygroundService
Business logic layer for prompt version management and testing

Service Methods:
- list_prompts(include_deleted): List all prompt versions with optional deleted filter
- get_prompt(version_id): Retrieve single prompt version by ID
- create_prompt(name, prompt_text, author_id, notes): Create new prompt version
- soft_delete_prompt(version_id): Mark prompt as deleted (30-day retention)
- restore_prompt(version_id): Restore soft-deleted prompt version
- get_production_prompt(): Retrieve current production prompt
- analyze_with_custom_prompt(document_url, custom_prompt): Run analysis with custom prompt

Soft-Delete Pattern:
- deleted_at = NULL: Active version
- deleted_at = timestamp: Soft-deleted (30-day retention)
- Hard-delete: Automatic cleanup after 30 days (via database trigger)
"""

from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, and_
import uuid

from ..models.prompt_version import (
    PromptVersion,
    PromptVersionCreate,
    PromptVersionInDB,
    PromptVersionResponse,
)
from ..models.production_prompt import (
    ProductionPrompt,
    ProductionPromptInDB,
    ProductionPromptResponse,
)
from ..models.playground_audit_log import (
    PlaygroundAuditLog,
    PlaygroundAuditLogCreate,
    AuditEventType,
    AuditOutcome,
)


class PlaygroundService:
    """
    Service layer for playground prompt management operations.

    Handles prompt version CRUD, soft-delete with retention, and custom prompt analysis.
    """

    def __init__(self, db: Session):
        """
        Initialize PlaygroundService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def list_prompts(
        self,
        include_deleted: bool = False,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[List[PromptVersionResponse], int]:
        """
        List all prompt versions with optional deleted filter.

        Args:
            include_deleted: If True, include soft-deleted prompts
            page: Page number (1-indexed)
            limit: Results per page

        Returns:
            Tuple of (prompt list with author details, total count)

        Logs:
            - INFO: Number of prompts retrieved with filter details
        """
        query = self.db.query(PromptVersion)

        # Filter by deletion status
        if not include_deleted:
            query = query.filter(PromptVersion.deleted_at.is_(None))

        total = query.count()

        # Pagination
        offset = (page - 1) * limit
        prompts = query.order_by(PromptVersion.created_at.desc()).offset(offset).limit(limit).all()

        # Convert to response schema with author details
        results = []
        for prompt in prompts:
            prompt_dict = PromptVersionInDB.from_orm(prompt).dict()
            prompt_dict["author_name"] = prompt.author.name if prompt.author else None
            results.append(PromptVersionResponse(**prompt_dict))

        print(
            f"[PlaygroundService] Retrieved {len(results)} prompts "
            f"(include_deleted={include_deleted}, page={page}, total={total})"
        )
        return results, total

    def get_prompt(self, version_id: uuid.UUID) -> Optional[PromptVersionResponse]:
        """
        Retrieve single prompt version by ID.

        Args:
            version_id: Prompt version UUID

        Returns:
            Prompt version with author details or None if not found

        Logs:
            - INFO: Prompt retrieved
            - ERROR: Prompt not found
        """
        prompt = self.db.query(PromptVersion).filter(PromptVersion.id == version_id).first()

        if not prompt:
            print(f"[PlaygroundService] ERROR: Prompt version with ID '{version_id}' not found")
            return None

        prompt_dict = PromptVersionInDB.from_orm(prompt).dict()
        prompt_dict["author_name"] = prompt.author.name if prompt.author else None
        result = PromptVersionResponse(**prompt_dict)

        print(
            f"[PlaygroundService] Retrieved prompt '{prompt.name}' "
            f"(id={version_id}, status={'deleted' if prompt.deleted_at else 'active'})"
        )
        return result

    def create_prompt(
        self,
        name: str,
        prompt_text: str,
        author_id: uuid.UUID,
        notes: Optional[str] = None,
    ) -> PromptVersionResponse:
        """
        Create new prompt version.

        Args:
            name: Unique version name (1-255 chars)
            prompt_text: System prompt content (1-10,000 chars)
            author_id: User ID who created this version
            notes: Optional description of changes

        Returns:
            Created prompt version with author details

        Raises:
            IntegrityError: If name already exists

        Logs:
            - INFO: Prompt created successfully
            - ERROR: Duplicate name or database error
        """
        try:
            prompt = PromptVersion(
                name=name,
                prompt_text=prompt_text,
                author_id=author_id,
                notes=notes,
            )
            self.db.add(prompt)
            self.db.flush()  # Get ID without committing

            # Create audit log entry
            audit_log = PlaygroundAuditLog(
                event_type=AuditEventType.SAVE_VERSION.value,
                user_id=author_id,
                prompt_version_id=prompt.id,
                outcome=AuditOutcome.SUCCESS.value,
                context={
                    "version_name": name,
                    "prompt_length": len(prompt_text),
                },
            )
            self.db.add(audit_log)
            self.db.commit()

            prompt_dict = PromptVersionInDB.from_orm(prompt).dict()
            prompt_dict["author_name"] = prompt.author.name if prompt.author else None
            result = PromptVersionResponse(**prompt_dict)

            print(
                f"[PlaygroundService] Created prompt version '{name}' "
                f"(id={prompt.id}, length={len(prompt_text)} chars)"
            )
            return result

        except IntegrityError as e:
            self.db.rollback()
            print(f"[PlaygroundService] ERROR: Failed to create prompt '{name}': {str(e)}")
            raise

    def soft_delete_prompt(self, version_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """
        Mark prompt version as deleted (30-day retention).

        Args:
            version_id: Prompt version UUID to delete
            user_id: User ID performing the deletion

        Raises:
            ValueError: If prompt not found or already deleted

        Logs:
            - INFO: Prompt soft-deleted
            - ERROR: Prompt not found or already deleted
        """
        prompt = self.db.query(PromptVersion).filter(PromptVersion.id == version_id).first()

        if not prompt:
            print(f"[PlaygroundService] ERROR: Prompt version '{version_id}' not found")
            raise ValueError(f"Prompt version '{version_id}' not found")

        if prompt.deleted_at:
            print(f"[PlaygroundService] ERROR: Prompt '{prompt.name}' already deleted")
            raise ValueError(f"Prompt '{prompt.name}' is already deleted")

        prompt.deleted_at = datetime.utcnow()

        # Create audit log entry
        audit_log = PlaygroundAuditLog(
            event_type=AuditEventType.DELETE_VERSION.value,
            user_id=user_id,
            prompt_version_id=version_id,
            outcome=AuditOutcome.SUCCESS.value,
            context={
                "version_name": prompt.name,
                "soft_delete": True,
                "retention_days": 30,
            },
        )
        self.db.add(audit_log)
        self.db.commit()

        print(
            f"[PlaygroundService] Soft-deleted prompt '{prompt.name}' "
            f"(id={version_id}, retention=30 days)"
        )

    def restore_prompt(self, version_id: uuid.UUID, user_id: uuid.UUID) -> PromptVersionResponse:
        """
        Restore soft-deleted prompt version.

        Args:
            version_id: Prompt version UUID to restore
            user_id: User ID performing the restoration

        Returns:
            Restored prompt version with author details

        Raises:
            ValueError: If prompt not found or not deleted

        Logs:
            - INFO: Prompt restored
            - ERROR: Prompt not found or not in deleted state
        """
        prompt = self.db.query(PromptVersion).filter(PromptVersion.id == version_id).first()

        if not prompt:
            print(f"[PlaygroundService] ERROR: Prompt version '{version_id}' not found")
            raise ValueError(f"Prompt version '{version_id}' not found")

        if not prompt.deleted_at:
            print(f"[PlaygroundService] ERROR: Prompt '{prompt.name}' is not deleted")
            raise ValueError(f"Prompt '{prompt.name}' is not deleted")

        prompt.deleted_at = None
        self.db.commit()

        prompt_dict = PromptVersionInDB.from_orm(prompt).dict()
        prompt_dict["author_name"] = prompt.author.name if prompt.author else None
        result = PromptVersionResponse(**prompt_dict)

        print(f"[PlaygroundService] Restored prompt '{prompt.name}' (id={version_id})")
        return result

    def get_production_prompt(self) -> ProductionPromptResponse:
        """
        Retrieve current production prompt (singleton row).

        Returns:
            Production prompt with promoter details

        Raises:
            ValueError: If production prompt not initialized

        Logs:
            - INFO: Production prompt retrieved
            - ERROR: Production prompt not found (system misconfiguration)
        """
        production = self.db.query(ProductionPrompt).filter(ProductionPrompt.id == 1).first()

        if not production:
            print("[PlaygroundService] CRITICAL ERROR: Production prompt not initialized (id=1)")
            raise ValueError("Production prompt not initialized - system misconfiguration")

        prompt_dict = ProductionPromptInDB.from_orm(production).dict()
        prompt_dict["promoter_name"] = production.promoter.name if production.promoter else None
        result = ProductionPromptResponse(**prompt_dict)

        print(
            f"[PlaygroundService] Retrieved production prompt "
            f"(promoted_at={production.promoted_at}, version={production.version})"
        )
        return result

    async def analyze_with_custom_prompt(
        self,
        document_url: str,
        custom_prompt: str,
        user_id: uuid.UUID,
    ) -> Dict:
        """
        Run template workflow analysis with custom system prompt.

        This method integrates with the existing Feature 023 Template Workflow API
        to analyze a document using a custom prompt instead of the production prompt.

        Args:
            document_url: GOV.UK document URL to analyze
            custom_prompt: Custom system prompt to use for analysis
            user_id: User ID performing the test

        Returns:
            Dictionary with analysis results:
            {
                "document_url": str,
                "playground_matches": int,
                "production_matches": int,
                "playground_analysis": {...},
                "production_analysis": {...},
                "analysis_duration_ms": int
            }

        Logs:
            - INFO: Analysis started and completed with timing
            - ERROR: Analysis failed with error details
        """
        from ..services.template_service import TemplateService
        import time

        start_time = time.time()

        try:
            # Get production prompt for comparison
            production_prompt = self.get_production_prompt()

            # Run analysis with playground prompt
            # TODO: Integrate with Feature 023 API once available
            # For now, return mock structure
            playground_result = {
                "matches": [],  # Will be populated by Feature 023 integration
                "confidence_scores": [],
            }

            # Run analysis with production prompt for comparison
            production_result = {
                "matches": [],  # Will be populated by Feature 023 integration
                "confidence_scores": [],
            }

            duration_ms = int((time.time() - start_time) * 1000)

            # Create audit log entry
            audit_log = PlaygroundAuditLog(
                event_type=AuditEventType.TEST_ANALYSIS.value,
                user_id=user_id,
                prompt_version_id=None,  # Test analysis doesn't require saved version
                outcome=AuditOutcome.SUCCESS.value,
                context={
                    "document_url": document_url,
                    "production_matches": len(production_result["matches"]),
                    "playground_matches": len(playground_result["matches"]),
                    "analysis_duration_ms": duration_ms,
                },
            )
            self.db.add(audit_log)
            self.db.commit()

            result = {
                "document_url": document_url,
                "playground_matches": len(playground_result["matches"]),
                "production_matches": len(production_result["matches"]),
                "playground_analysis": playground_result,
                "production_analysis": production_result,
                "analysis_duration_ms": duration_ms,
            }

            print(
                f"[PlaygroundService] Analysis completed "
                f"(url={document_url}, playground={len(playground_result['matches'])}, "
                f"production={len(production_result['matches'])}, duration={duration_ms}ms)"
            )
            return result

        except Exception as e:
            # Log failed analysis
            audit_log = PlaygroundAuditLog(
                event_type=AuditEventType.TEST_ANALYSIS.value,
                user_id=user_id,
                prompt_version_id=None,
                outcome=AuditOutcome.FAILURE.value,
                context={
                    "document_url": document_url,
                    "error": str(e),
                },
            )
            self.db.add(audit_log)
            self.db.commit()

            print(f"[PlaygroundService] ERROR: Analysis failed for {document_url}: {str(e)}")
            raise
