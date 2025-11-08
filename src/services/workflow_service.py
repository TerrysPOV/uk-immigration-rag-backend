"""
T038: WorkflowService
Business logic layer for workflow automation and execution

Service Methods:
- create_workflow(data, created_by): Create workflow with steps
- execute_workflow(workflow_id, input_data): Async workflow execution
- pause_execution(execution_id): Pause running workflow
- resume_execution(execution_id): Resume paused workflow
- get_execution_status(execution_id): Get real-time execution status
- retry_step(execution_id, step_number, strategy): Retry failed step with strategy
- get_workflow_by_id(workflow_id): Retrieve single workflow
- list_workflows(filters): List workflows with pagination

Retry Strategies (FR-WM-011):
- immediate: 3 attempts, 0s delay
- exponential: 5 attempts, 2x backoff with jitter
- manual: No retry, pause workflow
- circuit_breaker: Open after 5 failures, 60s cooldown
"""

from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
import uuid
import asyncio

from ..models.workflow import Workflow, WorkflowCreate, WorkflowUpdate, WorkflowInDB
from ..models.workflow_step import WorkflowStep, WorkflowStepInDB
from ..models.workflow_execution import (
    WorkflowExecution,
    WorkflowExecutionInDB,
    WorkflowExecutionStatus,
)


