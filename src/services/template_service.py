"""
T037: TemplateService
Business logic layer for document template management

Service Methods:
- create_template(data, created_by): Create new template (version 1)
- update_template(id, data, updated_by): Update template (auto-creates version)
- get_template_versions(id): Retrieve all versions for template
- generate_document(template_id, placeholder_values): Fill template and return document
- preview_template(template_id, placeholder_values): Real-time preview (<200ms)
- get_template_by_id(template_id): Retrieve single template
- list_templates(filters): List templates with pagination

Template Versioning (FR-TG-005):
- Each update creates new TemplateVersion entry
- Version number auto-increments
- Old versions preserved for audit trail
"""

from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
import uuid
import re

from ..models.template import (
    Template,
    TemplateCreate,
    TemplateUpdate,
    TemplateInDB,
    TemplateWithVersions,
)
from ..models.template_version import TemplateVersion, TemplateVersionCreate, TemplateVersionInDB


class TemplateService:
    """
    Service layer for template management operations.

    Handles template CRUD, versioning, document generation, and preview.
    Automatically creates version history on updates.
    """

    def __init__(self, db: Session):
        """
        Initialize TemplateService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def get_template_by_id(self, template_id: str) -> Optional[TemplateInDB]:
        """
        Retrieve single template by ID.

        Args:
            template_id: Template UUID

        Returns:
            Template object or None if not found

        Logs:
            - INFO: Template retrieved
            - ERROR: Template not found
        """
        template = self.db.query(Template).filter(Template.id == uuid.UUID(template_id)).first()

        if not template:
            print(f"[TemplateService] ERROR: Template with ID '{template_id}' not found")
            return None

        print(f"[TemplateService] Retrieved template '{template.template_name}' (id={template_id})")
        return TemplateInDB.from_orm(template)

    def list_templates(
        self,
        permission_level: Optional[str] = None,
        created_by: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[List[TemplateInDB], int]:
        """
        List templates with pagination and filters.

        Args:
            permission_level: Filter by permission level (optional)
            created_by: Filter by creator user ID (optional)
            search: Search template name or description (optional)
            page: Page number (1-indexed)
            limit: Results per page

        Returns:
            Tuple of (template list, total count)

        Logs:
            - INFO: Number of templates retrieved with filter details
        """
        query = self.db.query(Template)

        # Apply filters
        if permission_level:
            query = query.filter(Template.permission_level == permission_level)
        if created_by:
            query = query.filter(Template.created_by == uuid.UUID(created_by))
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Template.template_name.ilike(search_pattern),
                    Template.description.ilike(search_pattern),
                )
            )

        # Get total count
        total_count = query.count()

        # Apply pagination
        offset = (page - 1) * limit
        templates = query.offset(offset).limit(limit).all()

        template_list = [TemplateInDB.from_orm(t) for t in templates]

        print(
            f"[TemplateService] Retrieved {len(template_list)} templates (page={page}, limit={limit})"
        )
        return template_list, total_count

    def create_template(self, template_data: TemplateCreate, created_by: str) -> TemplateInDB:
        """
        Create new template with version 1.

        Args:
            template_data: Template creation data
            created_by: User ID creating the template

        Returns:
            Created template

        Raises:
            ValueError: If template creation fails

        Logs:
            - INFO: Template created with version 1
            - ERROR: Template creation failed
        """
        new_template = Template(
            id=uuid.uuid4(),
            template_name=template_data.template_name,
            description=template_data.description,
            content_structure=template_data.content_structure,
            placeholders=template_data.placeholders,
            permission_level=template_data.permission_level,
            created_by=uuid.UUID(created_by),
        )

        try:
            self.db.add(new_template)
            self.db.commit()
            self.db.refresh(new_template)

            # Create version 1
            version_1 = TemplateVersion(
                id=uuid.uuid4(),
                template_id=new_template.id,
                version_number=1,
                content_snapshot=template_data.content_structure,
                change_description="Initial version",
                created_by=uuid.UUID(created_by),
            )
            self.db.add(version_1)
            self.db.commit()

            print(
                f"[TemplateService] Created template '{new_template.template_name}' with version 1"
            )
            return TemplateInDB.from_orm(new_template)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to create template: {str(e)}"
            print(f"[TemplateService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def update_template(
        self,
        template_id: str,
        template_data: TemplateUpdate,
        updated_by: str,
        change_description: Optional[str] = None,
    ) -> TemplateInDB:
        """
        Update template and auto-create new version.

        Args:
            template_id: Template UUID to update
            template_data: Update data (partial)
            updated_by: User ID performing the update
            change_description: Optional description of changes

        Returns:
            Updated template

        Raises:
            ValueError: If template not found or update invalid

        Logs:
            - INFO: Template updated with new version
            - ERROR: Template update failed
        """
        template = self.db.query(Template).filter(Template.id == uuid.UUID(template_id)).first()

        if not template:
            error_msg = f"Template with ID '{template_id}' not found"
            print(f"[TemplateService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Track changes
        changes_made = False

        if template_data.template_name is not None:
            template.template_name = template_data.template_name
            changes_made = True

        if template_data.description is not None:
            template.description = template_data.description
            changes_made = True

        if template_data.content_structure is not None:
            template.content_structure = template_data.content_structure
            changes_made = True

        if template_data.placeholders is not None:
            template.placeholders = template_data.placeholders
            changes_made = True

        if template_data.permission_level is not None:
            template.permission_level = template_data.permission_level
            changes_made = True

        if not changes_made:
            print(f"[TemplateService] No changes detected for template '{template.template_name}'")
            return TemplateInDB.from_orm(template)

        try:
            template.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(template)

            # Get current version number
            latest_version = (
                self.db.query(TemplateVersion)
                .filter(TemplateVersion.template_id == template.id)
                .order_by(TemplateVersion.version_number.desc())
                .first()
            )

            new_version_number = latest_version.version_number + 1 if latest_version else 1

            # Create new version
            new_version = TemplateVersion(
                id=uuid.uuid4(),
                template_id=template.id,
                version_number=new_version_number,
                content_snapshot=template.content_structure,
                change_description=change_description or "Template updated",
                created_by=uuid.UUID(updated_by),
            )
            self.db.add(new_version)
            self.db.commit()

            print(
                f"[TemplateService] Updated template '{template.template_name}' - created version {new_version_number}"
            )
            return TemplateInDB.from_orm(template)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to update template: {str(e)}"
            print(f"[TemplateService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def get_template_versions(self, template_id: str) -> List[TemplateVersionInDB]:
        """
        Retrieve all versions for template.

        Args:
            template_id: Template UUID

        Returns:
            List of template versions (ordered by version_number DESC)

        Logs:
            - INFO: Number of versions retrieved
            - ERROR: Template not found
        """
        template = self.db.query(Template).filter(Template.id == uuid.UUID(template_id)).first()

        if not template:
            error_msg = f"Template with ID '{template_id}' not found"
            print(f"[TemplateService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        versions = (
            self.db.query(TemplateVersion)
            .filter(TemplateVersion.template_id == template.id)
            .order_by(TemplateVersion.version_number.desc())
            .all()
        )

        version_list = [TemplateVersionInDB.from_orm(v) for v in versions]

        print(
            f"[TemplateService] Retrieved {len(version_list)} versions for template '{template.template_name}'"
        )
        return version_list

    def generate_document(self, template_id: str, placeholder_values: Dict[str, str]) -> Dict:
        """
        Fill template with placeholder values and return generated document.

        Args:
            template_id: Template UUID
            placeholder_values: Dict mapping placeholder names to values

        Returns:
            Dict with generated_content and missing_placeholders

        Raises:
            ValueError: If template not found

        Logs:
            - INFO: Document generated successfully
            - WARNING: Missing placeholders
        """
        template = self.db.query(Template).filter(Template.id == uuid.UUID(template_id)).first()

        if not template:
            error_msg = f"Template with ID '{template_id}' not found"
            print(f"[TemplateService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Check for missing placeholders
        required_placeholders = set(template.placeholders)
        provided_placeholders = set(placeholder_values.keys())
        missing_placeholders = list(required_placeholders - provided_placeholders)

        if missing_placeholders:
            print(f"[TemplateService] WARNING: Missing placeholders: {missing_placeholders}")

        # Generate document by replacing placeholders
        generated_content = self._fill_placeholders(template.content_structure, placeholder_values)

        print(f"[TemplateService] Generated document from template '{template.template_name}'")

        return {
            "generated_content": generated_content,
            "missing_placeholders": missing_placeholders,
            "template_name": template.template_name,
        }

    def preview_template(self, template_id: str, placeholder_values: Dict[str, str]) -> Dict:
        """
        Real-time preview of template with placeholder values (<200ms).

        Args:
            template_id: Template UUID
            placeholder_values: Dict mapping placeholder names to values

        Returns:
            Dict with preview_html and render_time_ms

        Raises:
            ValueError: If template not found

        Logs:
            - INFO: Preview generated with render time
        """
        start_time = datetime.utcnow()

        template = self.db.query(Template).filter(Template.id == uuid.UUID(template_id)).first()

        if not template:
            error_msg = f"Template with ID '{template_id}' not found"
            print(f"[TemplateService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Generate preview (same as generate_document)
        preview_content = self._fill_placeholders(template.content_structure, placeholder_values)

        # Calculate render time
        end_time = datetime.utcnow()
        render_time_ms = (end_time - start_time).total_seconds() * 1000

        print(
            f"[TemplateService] Preview generated for template '{template.template_name}' in {render_time_ms:.2f}ms"
        )

        return {
            "preview_html": self._render_html(preview_content),
            "render_time_ms": round(render_time_ms, 2),
            "template_name": template.template_name,
        }

    def _fill_placeholders(
        self, content_structure: Dict, placeholder_values: Dict[str, str]
    ) -> Dict:
        """Fill placeholders in content structure recursively."""
        if isinstance(content_structure, dict):
            filled = {}
            for key, value in content_structure.items():
                filled[key] = self._fill_placeholders(value, placeholder_values)
            return filled
        elif isinstance(content_structure, list):
            return [self._fill_placeholders(item, placeholder_values) for item in content_structure]
        elif isinstance(content_structure, str):
            # Replace {{placeholder}} with values
            result = content_structure
            for placeholder, value in placeholder_values.items():
                pattern = f"{{{{{placeholder}}}}}"
                result = result.replace(pattern, str(value))
            return result
        else:
            return content_structure

    def _render_html(self, content_structure: Dict) -> str:
        """Render content structure as HTML."""
        html_parts = []

        # Header
        if "header" in content_structure:
            html_parts.append(f"<header>{content_structure['header']}</header>")

        # Body
        if "body" in content_structure:
            html_parts.append(f"<main>{content_structure['body']}</main>")

        # Footer
        if "footer" in content_structure:
            html_parts.append(f"<footer>{content_structure['footer']}</footer>")

        return "\n".join(html_parts)
