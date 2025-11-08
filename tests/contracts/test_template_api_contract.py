"""
Contract tests for Template Generation API.

Tests all 8 endpoints from contracts/template-api.yaml:
1. GET /api/v1/templates
2. POST /api/v1/templates
3. GET /api/v1/templates/{id}
4. PUT /api/v1/templates/{id}
5. DELETE /api/v1/templates/{id}
6. GET /api/v1/templates/{id}/versions
7. GET /api/v1/templates/{id}/versions/{version_number}
8. POST /api/v1/templates/{id}/generate
9. POST /api/v1/templates/{id}/preview

These tests MUST FAIL before implementation (TDD).
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4


class TestListTemplates:
    """Test GET /api/v1/templates - List templates with pagination."""

    def test_list_templates_success(self, client, auth_headers):
        """Test successful template listing."""
        response = client.get("/api/v1/templates", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "templates" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data

        # Template schema validation
        if len(data["templates"]) > 0:
            template = data["templates"][0]
            assert "id" in template
            assert "template_name" in template
            assert "content_structure" in template
            assert "placeholders" in template
            assert "permission_level" in template
            assert "created_by" in template
            assert "created_at" in template
            assert "current_version" in template

            assert template["permission_level"] in ["public", "shared", "private"]
            assert template["current_version"] >= 1

    def test_list_templates_filter_by_permission(self, client, auth_headers):
        """Test filtering by permission_level."""
        response = client.get(
            "/api/v1/templates", params={"permission_level": "public"}, headers=auth_headers
        )

        assert response.status_code == 200
        templates = response.json()["templates"]

        for template in templates:
            assert template["permission_level"] == "public"

    def test_list_templates_pagination(self, client, auth_headers):
        """Test pagination parameters."""
        response = client.get(
            "/api/v1/templates", params={"page": 2, "limit": 10}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["limit"] == 10


class TestCreateTemplate:
    """Test POST /api/v1/templates - Create new template."""

    def test_create_template_success(self, client, auth_headers):
        """Test successful template creation."""
        template_data = {
            "template_name": "Visa Application Letter",
            "description": "Standard visa application letter template",
            "content_structure": {
                "blocks": [
                    {"type": "heading", "level": 1, "content": "{{title}}"},
                    {"type": "paragraph", "content": "Dear {{applicant_name}},"},
                    {
                        "type": "list",
                        "items": [
                            "Visa Type: {{visa_type}}",
                            "Application Date: {{application_date}}",
                        ],
                    },
                ]
            },
            "placeholders": [
                {
                    "key": "title",
                    "label": "Document Title",
                    "required": True,
                    "validation_pattern": None,
                },
                {
                    "key": "applicant_name",
                    "label": "Applicant Full Name",
                    "required": True,
                    "validation_pattern": "^[A-Za-z ]{2,100}$",
                },
                {
                    "key": "visa_type",
                    "label": "Visa Type",
                    "required": True,
                    "validation_pattern": None,
                },
                {
                    "key": "application_date",
                    "label": "Application Date",
                    "required": True,
                    "validation_pattern": None,
                },
            ],
            "permission_level": "shared",
        }

        response = client.post("/api/v1/templates", json=template_data, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()

        assert data["template_name"] == "Visa Application Letter"
        assert data["permission_level"] == "shared"
        assert data["current_version"] == 1
        assert len(data["placeholders"]) == 4

    def test_create_template_validates_content_structure(self, client, auth_headers):
        """Test content_structure JSONB validation."""
        invalid_template = {
            "template_name": "Invalid Template",
            "content_structure": "not a JSON object",  # Invalid
            "placeholders": [],
            "permission_level": "private",
        }

        response = client.post("/api/v1/templates", json=invalid_template, headers=auth_headers)

        assert response.status_code in [400, 422]

    def test_create_template_missing_required_fields(self, client, auth_headers):
        """Test 400 when required fields missing."""
        incomplete_template = {
            "template_name": "Incomplete Template"
            # Missing content_structure, placeholders, permission_level
        }

        response = client.post("/api/v1/templates", json=incomplete_template, headers=auth_headers)

        assert response.status_code in [400, 422]


class TestGetTemplate:
    """Test GET /api/v1/templates/{id} - Get single template."""

    def test_get_template_success(self, client, auth_headers, sample_template_id):
        """Test retrieving single template."""
        response = client.get(f"/api/v1/templates/{sample_template_id}", headers=auth_headers)

        assert response.status_code == 200
        template = response.json()

        assert template["id"] == str(sample_template_id)
        assert "content_structure" in template
        assert "placeholders" in template

    def test_get_template_not_found(self, client, auth_headers):
        """Test 404 for non-existent template."""
        fake_id = uuid4()
        response = client.get(f"/api/v1/templates/{fake_id}", headers=auth_headers)

        assert response.status_code == 404


class TestUpdateTemplate:
    """Test PUT /api/v1/templates/{id} - Update template (creates version)."""

    def test_update_template_success(self, client, auth_headers, sample_template_id):
        """Test successful template update."""
        update_data = {
            "template_name": "Updated Template Name",
            "description": "Updated description",
            "change_description": "Changed template name and description",
        }

        response = client.put(
            f"/api/v1/templates/{sample_template_id}", json=update_data, headers=auth_headers
        )

        assert response.status_code == 200
        template = response.json()

        assert template["template_name"] == "Updated Template Name"
        assert template["current_version"] > 1  # Version incremented

    def test_update_template_creates_version(self, client, auth_headers, sample_template_id):
        """Test that update creates TemplateVersion record."""
        update_data = {
            "content_structure": {"blocks": [{"type": "heading", "content": "New Content"}]},
            "change_description": "Updated content structure",
        }

        # Update template
        update_response = client.put(
            f"/api/v1/templates/{sample_template_id}", json=update_data, headers=auth_headers
        )
        assert update_response.status_code == 200

        # Check versions endpoint
        versions_response = client.get(
            f"/api/v1/templates/{sample_template_id}/versions", headers=auth_headers
        )

        assert versions_response.status_code == 200
        versions = versions_response.json()["versions"]
        assert len(versions) > 1  # Multiple versions exist


class TestDeleteTemplate:
    """Test DELETE /api/v1/templates/{id} - Soft delete template."""

    def test_delete_template_success(self, client, auth_headers, sample_template_id):
        """Test successful soft delete."""
        response = client.delete(f"/api/v1/templates/{sample_template_id}", headers=auth_headers)

        assert response.status_code == 204

        # Verify template not returned in list
        list_response = client.get("/api/v1/templates", headers=auth_headers)
        templates = list_response.json()["templates"]
        assert not any(t["id"] == str(sample_template_id) for t in templates)

    def test_delete_template_forbidden_not_owner(
        self, client, viewer_auth_headers, sample_template_id
    ):
        """Test 403 when non-owner tries to delete."""
        response = client.delete(
            f"/api/v1/templates/{sample_template_id}", headers=viewer_auth_headers
        )

        assert response.status_code == 403


class TestTemplateVersions:
    """Test GET /api/v1/templates/{id}/versions - Get version history."""

    def test_get_template_versions_success(self, client, auth_headers, sample_template_id):
        """Test retrieving version history."""
        response = client.get(
            f"/api/v1/templates/{sample_template_id}/versions", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()

        assert "template_id" in data
        assert "versions" in data
        assert isinstance(data["versions"], list)

        # TemplateVersion schema validation
        if len(data["versions"]) > 0:
            version = data["versions"][0]
            assert "id" in version
            assert "template_id" in version
            assert "version_number" in version
            assert "content_snapshot" in version
            assert "created_at" in version
            assert "created_by" in version

    def test_get_specific_version(self, client, auth_headers, sample_template_id):
        """Test GET /api/v1/templates/{id}/versions/{version_number}."""
        response = client.get(
            f"/api/v1/templates/{sample_template_id}/versions/1", headers=auth_headers
        )

        assert response.status_code == 200
        version = response.json()

        assert version["version_number"] == 1
        assert version["template_id"] == str(sample_template_id)
        assert "content_snapshot" in version

    def test_get_version_not_found(self, client, auth_headers, sample_template_id):
        """Test 404 for non-existent version."""
        response = client.get(
            f"/api/v1/templates/{sample_template_id}/versions/999", headers=auth_headers
        )

        assert response.status_code == 404


class TestGenerateDocument:
    """Test POST /api/v1/templates/{id}/generate - Generate document from template."""

    def test_generate_document_success(self, client, auth_headers, sample_template_id):
        """Test successful document generation."""
        generate_request = {
            "placeholder_values": {
                "title": "UK Visa Application",
                "applicant_name": "John Smith",
                "visa_type": "Tier 2 (General)",
                "application_date": "2025-10-14",
            },
            "output_format": "markdown",
            "validate_placeholders": True,
        }

        response = client.post(
            f"/api/v1/templates/{sample_template_id}/generate",
            json=generate_request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "generated_content" in data
        assert "format" in data
        assert "placeholders_used" in data
        assert "missing_placeholders" in data

        assert data["format"] == "markdown"
        assert len(data["missing_placeholders"]) == 0

    def test_generate_document_missing_required_placeholders(
        self, client, auth_headers, sample_template_id
    ):
        """Test 400 when required placeholders missing (FR-TG-008)."""
        generate_request = {
            "placeholder_values": {
                "title": "UK Visa Application"
                # Missing required: applicant_name, visa_type, application_date
            },
            "output_format": "markdown",
            "validate_placeholders": True,
        }

        response = client.post(
            f"/api/v1/templates/{sample_template_id}/generate",
            json=generate_request,
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = response.json()

        assert "missing_placeholders" in data
        assert len(data["missing_placeholders"]) > 0

    def test_generate_document_html_format(self, client, auth_headers, sample_template_id):
        """Test HTML output format."""
        generate_request = {
            "placeholder_values": {
                "title": "Test",
                "applicant_name": "Test User",
                "visa_type": "Tier 1",
                "application_date": "2025-10-14",
            },
            "output_format": "html",
        }

        response = client.post(
            f"/api/v1/templates/{sample_template_id}/generate",
            json=generate_request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "html"


class TestPreviewTemplate:
    """Test POST /api/v1/templates/{id}/preview - Real-time preview (<200ms)."""

    def test_preview_template_success(self, client, auth_headers, sample_template_id):
        """Test real-time template preview."""
        preview_request = {
            "placeholder_values": {
                "title": "Preview Test",
                "applicant_name": "Jane Doe",
                # Partial values for preview
            }
        }

        response = client.post(
            f"/api/v1/templates/{sample_template_id}/preview",
            json=preview_request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "preview_html" in data
        assert "render_time_ms" in data

        # FR-TG-007: Preview must be <200ms
        assert data["render_time_ms"] < 200

    def test_preview_template_empty_placeholders(self, client, auth_headers, sample_template_id):
        """Test preview with empty placeholder values."""
        preview_request = {"placeholder_values": {}}

        response = client.post(
            f"/api/v1/templates/{sample_template_id}/preview",
            json=preview_request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        # Should still render with empty placeholders


# Fixtures
@pytest.fixture
def client():
    """FastAPI test client."""
    # TODO: Import actual app after implementation
    # from src.main import app
    # return TestClient(app)
    pytest.skip("Endpoints not implemented yet - TDD test must fail first")


@pytest.fixture
def auth_headers():
    """Editor authentication headers."""
    return {"Authorization": "Bearer fake-editor-jwt-token"}


@pytest.fixture
def viewer_auth_headers():
    """Viewer role authentication headers."""
    return {"Authorization": "Bearer fake-viewer-jwt-token"}


@pytest.fixture
def sample_template_id():
    """Sample template UUID for testing."""
    return uuid4()