class WorkflowService:
    """
    Service layer for workflow automation operations.

    Handles workflow CRUD, execution, pause/resume, and step retry.
    Supports async execution with real-time status tracking.
    """

    def __init__(self, db: Session):
        """
        Initialize WorkflowService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def get_workflow_by_id(self, workflow_id: str) -> Optional[WorkflowInDB]:
        """
        Retrieve single workflow by ID with steps.

        Args:
            workflow_id: Workflow UUID

        Returns:
            Workflow object or None if not found

        Logs:
            - INFO: Workflow retrieved with step count
            - ERROR: Workflow not found
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == uuid.UUID(workflow_id)).first()

        if not workflow:
            print(f"[WorkflowService] ERROR: Workflow with ID '{workflow_id}' not found")
            return None

        steps = (
            self.db.query(WorkflowStep)
            .filter(WorkflowStep.workflow_id == workflow.id)
            .order_by(WorkflowStep.step_number)
            .all()
        )

        print(
            f"[WorkflowService] Retrieved workflow '{workflow.workflow_name}' with {len(steps)} steps"
        )
        return WorkflowInDB.from_orm(workflow)

    def list_workflows(
        self,
        status: Optional[str] = None,
        created_by: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[List[WorkflowInDB], int]:
        """
        List workflows with pagination and filters.

        Args:
            status: Filter by status (active/paused/draft) (optional)
            created_by: Filter by creator user ID (optional)
            search: Search workflow name or description (optional)
            page: Page number (1-indexed)
            limit: Results per page

        Returns:
            Tuple of (workflow list, total count)

        Logs:
            - INFO: Number of workflows retrieved with filter details
        """
        query = self.db.query(Workflow)

        # Apply filters
        if status:
            query = query.filter(Workflow.status == status)
        if created_by:
            query = query.filter(Workflow.created_by == uuid.UUID(created_by))
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Workflow.workflow_name.ilike(search_pattern),
                    Workflow.description.ilike(search_pattern),
                )
            )

        # Get total count
        total_count = query.count()

        # Apply pagination
        offset = (page - 1) * limit
        workflows = query.offset(offset).limit(limit).all()

        workflow_list = [WorkflowInDB.from_orm(w) for w in workflows]

        print(
            f"[WorkflowService] Retrieved {len(workflow_list)} workflows (page={page}, limit={limit})"
        )
        return workflow_list, total_count

    def create_workflow(self, workflow_data: WorkflowCreate, created_by: str) -> WorkflowInDB:
        """
        Create workflow with steps.

        Args:
            workflow_data: Workflow creation data with steps
            created_by: User ID creating the workflow

        Returns:
            Created workflow

        Raises:
            ValueError: If workflow creation fails

        Logs:
            - INFO: Workflow created with step count
            - ERROR: Workflow creation failed
        """
        new_workflow = Workflow(
            id=uuid.uuid4(),
            workflow_name=workflow_data.workflow_name,
            description=workflow_data.description,
            trigger_conditions=workflow_data.trigger_conditions,
            status=workflow_data.status,
            created_by=uuid.UUID(created_by),
        )

        try:
            self.db.add(new_workflow)
            self.db.commit()
            self.db.refresh(new_workflow)

            # Create workflow steps
            # (Steps would be passed in workflow_data, but schema doesn't include them yet)
            # TODO: Add steps support to WorkflowCreate schema

            print(f"[WorkflowService] Created workflow '{new_workflow.workflow_name}'")
            return WorkflowInDB.from_orm(new_workflow)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to create workflow: {str(e)}"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def execute_workflow(self, workflow_id: str, input_data: Dict) -> str:
        """
        Trigger workflow execution (async).

        Args:
            workflow_id: Workflow UUID to execute
            input_data: Input data for workflow

        Returns:
            Execution ID (UUID)

        Raises:
            ValueError: If workflow not found or execution fails

        Logs:
            - INFO: Workflow execution started
            - ERROR: Workflow execution failed

        Note:
            Returns execution_id immediately (202 Accepted).
            Actual execution happens asynchronously.
        """
        workflow = self.db.query(Workflow).filter(Workflow.id == uuid.UUID(workflow_id)).first()

        if not workflow:
            error_msg = f"Workflow with ID '{workflow_id}' not found"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Create execution record
        execution = WorkflowExecution(
            execution_id=uuid.uuid4(),
            workflow_id=workflow.id,
            status="running",
            current_step=0,
            progress_percentage=0.0,
            execution_logs={"input_data": input_data, "steps": []},
        )

        try:
            self.db.add(execution)
            self.db.commit()
            self.db.refresh(execution)

            print(
                f"[WorkflowService] Started execution of workflow '{workflow.workflow_name}' (execution_id={execution.execution_id})"
            )

            # TODO: Trigger async execution (use Celery or background task)
            # For now, just create the execution record

            return str(execution.execution_id)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to start workflow execution: {str(e)}"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def get_execution_status(self, execution_id: str) -> WorkflowExecutionInDB:
        """
        Get real-time execution status.

        Args:
            execution_id: Execution UUID

        Returns:
            Execution object with current status, progress, and logs

        Raises:
            ValueError: If execution not found

        Logs:
            - INFO: Execution status retrieved
            - ERROR: Execution not found
        """
        execution = (
            self.db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == uuid.UUID(execution_id))
            .first()
        )

        if not execution:
            error_msg = f"Execution with ID '{execution_id}' not found"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        print(
            f"[WorkflowService] Retrieved execution status: {execution.status} (progress={execution.progress_percentage}%)"
        )
        return WorkflowExecutionInDB.from_orm(execution)

    def pause_execution(self, execution_id: str) -> WorkflowExecutionInDB:
        """
        Pause running workflow execution.

        Args:
            execution_id: Execution UUID

        Returns:
            Updated execution object

        Raises:
            ValueError: If execution not found or not running

        Logs:
            - INFO: Execution paused
            - ERROR: Execution not found or invalid state
        """
        execution = (
            self.db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == uuid.UUID(execution_id))
            .first()
        )

        if not execution:
            error_msg = f"Execution with ID '{execution_id}' not found"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        if execution.status != "running":
            error_msg = f"Cannot pause execution with status '{execution.status}'"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        execution.status = "paused"

        try:
            self.db.commit()
            self.db.refresh(execution)

            print(f"[WorkflowService] Paused execution {execution_id}")
            return WorkflowExecutionInDB.from_orm(execution)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to pause execution: {str(e)}"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def resume_execution(self, execution_id: str) -> WorkflowExecutionInDB:
        """
        Resume paused workflow execution.

        Args:
            execution_id: Execution UUID

        Returns:
            Updated execution object

        Raises:
            ValueError: If execution not found or not paused

        Logs:
            - INFO: Execution resumed
            - ERROR: Execution not found or invalid state
        """
        execution = (
            self.db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == uuid.UUID(execution_id))
            .first()
        )

        if not execution:
            error_msg = f"Execution with ID '{execution_id}' not found"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        if execution.status != "paused":
            error_msg = f"Cannot resume execution with status '{execution.status}'"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        execution.status = "running"

        try:
            self.db.commit()
            self.db.refresh(execution)

            print(f"[WorkflowService] Resumed execution {execution_id}")
            # TODO: Trigger async continuation of workflow

            return WorkflowExecutionInDB.from_orm(execution)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to resume execution: {str(e)}"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def retry_step(
        self, execution_id: str, step_number: int, strategy: str
    ) -> WorkflowExecutionInDB:
        """
        Retry failed workflow step with retry strategy.

        Args:
            execution_id: Execution UUID
            step_number: Step number to retry
            strategy: Retry strategy (immediate/exponential/manual/circuit_breaker)

        Returns:
            Updated execution object

        Raises:
            ValueError: If execution/step not found or invalid strategy

        Logs:
            - INFO: Step retry initiated with strategy
            - ERROR: Retry failed

        Retry Strategies:
            - immediate: 3 attempts, 0s delay
            - exponential: 5 attempts, 2x backoff with jitter
            - manual: No retry, pause workflow
            - circuit_breaker: Open after 5 failures, 60s cooldown
        """
        execution = (
            self.db.query(WorkflowExecution)
            .filter(WorkflowExecution.execution_id == uuid.UUID(execution_id))
            .first()
        )

        if not execution:
            error_msg = f"Execution with ID '{execution_id}' not found"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        valid_strategies = ["immediate", "exponential", "manual", "circuit_breaker"]
        if strategy not in valid_strategies:
            error_msg = f"Invalid retry strategy '{strategy}'. Must be one of {valid_strategies}"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        print(
            f"[WorkflowService] Initiating retry for step {step_number} with strategy '{strategy}'"
        )

        # TODO: Implement retry logic with RetryStrategyExecutor
        # For now, just log the retry attempt

        # Update execution logs
        if "steps" not in execution.execution_logs:
            execution.execution_logs["steps"] = []

        execution.execution_logs["steps"].append(
            {
                "step_number": step_number,
                "retry_strategy": strategy,
                "retry_timestamp": datetime.utcnow().isoformat(),
            }
        )

        try:
            self.db.commit()
            self.db.refresh(execution)

            print(
                f"[WorkflowService] Retry logged for execution {execution_id}, step {step_number}"
            )
            return WorkflowExecutionInDB.from_orm(execution)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to retry step: {str(e)}"
            print(f"[WorkflowService] ERROR: {error_msg}")
            raise ValueError(error_msg)
