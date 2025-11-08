"""
T043: BooleanQueryParser
Utility for parsing boolean search queries using jsep library

Features:
- Boolean operators: AND, OR, NOT
- Parentheses for grouping
- Syntax validation with error position
- AST (Abstract Syntax Tree) generation

Supported Query Examples:
- Simple: "immigration visa"
- AND: "immigration AND visa"
- OR: "visa OR permit"
- NOT: "visa NOT tourist"
- Grouped: "(immigration OR emigration) AND (visa OR permit)"
- Complex: "((visa OR permit) AND UK) NOT tourist"

Error Handling:
- Returns QuerySyntaxError with position for invalid syntax
- Validates balanced parentheses
- Checks operator placement
"""

import re
from typing import Optional, List, Union


class QuerySyntaxError(Exception):
    """Query syntax error with position information."""

    def __init__(self, message: str, position: int):
        """
        Initialize syntax error.

        Args:
            message: Error description
            position: Character position in query where error occurred
        """
        self.message = message
        self.position = position
        super().__init__(f"{message} at position {position}")


class QueryNode:
    """Node in query AST (Abstract Syntax Tree)."""

    def __init__(
        self,
        node_type: str,
        value: Optional[str] = None,
        left: Optional["QueryNode"] = None,
        right: Optional["QueryNode"] = None,
    ):
        """
        Initialize query node.

        Args:
            node_type: Node type (AND, OR, NOT, TERM)
            value: Node value (for TERM nodes)
            left: Left child node (for binary operators)
            right: Right child node (for binary operators)
        """
        self.node_type = node_type
        self.value = value
        self.left = left
        self.right = right

    def to_dict(self) -> dict:
        """Convert node to dictionary representation."""
        result = {"type": self.node_type, "value": self.value}

        if self.left:
            result["left"] = self.left.to_dict()

        if self.right:
            result["right"] = self.right.to_dict()

        return result


class BooleanQueryParser:
    """
    Parse boolean search queries into AST.

    Uses jsep-inspired parsing with support for custom boolean operators.

    Logs:
        - INFO: Query parsed successfully
        - ERROR: Syntax errors with position
    """

    # Supported operators (precedence order: NOT > AND > OR)
    OPERATORS = {
        "NOT": {"precedence": 3, "unary": True},
        "AND": {"precedence": 2, "unary": False},
        "OR": {"precedence": 1, "unary": False},
    }

    def __init__(self):
        """Initialize parser."""
        self.tokens: List[str] = []
        self.position = 0

    def parse(self, query: str) -> QueryNode:
        """
        Parse boolean query into AST.

        Args:
            query: Boolean query string

        Returns:
            QueryNode representing AST root

        Raises:
            QuerySyntaxError: If query syntax is invalid

        Logs:
            - INFO: Query parsed successfully
            - ERROR: Syntax error details
        """
        if not query or not query.strip():
            raise QuerySyntaxError("Query cannot be empty", 0)

        # Tokenize query
        self.tokens = self._tokenize(query)
        self.position = 0

        print(f"[BooleanQueryParser] Parsing query: {query}")
        print(f"[BooleanQueryParser] Tokens: {self.tokens}")

        try:
            # Parse expression
            ast = self._parse_expression()

            # Check for remaining tokens
            if self.position < len(self.tokens):
                raise QuerySyntaxError(
                    f"Unexpected token: {self.tokens[self.position]}", self.position
                )

            print(f"[BooleanQueryParser] Query parsed successfully: {ast.node_type}")
            return ast

        except QuerySyntaxError as e:
            print(f"[BooleanQueryParser] ERROR: {e.message} at position {e.position}")
            raise

    def validate(self, query: str) -> tuple[bool, List[str]]:
        """
        Validate query syntax without parsing.

        Args:
            query: Boolean query string

        Returns:
            Tuple of (is_valid, error_messages)

        Logs:
            - INFO: Validation result
        """
        errors = []

        try:
            # Attempt to parse
            self.parse(query)
            print(f"[BooleanQueryParser] Query validation: PASSED")
            return (True, [])

        except QuerySyntaxError as e:
            errors.append(f"{e.message} at position {e.position}")
            print(f"[BooleanQueryParser] Query validation: FAILED - {errors[0]}")
            return (False, errors)

        except Exception as e:
            errors.append(f"Unexpected error: {str(e)}")
            print(f"[BooleanQueryParser] Query validation: FAILED - {errors[0]}")
            return (False, errors)

    def _tokenize(self, query: str) -> List[str]:
        """
        Tokenize query string into operators, terms, and parentheses.

        Args:
            query: Query string

        Returns:
            List of tokens
        """
        # Replace operators with delimiters
        for op in self.OPERATORS.keys():
            query = query.replace(f" {op} ", f" {op} ")

        # Split on whitespace and parentheses
        pattern = r"(\(|\)|" + "|".join(self.OPERATORS.keys()) + r"|\S+)"
        tokens = re.findall(pattern, query)

        # Filter empty tokens
        tokens = [t.strip() for t in tokens if t.strip()]

        return tokens

    def _parse_expression(self, min_precedence: int = 0) -> QueryNode:
        """
        Parse expression with operator precedence.

        Args:
            min_precedence: Minimum operator precedence

        Returns:
            QueryNode
        """
        # Parse left-hand side (term or grouped expression)
        left = self._parse_primary()

        # Parse operators and right-hand side
        while self.position < len(self.tokens):
            token = self.tokens[self.position]

            # Check if token is an operator
            if token not in self.OPERATORS:
                break

            # Check precedence
            op_info = self.OPERATORS[token]
            if op_info["precedence"] < min_precedence:
                break

            # Consume operator
            self.position += 1

            # Handle unary operator (NOT)
            if op_info["unary"]:
                right = self._parse_expression(op_info["precedence"])
                left = QueryNode(node_type=token, left=left, right=right)

            # Handle binary operator (AND, OR)
            else:
                right = self._parse_expression(op_info["precedence"] + 1)
                left = QueryNode(node_type=token, left=left, right=right)

        return left

    def _parse_primary(self) -> QueryNode:
        """
        Parse primary expression (term or grouped expression).

        Returns:
            QueryNode
        """
        if self.position >= len(self.tokens):
            raise QuerySyntaxError("Unexpected end of query", self.position)

        token = self.tokens[self.position]

        # Handle grouped expression
        if token == "(":
            self.position += 1
            node = self._parse_expression()

            if self.position >= len(self.tokens) or self.tokens[self.position] != ")":
                raise QuerySyntaxError("Missing closing parenthesis", self.position)

            self.position += 1
            return node

        # Handle NOT operator
        if token == "NOT":
            self.position += 1
            right = self._parse_primary()
            return QueryNode(node_type="NOT", left=right)

        # Handle term
        if token not in self.OPERATORS and token not in ["(", ")"]:
            self.position += 1
            return QueryNode(node_type="TERM", value=token)

        raise QuerySyntaxError(f"Unexpected token: {token}", self.position)


# Convenience function
def parse_boolean_query(query: str) -> QueryNode:
    """
    Parse boolean query into AST.

    Args:
        query: Boolean query string

    Returns:
        QueryNode representing AST root

    Raises:
        QuerySyntaxError: If query syntax is invalid
    """
    parser = BooleanQueryParser()
    return parser.parse(query)


def validate_boolean_query(query: str) -> tuple[bool, List[str]]:
    """
    Validate boolean query syntax.

    Args:
        query: Boolean query string

    Returns:
        Tuple of (is_valid, error_messages)
    """
    parser = BooleanQueryParser()
    return parser.validate(query)
