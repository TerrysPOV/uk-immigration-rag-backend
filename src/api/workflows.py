"""
Feature 012: Workflow Management API
T069-T077: Workflow Management API endpoints

Endpoints:
- GET /api/v1/workflows - List workflows with filtering and pagination
- POST /api/v1/workflows - Create workflow with steps
- GET /api/v1/workflows/{id} - Get workflow with all steps
- PUT /api/v1/workflows/{id} - Update workflow and steps
- DELETE /api/v1/workflows/{id} - Soft delete workflow
- POST /api/v1/workflows/{id}/execute - Trigger async execution
- GET /api/v1/workflows/executions/{execution_id} - Get execution status
- POST /api/v1/workflows/executions/{execution_id}/pause - Pause execution
- POST /api/v1/workflows/executions/{execution_id}/resume - Resume execution

Authentication: Requires Admin role
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from ..database import get_db
from ..models.workflow import Workflow, WorkflowCreate, WorkflowUpdate, WorkflowInDB
from ..models.workflow_step import WorkflowStep, WorkflowStepInDB
from ..models.workflow_execution import WorkflowExecution, WorkflowExecutionInDB
from ..services.workflow_service import WorkflowService
from ..middleware.rbac import get_current_user_with_role


router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


# ============================================================================
# Request/Response Models
# ============================================================================


class WorkflowListResponse(BaseModel):
    """Response schema for workflow list."""

    workflows: List[WorkflowInDB]
    pagination: dict


class WorkflowWithSteps(WorkflowInDB):
    """Workflow with all steps included."""

    steps: List[WorkflowStepInDB]


class ExecutionTriggerRequest(BaseModel):
    """Request schema for workflow execution."""

    input_data: dict = Field(..., description="Input data for workflow execution")


class ExecutionTriggerResponse(BaseModel):
    """Response schema for workflow execution trigger."""

    execution_id: str
    workflow_id: str
    status: str
    message: str


class ExecutionStatusResponse(BaseModel):
    """Response schema for execution status."""

    execution_id: str
    workflow_id: str
    status: str
    current_step: Optional[int]
    progress_percentage: float
    started_at: datetime
    completed_at: Optional[datetime]
    execution_logs: dict
    error_message: Optional[str]


# ============================================================================
# T069: GET /api/v1/workflows
# ============================================================================


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    status: Optional[str] = Query(None, description="Filter by status (active/paused/draft)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    List workflows with filtering and pagination (T069).

    Requires: Admin role

    Filters:
    - status: Filter by workflow status (active/paused/draft)

    Returns:
        WorkflowListResponse with workflows array and pagination metadata
    """
    try:
        offset = (page - 1) * limit

        query = db.query(Workflow).filter(Workflow.deleted_at.is_(None))

        # Apply status filter
        if status:
            query = query.filter(Workflow.status == status)

        total_count = query.count()
        workflows = query.offset(offset).limit(limit).all()

        return WorkflowListResponse(
            workflows=[WorkflowInDB.from_orm(w) for w in workflows],
            pagination={
                "page": page,
                "limit": limit,
                "total_count": total_count,
                "total_pages": (total_count + limit - 1) // limit,
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list workflows: {str(e)}",
        )


# ============================================================================
# T070: POST /api/v1/workflows
# ============================================================================


@router.post("", response_model=WorkflowWithSteps, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workflow_data: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Create workflow with steps (T070).

    Requires: Admin role

    Validates trigger_conditions JSONB and retry_config for each step.
    Creates workflow and all associated steps.

    Args:
        workflow_data: Workflow creation data with steps

    Returns:
        Created workflow with all steps
    """
    try:
        workflow_service = WorkflowService(db)

        # Create workflow
        new_workflow = workflow_service.create_workflow(
            workflow_data=workflow_data, created_by=current_user.id
        )

        # Get workflow with steps
        workflow = db.query(Workflow).filter(Workflow.id == new_workflow.id).first()
        steps = db.query(WorkflowStep).filter(WorkflowStep.workflow_id == workflow.id).all()

        return WorkflowWithSteps(
            **WorkflowInDB.from_orm(workflow).dict(),
            steps=[WorkflowStepInDB.from_orm(s) for s in steps],
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create workflow: {str(e)}",
        )


# ============================================================================
# T071: GET /api/v1/workflows/{id}
# ============================================================================


@router.get("/{workflow_id}", response_model=WorkflowWithSteps)
async def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Get workflow with all steps (T071).

    Requires: Admin role

    Returns workflow with all WorkflowStep objects.

    Args:
        workflow_id: Workflow UUID

    Returns:
        Workflow object with steps array
    """
    try:
        workflow = (
            db.query(Workflow)
            .filter(Workflow.id == workflow_id, Workflow.deleted_at.is_(None))
            .first()
        )

        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {workflow_id} not found"
            )

        # Get workflow steps
        steps = (
            db.query(WorkflowStep)
            .filter(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.step_number)
            .all()
        )

        return WorkflowWithSteps(
            **WorkflowInDB.from_orm(workflow).dict(),
            steps=[WorkflowStepInDB.from_orm(s) for s in steps],
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve workflow: {str(e)}",
        )


# ============================================================================
# T072: PUT /api/v1/workflows/{id}
# ============================================================================


@router.put("/{workflow_id}", response_model=WorkflowWithSteps)
async def update_workflow(
    workflow_id: str,
    workflow_data: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Update workflow and steps (T072).

    Requires: Admin role

    Updates workflow metadata and steps.
    Can add/remove/modify steps.

    Args:
        workflow_id: Workflow UUID
        workflow_data: Workflow update data

    Returns:
        Updated workflow with steps
    """
    try:
        workflow_service = WorkflowService(db)

        # Update workflow
        updated_workflow = workflow_service.update_workflow(
            workflow_id=workflow_id, workflow_data=workflow_data
        )

        # Get workflow with steps
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        steps = (
            db.query(WorkflowStep)
            .filter(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.step_number)
            .all()
        )

        return WorkflowWithSteps(
            **WorkflowInDB.from_orm(workflow).dict(),
            steps=[WorkflowStepInDB.from_orm(s) for s in steps],
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update workflow: {str(e)}",
        )


# ============================================================================
# T073: DELETE /api/v1/workflows/{id}
# ============================================================================


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Soft delete workflow (T073).

    Requires: Admin role

    Sets deleted_at timestamp instead of hard delete.
    Preserves workflow and execution history for audit purposes.

    Args:
        workflow_id: Workflow UUID
    """
    try:
        workflow_service = WorkflowService(db)

        # Soft delete workflow
        workflow_service.delete_workflow(workflow_id)

        return None

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete workflow: {str(e)}",
        )


# ============================================================================
# T074: POST /api/v1/workflows/{id}/execute
# ============================================================================


@router.post(
    "/{workflow_id}/execute",
    response_model=ExecutionTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_workflow(
    workflow_id: str,
    execution_request: ExecutionTriggerRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Trigger async workflow execution (T074).

    Requires: Admin role

    Creates WorkflowExecution record and returns execution_id immediately.
    Actual execution happens asynchronously (202 Accepted).

    Args:
        workflow_id: Workflow UUID
        execution_request: Input data for execution

    Returns:
        ExecutionTriggerResponse with execution_id (202 Accepted)
    """
    try:
        workflow_service = WorkflowService(db)

        # Execute workflow (async)
        execution_id = workflow_service.execute_workflow(
            workflow_id=workflow_id, input_data=execution_request.input_data
        )

        return ExecutionTriggerResponse(
            execution_id=execution_id,
            workflow_id=workflow_id,
            status="pending",
            message="Workflow execution started. Use execution_id to check status.",
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute workflow: {str(e)}",
        )


# ============================================================================
# T075: GET /api/v1/workflows/executions/{execution_id}
# ============================================================================


@router.get("/executions/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Get real-time execution status (T075).

    Requires: Admin role

    Returns:
    - Execution status (pending/running/completed/failed/paused)
    - Current step number
    - Progress percentage
    - Execution logs with step-by-step details

    Args:
        execution_id: Execution UUID

    Returns:
        ExecutionStatusResponse with real-time status
    """
    try:
        workflow_service = WorkflowService(db)

        # Get execution status
        status_data = workflow_service.get_execution_status(execution_id)

        return ExecutionStatusResponse(**status_data)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve execution status: {str(e)}",
        )


# ============================================================================
# T076: POST /api/v1/workflows/executions/{execution_id}/pause
# ============================================================================


@router.post("/executions/{execution_id}/pause", status_code=status.HTTP_204_NO_CONTENT)
async def pause_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Pause running workflow execution (T076).

    Requires: Admin role

    Sets execution status to 'paused'.
    Workflow can be resumed later from current step.

    Args:
        execution_id: Execution UUID
    """
    try:
        workflow_service = WorkflowService(db)

        # Pause execution
        workflow_service.pause_execution(execution_id)

        return None

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause execution: {str(e)}",
        )


# ============================================================================
# T077: POST /api/v1/workflows/executions/{execution_id}/resume
# ============================================================================


@router.post("/executions/{execution_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user_with_role("admin")),
):
    """
    Resume paused workflow execution (T077).

    Requires: Admin role

    Sets execution status to 'running'.
    Continues execution from current_step.

    Args:
        execution_id: Execution UUID
    """
    try:
        workflow_service = WorkflowService(db)

        # Resume execution
        workflow_service.resume_execution(execution_id)

        return None

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume execution: {str(e)}",
        )
