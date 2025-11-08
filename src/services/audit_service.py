"""
T040: AuditService
Business logic layer for audit log management (INSERT-ONLY, immutable records)

Service Methods:
- log_action(user_id, action_type, resource_type, resource_id, old_value, new_value, ip_address, user_agent): Create audit log entry
- get_audit_logs(filters): Retrieve audit logs with pagination and filters
- get_user_activity(user_id, start_date, end_date): Get user activity in date range

CRITICAL:
- Audit logs are IMMUTABLE (INSERT-ONLY)
- No UPDATE or DELETE operations allowed
- 7-year retention (UK government compliance)
- Monthly partitioning for performance
"""

from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_

from ..models.audit_log import AuditLog, AuditLogCreate, AuditLogInDB, AuditLogFilter


class AuditService:
    """
    Service layer for audit log operations.

    CRITICAL: This service ONLY supports INSERT operations.
    Audit logs are immutable for compliance and security.

    Handles audit log creation and retrieval with filtering.
    """

    def __init__(self, db: Session):
        """
        Initialize AuditService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def log_action(
        self,
        user_id: str,
        action_type: str,
        resource_type: str,
        resource_id: str,
        old_value: Optional[Dict],
        new_value: Optional[Dict],
        ip_address: str,
        user_agent: Optional[str] = None,
    ) -> AuditLogInDB:
        """
        Create immutable audit log entry.

        Args:
            user_id: User UUID performing action
            action_type: Action type (create/update/delete/login/logout/config_change/role_change)
            resource_type: Resource affected (user/role/template/workflow/config/session)
            resource_id: ID of affected resource
            old_value: State before change (JSONB)
            new_value: State after change (JSONB)
            ip_address: Client IP address
            user_agent: Client user agent (optional)

        Returns:
            Created audit log entry

        Raises:
            ValueError: If audit log creation fails

        Logs:
            - INFO: Audit log created
            - ERROR: Audit log creation failed

        CRITICAL:
            This is the ONLY method that writes to audit_logs table.
            No UPDATE or DELETE methods exist by design.
        """
        audit_data = AuditLogCreate(
            user_id=user_id,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        new_log = AuditLog(
            user_id=audit_data.user_id,
            action_type=audit_data.action_type,
            resource_type=audit_data.resource_type,
            resource_id=audit_data.resource_id,
            old_value=audit_data.old_value,
            new_value=audit_data.new_value,
            ip_address=audit_data.ip_address,
            user_agent=audit_data.user_agent,
        )

        try:
            self.db.add(new_log)
            self.db.commit()
            self.db.refresh(new_log)

            print(
                f"[AuditService] Logged action: user={user_id}, action={action_type}, resource={resource_type}/{resource_id}"
            )
            return AuditLogInDB.from_orm(new_log)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to create audit log: {str(e)}"
            print(f"[AuditService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def get_audit_logs(self, filters: AuditLogFilter) -> tuple[List[AuditLogInDB], int]:
        """
        Retrieve audit logs with pagination and filters.

        Args:
            filters: AuditLogFilter object with filter criteria

        Returns:
            Tuple of (audit log list, total count)

        Logs:
            - INFO: Number of audit logs retrieved with filter details
        """
        query = self.db.query(AuditLog)

        # Apply filters
        if filters.user_id:
            query = query.filter(AuditLog.user_id == filters.user_id)

        if filters.action_type:
            query = query.filter(AuditLog.action_type == filters.action_type)

        if filters.resource_type:
            query = query.filter(AuditLog.resource_type == filters.resource_type)

        if filters.start_date:
            query = query.filter(AuditLog.timestamp >= filters.start_date)

        if filters.end_date:
            query = query.filter(AuditLog.timestamp <= filters.end_date)

        # Get total count
        total_count = query.count()

        # Apply pagination
        offset = (filters.page - 1) * filters.limit
        logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(filters.limit).all()

        log_list = [AuditLogInDB.from_orm(log) for log in logs]

        print(
            f"[AuditService] Retrieved {len(log_list)} audit logs (page={filters.page}, limit={filters.limit})"
        )
        print(
            f"[AuditService] Filters: user_id={filters.user_id}, action_type={filters.action_type}, resource_type={filters.resource_type}"
        )

        return log_list, total_count

    def get_user_activity(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime,
        page: int = 1,
        limit: int = 100,
    ) -> tuple[List[AuditLogInDB], int]:
        """
        Get user activity in date range.

        Args:
            user_id: User UUID
            start_date: Activity start date
            end_date: Activity end date
            page: Page number (1-indexed)
            limit: Results per page

        Returns:
            Tuple of (audit log list, total count)

        Logs:
            - INFO: User activity summary
        """
        query = self.db.query(AuditLog).filter(
            and_(
                AuditLog.user_id == user_id,
                AuditLog.timestamp >= start_date,
                AuditLog.timestamp <= end_date,
            )
        )

        total_count = query.count()

        offset = (page - 1) * limit
        logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()

        log_list = [AuditLogInDB.from_orm(log) for log in logs]

        print(
            f"[AuditService] Retrieved user activity for {user_id}: {len(log_list)} actions (total={total_count})"
        )
        print(f"[AuditService] Date range: {start_date} to {end_date}")

        return log_list, total_count

    def get_resource_history(
        self, resource_type: str, resource_id: str, page: int = 1, limit: int = 50
    ) -> tuple[List[AuditLogInDB], int]:
        """
        Get complete history for specific resource.

        Args:
            resource_type: Resource type (user/role/template/workflow/config/session)
            resource_id: Resource UUID
            page: Page number (1-indexed)
            limit: Results per page

        Returns:
            Tuple of (audit log list, total count)

        Logs:
            - INFO: Resource history summary
        """
        query = self.db.query(AuditLog).filter(
            and_(AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id)
        )

        total_count = query.count()

        offset = (page - 1) * limit
        logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()

        log_list = [AuditLogInDB.from_orm(log) for log in logs]

        print(f"[AuditService] Retrieved resource history: {resource_type}/{resource_id}")
        print(f"[AuditService] Total changes: {total_count}, returned: {len(log_list)}")

        return log_list, total_count

    def get_action_summary(self, start_date: datetime, end_date: datetime) -> Dict:
        """
        Get summary of actions by type in date range.

        Args:
            start_date: Summary start date
            end_date: Summary end date

        Returns:
            Dict with action type counts

        Logs:
            - INFO: Action summary details
        """
        from sqlalchemy import func

        query = (
            self.db.query(AuditLog.action_type, func.count(AuditLog.id).label("count"))
            .filter(and_(AuditLog.timestamp >= start_date, AuditLog.timestamp <= end_date))
            .group_by(AuditLog.action_type)
        )

        results = query.all()

        summary = {row.action_type: row.count for row in results}

        total_actions = sum(summary.values())

        print(
            f"[AuditService] Action summary ({start_date} to {end_date}): {total_actions} total actions"
        )
        print(f"[AuditService] Breakdown: {summary}")

        return {
            "total_actions": total_actions,
            "action_counts": summary,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
        }
