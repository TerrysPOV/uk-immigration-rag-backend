"""
T039: SearchService
Business logic layer for advanced boolean search and query management

Service Methods:
- parse_boolean_query(query_syntax): Parse boolean query using jsep
- validate_query(query_syntax): Validate query syntax without execution
- execute_boolean_search(parsed_query): Execute parsed boolean query
- field_search(field, value, operator): Search specific fields
- save_query(user_id, query_data): Save user query
- execute_saved_query(query_id): Execute saved query

Supported Operators (FR-AS-001):
- Boolean: AND, OR, NOT
- Field: equals, contains, starts_with, regex
- Fields: title, content, metadata
"""

from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import uuid

from ..models.saved_query import SavedQuery, SavedQueryCreate, SavedQueryInDB


class QuerySyntaxError:
    """Query syntax error with position."""

    def __init__(self, message: str, position: int):
        self.message = message
        self.position = position


class QueryAST:
    """Abstract Syntax Tree for boolean query."""

    def __init__(self, node_type: str, value: any, left: any = None, right: any = None):
        self.node_type = node_type  # 'AND', 'OR', 'NOT', 'TERM'
        self.value = value
        self.left = left
        self.right = right


class SearchService:
    """
    Service layer for advanced search operations.

    Handles boolean query parsing, validation, execution, and saved queries.
    Supports field-specific search with multiple operators.
    """

    def __init__(self, db: Session):
        """
        Initialize SearchService with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def parse_boolean_query(self, query_syntax: str) -> QueryAST:
        """
        Parse boolean query using jsep library.

        Args:
            query_syntax: Boolean query string (e.g., "(term1 AND term2) OR term3")

        Returns:
            QueryAST object

        Raises:
            ValueError: If query syntax is invalid

        Logs:
            - INFO: Query parsed successfully
            - ERROR: Query parsing failed with position

        TODO:
            - Integrate jsep library for proper parsing
            - Register custom operators (AND, OR, NOT)
            - Handle nested expressions
        """
        print(f"[SearchService] Parsing query: {query_syntax}")

        # TODO: Use jsep library for parsing
        # For now, create a simple mock AST
        try:
            # Mock implementation - replace with jsep
            if "AND" in query_syntax:
                parts = query_syntax.split(" AND ")
                ast = QueryAST(
                    node_type="AND",
                    value="AND",
                    left=QueryAST("TERM", parts[0].strip()),
                    right=QueryAST("TERM", parts[1].strip()),
                )
            elif "OR" in query_syntax:
                parts = query_syntax.split(" OR ")
                ast = QueryAST(
                    node_type="OR",
                    value="OR",
                    left=QueryAST("TERM", parts[0].strip()),
                    right=QueryAST("TERM", parts[1].strip()),
                )
            elif "NOT" in query_syntax:
                term = query_syntax.replace("NOT ", "").strip()
                ast = QueryAST(node_type="NOT", value="NOT", left=QueryAST("TERM", term))
            else:
                ast = QueryAST("TERM", query_syntax.strip())

            print(f"[SearchService] Query parsed successfully: node_type={ast.node_type}")
            return ast

        except Exception as e:
            error_msg = f"Failed to parse query: {str(e)}"
            print(f"[SearchService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def validate_query(self, query_syntax: str) -> Dict:
        """
        Validate boolean query syntax without execution.

        Args:
            query_syntax: Boolean query string

        Returns:
            Dict with is_valid, errors (list of QuerySyntaxError), and parsed_ast

        Logs:
            - INFO: Query validation result
            - ERROR: Syntax errors with positions
        """
        print(f"[SearchService] Validating query: {query_syntax}")

        errors = []

        try:
            # Attempt to parse
            ast = self.parse_boolean_query(query_syntax)

            # Check for empty query
            if not query_syntax.strip():
                errors.append(QuerySyntaxError("Query cannot be empty", 0))

            # Check for balanced parentheses
            if query_syntax.count("(") != query_syntax.count(")"):
                errors.append(QuerySyntaxError("Unbalanced parentheses", 0))

            is_valid = len(errors) == 0

            result = {
                "is_valid": is_valid,
                "errors": [{"message": e.message, "position": e.position} for e in errors],
                "parsed_ast": ast if is_valid else None,
            }

            print(f"[SearchService] Query validation: is_valid={is_valid}, errors={len(errors)}")
            return result

        except ValueError as e:
            errors.append(QuerySyntaxError(str(e), 0))

            result = {
                "is_valid": False,
                "errors": [{"message": e.message, "position": e.position} for e in errors],
                "parsed_ast": None,
            }

            print(f"[SearchService] Query validation failed: {len(errors)} errors")
            return result

    def execute_boolean_search(self, parsed_query: QueryAST, limit: int = 50) -> List[Dict]:
        """
        Execute parsed boolean query.

        Args:
            parsed_query: QueryAST object
            limit: Maximum results to return

        Returns:
            List of matching documents

        Logs:
            - INFO: Search executed with result count
            - ERROR: Search execution failed

        TODO:
            - Integrate with Qdrant vector database
            - Execute boolean logic on search results
            - Support nested queries
        """
        print(f"[SearchService] Executing boolean search: node_type={parsed_query.node_type}")

        # TODO: Integrate with Qdrant and execute actual search
        # For now, return mock results

        results = []

        print(f"[SearchService] Boolean search executed: {len(results)} results (limit={limit})")
        return results

    def field_search(self, field: str, value: str, operator: str, limit: int = 50) -> List[Dict]:
        """
        Search specific field with operator.

        Args:
            field: Field name (title, content, metadata)
            value: Search value
            operator: Search operator (equals, contains, starts_with, regex)
            limit: Maximum results to return

        Returns:
            List of matching documents

        Raises:
            ValueError: If field or operator invalid

        Logs:
            - INFO: Field search executed
            - ERROR: Invalid field or operator
        """
        valid_fields = ["title", "content", "metadata"]
        valid_operators = ["equals", "contains", "starts_with", "regex"]

        if field not in valid_fields:
            error_msg = f"Invalid field '{field}'. Must be one of {valid_fields}"
            print(f"[SearchService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        if operator not in valid_operators:
            error_msg = f"Invalid operator '{operator}'. Must be one of {valid_operators}"
            print(f"[SearchService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        print(f"[SearchService] Field search: field={field}, operator={operator}, value={value}")

        # TODO: Integrate with Qdrant and execute field search
        # For now, return mock results

        results = []

        print(f"[SearchService] Field search executed: {len(results)} results (limit={limit})")
        return results

    def save_query(self, user_id: str, query_data: SavedQueryCreate) -> SavedQueryInDB:
        """
        Save user query with parsed AST.

        Args:
            user_id: User UUID
            query_data: Query creation data

        Returns:
            Saved query object

        Raises:
            ValueError: If query save fails

        Logs:
            - INFO: Query saved successfully
            - ERROR: Query save failed
        """
        new_query = SavedQuery(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            query_name=query_data.query_name,
            query_syntax=query_data.query_syntax,
            boolean_operators=query_data.boolean_operators,
        )

        try:
            self.db.add(new_query)
            self.db.commit()
            self.db.refresh(new_query)

            print(f"[SearchService] Saved query '{new_query.query_name}' for user {user_id}")
            return SavedQueryInDB.from_orm(new_query)

        except IntegrityError as e:
            self.db.rollback()
            error_msg = f"Failed to save query: {str(e)}"
            print(f"[SearchService] ERROR: {error_msg}")
            raise ValueError(error_msg)

    def execute_saved_query(
        self, query_id: str, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Dict]:
        """
        Execute saved query with optional limit/offset overrides.

        Args:
            query_id: Saved query UUID
            limit: Optional result limit override
            offset: Optional result offset override

        Returns:
            List of matching documents

        Raises:
            ValueError: If query not found

        Logs:
            - INFO: Saved query executed
            - ERROR: Query not found or execution failed
        """
        saved_query = self.db.query(SavedQuery).filter(SavedQuery.id == uuid.UUID(query_id)).first()

        if not saved_query:
            error_msg = f"Saved query with ID '{query_id}' not found"
            print(f"[SearchService] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Parse and execute query
        parsed_query = self.parse_boolean_query(saved_query.query_syntax)
        results = self.execute_boolean_search(parsed_query, limit or 50)

        # Update execution stats
        saved_query.last_executed_at = datetime.utcnow()
        saved_query.execution_count += 1

        try:
            self.db.commit()
            print(
                f"[SearchService] Executed saved query '{saved_query.query_name}': {len(results)} results"
            )
            return results

        except IntegrityError as e:
            self.db.rollback()
            print(f"[SearchService] ERROR: Failed to update query stats - {str(e)}")
            return results

    def get_user_queries(
        self, user_id: str, page: int = 1, limit: int = 50
    ) -> tuple[List[SavedQueryInDB], int]:
        """
        List user's saved queries with pagination.

        Args:
            user_id: User UUID
            page: Page number (1-indexed)
            limit: Results per page

        Returns:
            Tuple of (query list, total count)

        Logs:
            - INFO: Number of queries retrieved
        """
        query = self.db.query(SavedQuery).filter(SavedQuery.user_id == uuid.UUID(user_id))

        total_count = query.count()

        offset = (page - 1) * limit
        queries = query.offset(offset).limit(limit).all()

        query_list = [SavedQueryInDB.from_orm(q) for q in queries]

        print(f"[SearchService] Retrieved {len(query_list)} saved queries for user {user_id}")
        return query_list, total_count
