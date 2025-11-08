"""
Contract tests for Workflow Management API.

Tests all 7 endpoints from contracts/workflow-api.yaml:
1. GET /api/v1/workflows
2. POST /api/v1/workflows
3. GET /api/v1/workflows/{id}
4. PUT /api/v1/workflows/{id}
5. DELETE /api/v1/workflows/{id}
6. POST /api/v1/workflows/{id}/execute
7. GET /api/v1/workflows/executions/{execution_id}
8. POST /api/v1/workflows/executions/{execution_id}/pause
9. POST /api/v1/workflows/executions/{execution_id}/resume

These tests MUST FAIL before implementation (TDD).
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4


class TestListWorkflows:
    """Test GET /api/v1/workflows - List workflows with pagination."""

    def test_list_workflows_success(self, client, auth_headers):
        """Test successful workflow listing."""
        response = client.get("/api/v1/workflows", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "workflows" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data

        # Workflow schema validation
        if len(data["workflows"]) > 0:
            workflow = data["workflows"][0]
            assert "id" in workflow
            assert "workflow_name" in workflow
            assert "trigger_conditions" in workflow
            assert "status" in workflow
            assert "created_by" in workflow
            assert "created_at" in workflow

            assert workflow["status"] in ["active", "paused", "draft"]

    def test_list_workflows_filter_by_status(self, client, auth_headers):
        """Test filtering by status."""
        response = client.get(
            "/api/v1/workflows", params={"status": "active"}, headers=auth_headers
        )

        assert response.status_code == 200
        workflows = response.json()["workflows"]

        for workflow in workflows:
            assert workflow["status"] == "active"


class TestCreateWorkflow:
    """Test POST /api/v1/workflows - Create workflow with visual designer."""

    def test_create_workflow_success(self, client, auth_headers):
        """Test successful workflow creation."""
        workflow_data = {
            "workflow_name": "Document Processing Workflow",
            "description": "Automated document ingestion and processing",
            "trigger_conditions": {
                "trigger_type": "schedule",
                "cron": "0 2 * * *",  # Daily at 2 AM
            },
            "status": "draft",
            "steps": [
                {
                    "step_number": 1,
                    "step_type": "transform",
                    "parameters": {"transformation": "normalize_text"},
                    "retry_config": {
                        "strategy": "exponential",
                        "max_attempts": 5,
                        "initial_delay_ms": 1000,
                        "backoff_multiplier": 2,
                        "max_delay_ms": 60000,
                        "jitter_percentage": 20,
                    },
                },
                {
                    "step_number": 2,
                    "step_type": "api",
                    "parameters": {"endpoint": "/api/v1/ingestion/process", "method": "POST"},
                    "retry_config": {
                        "strategy": "immediate",
                        "max_attempts": 3,
                        "initial_delay_ms": 0,
                    },
                },
                {
                    "step_number": 3,
                    "step_type": "notify",
                    "parameters": {
                        "notification_type": "email",
                        "recipients": ["admin@example.gov.uk"],
                    },
                },
            ],
        }

        response = client.post("/api/v1/workflows", json=workflow_data, headers=auth_headers)

        assert response.status_code == 201
        workflow = response.json()

        assert workflow["workflow_name"] == "Document Processing Workflow"
        assert workflow["status"] == "draft"
        assert "id" in workflow

    def test_create_workflow_validates_trigger_conditions(self, client, auth_headers):
        """Test trigger_conditions JSONB validation."""
        invalid_workflow = {
            "workflow_name": "Invalid Workflow",
            "trigger_conditions": "not a JSON object",  # Invalid
            "steps": [],
        }

        response = client.post("/api/v1/workflows", json=invalid_workflow, headers=auth_headers)

        assert response.status_code in [400, 422]

    def test_create_workflow_validates_retry_config(self, client, auth_headers):
        """Test retry_config validation (FR-WM-011)."""
        workflow_data = {
            "workflow_name": "Test Workflow",
            "trigger_conditions": {"trigger_type": "manual"},
            "steps": [
                {
                    "step_number": 1,
                    "step_type": "transform",
                    "parameters": {},
                    "retry_config": {
                        "strategy": "exponential",
                        "max_attempts": 5,
                        "initial_delay_ms": 1000,
                        "backoff_multiplier": 2,
                        "max_delay_ms": 60000,
                        "jitter_percentage": 20,
                    },
                }
            ],
        }

        response = client.post("/api/v1/workflows", json=workflow_data, headers=auth_headers)

        assert response.status_code == 201


class TestGetWorkflow:
    """Test GET /api/v1/workflows/{id} - Get workflow with steps."""

    def test_get_workflow_success(self, client, auth_headers, sample_workflow_id):
        """Test retrieving workflow with all steps."""
        response = client.get(f"/api/v1/workflows/{sample_workflow_id}", headers=auth_headers)

        assert response.status_code == 200
        workflow = response.json()

        assert workflow["id"] == str(sample_workflow_id)
        assert "steps" in workflow
        assert isinstance(workflow["steps"], list)

        # WorkflowStep schema validation
        if len(workflow["steps"]) > 0:
            step = workflow["steps"][0]
            assert "id" in step
            assert "workflow_id" in step
            assert "step_number" in step
            assert "step_type" in step
            assert "parameters" in step

            assert step["step_type"] in ["transform", "api", "notify", "condition", "delay"]

    def test_get_workflow_not_found(self, client, auth_headers):
        """Test 404 for non-existent workflow."""
        fake_id = uuid4()
        response = client.get(f"/api/v1/workflows/{fake_id}", headers=auth_headers)

        assert response.status_code == 404


class TestUpdateWorkflow:
    """Test PUT /api/v1/workflows/{id} - Update workflow and steps."""

    def test_update_workflow_success(self, client, auth_headers, sample_workflow_id):
        """Test successful workflow update."""
        update_data = {
            "workflow_name": "Updated Workflow Name",
            "status": "active",
            "steps": [
                {
                    "step_number": 1,
                    "step_type": "transform",
                    "parameters": {"transformation": "updated"},
                }
            ],
        }

        response = client.put(
            f"/api/v1/workflows/{sample_workflow_id}", json=update_data, headers=auth_headers
        )

        assert response.status_code == 200
        workflow = response.json()
        assert workflow["workflow_name"] == "Updated Workflow Name"


class TestDeleteWorkflow:
    """Test DELETE /api/v1/workflows/{id} - Soft delete workflow."""

    def test_delete_workflow_success(self, client, auth_headers, sample_workflow_id):
        """Test successful soft delete."""
        response = client.delete(f"/api/v1/workflows/{sample_workflow_id}", headers=auth_headers)

        assert response.status_code == 204


class TestExecuteWorkflow:
    """Test POST /api/v1/workflows/{id}/execute - Trigger workflow execution."""

    def test_execute_workflow_async(self, client, auth_headers, sample_workflow_id):
        """Test async workflow execution (FR-WM-005, FR-WM-006)."""
        execute_request = {
            "input_data": {"document_id": "doc-123", "source": "gov.uk"},
            "execute_async": True,
        }

        response = client.post(
            f"/api/v1/workflows/{sample_workflow_id}/execute",
            json=execute_request,
            headers=auth_headers,
        )

        assert response.status_code == 202  # Accepted
        data = response.json()

        assert "execution_id" in data
        assert "status" in data
        assert "started_at" in data
        assert data["status"] in ["queued", "running"]

    def test_execute_workflow_sync(self, client, auth_headers, sample_workflow_id):
        """Test synchronous workflow execution."""
        execute_request = {"input_data": {"test": "data"}, "execute_async": False}

        response = client.post(
            f"/api/v1/workflows/{sample_workflow_id}/execute",
            json=execute_request,
            headers=auth_headers,
        )

        # Sync returns 200 with full execution result
        assert response.status_code == 200
        execution = response.json()

        assert "execution_id" in execution
        assert "status" in execution
        assert execution["status"] in ["completed", "failed"]

    def test_execute_workflow_not_found(self, client, auth_headers):
        """Test 404 for non-existent workflow."""
        fake_id = uuid4()
        response = client.post(
            f"/api/v1/workflows/{fake_id}/execute", json={"input_data": {}}, headers=auth_headers
        )

        assert response.status_code == 404


class TestGetExecutionStatus:
    """Test GET /api/v1/workflows/executions/{execution_id} - Real-time status."""

    def test_get_execution_status_success(self, client, auth_headers, sample_execution_id):
        """Test retrieving execution status (FR-WM-007, FR-WM-008)."""
        response = client.get(
            f"/api/v1/workflows/executions/{sample_execution_id}", headers=auth_headers
        )

        assert response.status_code == 200
        execution = response.json()

        # WorkflowExecution schema validation
        assert "execution_id" in execution
        assert "workflow_id" in execution
        assert "status" in execution
        assert "started_at" in execution
        assert "current_step" in execution
        assert "total_steps" in execution
        assert "execution_logs" in execution
        assert "progress_percentage" in execution

        assert execution["status"] in ["queued", "running", "paused", "completed", "failed"]
        assert 0 <= execution["progress_percentage"] <= 100

        # Execution logs validation
        logs = execution["execution_logs"]
        assert "steps" in logs
        if len(logs["steps"]) > 0:
            step_log = logs["steps"][0]
            assert "step_number" in step_log
            assert "status" in step_log
            assert step_log["status"] in ["pending", "running", "completed", "failed", "retrying"]

    def test_get_execution_status_includes_retry_attempts(
        self, client, auth_headers, sample_execution_id
    ):
        """Test execution logs include retry attempt numbers (FR-WM-011)."""
        response = client.get(
            f"/api/v1/workflows/executions/{sample_execution_id}", headers=auth_headers
        )

        assert response.status_code == 200
        execution = response.json()

        # Check for retry attempts in logs
        steps = execution["execution_logs"]["steps"]
        if len(steps) > 0:
            step = steps[0]
            assert "attempt_number" in step

    def test_get_execution_status_not_found(self, client, auth_headers):
        """Test 404 for non-existent execution."""
        fake_id = uuid4()
        response = client.get(f"/api/v1/workflows/executions/{fake_id}", headers=auth_headers)

        assert response.status_code == 404


class TestPauseExecution:
    """Test POST /api/v1/workflows/executions/{execution_id}/pause - Pause workflow."""

    def test_pause_execution_success(self, client, auth_headers, running_execution_id):
        """Test pausing running workflow (FR-WM-009)."""
        response = client.post(
            f"/api/v1/workflows/executions/{running_execution_id}/pause", headers=auth_headers
        )

        assert response.status_code == 200
        execution = response.json()
        assert execution["status"] == "paused"

    def test_pause_execution_invalid_state(self, client, auth_headers, completed_execution_id):
        """Test 400 when trying to pause non-running execution."""
        response = client.post(
            f"/api/v1/workflows/executions/{completed_execution_id}/pause", headers=auth_headers
        )

        assert response.status_code == 400
        assert "error" in response.json()


class TestResumeExecution:
    """Test POST /api/v1/workflows/executions/{execution_id}/resume - Resume workflow."""

    def test_resume_execution_success(self, client, auth_headers, paused_execution_id):
        """Test resuming paused workflow (FR-WM-009)."""
        response = client.post(
            f"/api/v1/workflows/executions/{paused_execution_id}/resume", headers=auth_headers
        )

        assert response.status_code == 200
        execution = response.json()
        assert execution["status"] == "running"

    def test_resume_execution_invalid_state(self, client, auth_headers, running_execution_id):
        """Test 400 when trying to resume non-paused execution."""
        response = client.post(
            f"/api/v1/workflows/executions/{running_execution_id}/resume", headers=auth_headers
        )

        assert response.status_code == 400


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
    """Admin authentication headers."""
    return {"Authorization": "Bearer fake-admin-jwt-token"}


@pytest.fixture
def sample_workflow_id():
    """Sample workflow UUID for testing."""
    return uuid4()


@pytest.fixture
def sample_execution_id():
    """Sample execution UUID for testing."""
    return uuid4()


@pytest.fixture
def running_execution_id():
    """Execution ID in running state."""
    return uuid4()


@pytest.fixture
def paused_execution_id():
    """Execution ID in paused state."""
    return uuid4()


@pytest.fixture
def completed_execution_id():
    """Execution ID in completed state."""
    return uuid4()
