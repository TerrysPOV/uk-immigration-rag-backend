"""
T041: MetricsWebSocketManager
WebSocket manager for real-time metrics broadcasting

Features:
- JWT token authentication via query param ?token=<jwt>
- 30-second broadcast interval (FR-AD-008)
- Exponential backoff reconnection logic
- Connection limit per user (max 3 concurrent connections)
- Automatic cleanup on disconnect

Broadcast Format:
{
    "type": "metrics_update",
    "timestamp": "2025-10-15T12:34:56Z",
    "data": {
        "cpu": {"percent": 45.2, "status": "healthy"},
        "memory": {"percent": 62.1, "used_mb": 8192, "total_mb": 16384, "status": "healthy"},
        ...
    }
}

Reconnection Strategy:
- Initial delay: 1s
- Max delay: 30s
- Backoff multiplier: 2x
- Jitter: ±20%
"""

from typing import Dict, List, Optional
from datetime import datetime
import asyncio
import json
import uuid
import random

from fastapi import WebSocket, WebSocketDisconnect


class MetricsWebSocketManager:
    """
    WebSocket manager for real-time metrics broadcasting.

    Manages client connections, broadcasts metrics every 30 seconds,
    and handles reconnection with exponential backoff.
    """

    def __init__(self):
        """Initialize WebSocket manager."""
        # Active connections: {connection_id: WebSocket}
        self.active_connections: Dict[str, WebSocket] = {}

        # User connections: {user_id: [connection_ids]}
        self.user_connections: Dict[str, List[str]] = {}

        # Connection metadata: {connection_id: {"user_id": str, "connected_at": datetime}}
        self.connection_metadata: Dict[str, Dict] = {}

        # Broadcast task
        self.broadcast_task: Optional[asyncio.Task] = None

        # Max connections per user
        self.max_connections_per_user = 3

        print("[MetricsWebSocketManager] Initialized")

    async def connect(self, websocket: WebSocket, user_id: str, token: str) -> str:
        """
        Accept WebSocket connection after authentication.

        Args:
            websocket: WebSocket connection object
            user_id: Authenticated user ID
            token: JWT token (already validated)

        Returns:
            Connection ID (UUID)

        Raises:
            ValueError: If user has too many concurrent connections

        Logs:
            - INFO: Connection accepted
            - ERROR: Connection rejected (too many connections)
        """
        # Check connection limit
        user_connection_count = len(self.user_connections.get(user_id, []))
        if user_connection_count >= self.max_connections_per_user:
            error_msg = (
                f"User {user_id} has reached max connections ({self.max_connections_per_user})"
            )
            print(f"[MetricsWebSocketManager] ERROR: {error_msg}")
            raise ValueError(error_msg)

        # Accept connection
        await websocket.accept()

        # Generate connection ID
        connection_id = str(uuid.uuid4())

        # Store connection
        self.active_connections[connection_id] = websocket

        # Track user connections
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(connection_id)

        # Store metadata
        self.connection_metadata[connection_id] = {
            "user_id": user_id,
            "connected_at": datetime.utcnow(),
            "token": token,
        }

        print(
            f"[MetricsWebSocketManager] Connection accepted: connection_id={connection_id}, user_id={user_id}"
        )
        print(
            f"[MetricsWebSocketManager] Total connections: {len(self.active_connections)} (user {user_id}: {len(self.user_connections[user_id])})"
        )

        # Start broadcast ticker if not running
        if self.broadcast_task is None or self.broadcast_task.done():
            self.broadcast_task = asyncio.create_task(self.start_30s_ticker())

        return connection_id

    async def disconnect(self, connection_id: str):
        """
        Remove WebSocket connection.

        Args:
            connection_id: Connection UUID to remove

        Logs:
            - INFO: Connection removed
        """
        if connection_id in self.active_connections:
            # Get metadata
            metadata = self.connection_metadata.get(connection_id, {})
            user_id = metadata.get("user_id")

            # Remove from active connections
            del self.active_connections[connection_id]

            # Remove from user connections
            if user_id and user_id in self.user_connections:
                self.user_connections[user_id].remove(connection_id)
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]

            # Remove metadata
            if connection_id in self.connection_metadata:
                del self.connection_metadata[connection_id]

            print(
                f"[MetricsWebSocketManager] Connection removed: connection_id={connection_id}, user_id={user_id}"
            )
            print(f"[MetricsWebSocketManager] Total connections: {len(self.active_connections)}")

            # Stop broadcast ticker if no connections
            if not self.active_connections and self.broadcast_task:
                self.broadcast_task.cancel()
                self.broadcast_task = None
                print("[MetricsWebSocketManager] Broadcast ticker stopped (no active connections)")

    async def broadcast_metrics(self, metrics_data: Dict):
        """
        Broadcast metrics to all connected clients.

        Args:
            metrics_data: Metrics dictionary to broadcast

        Logs:
            - INFO: Broadcast details (connection count)
            - WARNING: Failed broadcasts (connection errors)
        """
        message = {
            "type": "metrics_update",
            "timestamp": datetime.utcnow().isoformat(),
            "data": metrics_data,
        }

        message_json = json.dumps(message)

        successful_broadcasts = 0
        failed_broadcasts = 0
        disconnected_ids = []

        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(message_json)
                successful_broadcasts += 1

            except WebSocketDisconnect:
                print(
                    f"[MetricsWebSocketManager] WARNING: Connection {connection_id} disconnected during broadcast"
                )
                disconnected_ids.append(connection_id)
                failed_broadcasts += 1

            except Exception as e:
                print(
                    f"[MetricsWebSocketManager] WARNING: Failed to send to {connection_id}: {str(e)}"
                )
                failed_broadcasts += 1

        # Clean up disconnected connections
        for connection_id in disconnected_ids:
            await self.disconnect(connection_id)

        print(
            f"[MetricsWebSocketManager] Broadcast complete: successful={successful_broadcasts}, failed={failed_broadcasts}"
        )

    async def start_30s_ticker(self):
        """
        Start 30-second broadcast ticker with exponential backoff reconnection.

        Broadcasts metrics every 30 seconds to all connected clients.
        Implements exponential backoff with jitter for reconnection failures.

        Logs:
            - INFO: Ticker started/stopped
            - INFO: Each broadcast cycle
            - WARNING: Broadcast errors with retry details
        """
        print("[MetricsWebSocketManager] Starting 30s broadcast ticker")

        retry_delay = 1.0  # Initial delay: 1 second
        max_delay = 30.0  # Max delay: 30 seconds
        backoff_multiplier = 2.0
        jitter_percentage = 0.2  # ±20% jitter

        while True:
            try:
                # Wait 30 seconds
                await asyncio.sleep(30)

                # Get metrics (mock for now - should call AnalyticsService)
                # TODO: Integrate with AnalyticsService.get_resource_usage()
                metrics_data = {
                    "cpu": {"percent": 45.2, "status": "healthy"},
                    "memory": {
                        "percent": 62.1,
                        "used_mb": 8192,
                        "total_mb": 16384,
                        "status": "healthy",
                    },
                    "storage": {
                        "percent": 55.3,
                        "used_gb": 100.5,
                        "total_gb": 200.0,
                        "status": "healthy",
                    },
                    "database_connections": {
                        "active": 15,
                        "max": 100,
                        "percent": 15.0,
                        "status": "healthy",
                    },
                    "websocket_connections": {
                        "active": len(self.active_connections),
                        "status": "healthy",
                    },
                }

                # Broadcast to all connections
                await self.broadcast_metrics(metrics_data)

                # Reset retry delay on successful broadcast
                retry_delay = 1.0

            except asyncio.CancelledError:
                print("[MetricsWebSocketManager] Broadcast ticker cancelled")
                break

            except Exception as e:
                print(f"[MetricsWebSocketManager] WARNING: Broadcast error: {str(e)}")

                # Apply exponential backoff with jitter
                jitter = retry_delay * jitter_percentage * (2 * random.random() - 1)
                current_delay = min(retry_delay + jitter, max_delay)

                print(
                    f"[MetricsWebSocketManager] Retrying broadcast in {current_delay:.2f}s (exponential backoff)"
                )
                await asyncio.sleep(current_delay)

                # Increase delay for next retry
                retry_delay = min(retry_delay * backoff_multiplier, max_delay)

    async def send_to_user(self, user_id: str, message: Dict):
        """
        Send message to all connections for specific user.

        Args:
            user_id: User ID
            message: Message dictionary to send

        Logs:
            - INFO: Message sent to user
            - WARNING: No connections for user
        """
        if user_id not in self.user_connections:
            print(f"[MetricsWebSocketManager] WARNING: No connections for user {user_id}")
            return

        message_json = json.dumps(message)
        connection_ids = self.user_connections[user_id].copy()

        for connection_id in connection_ids:
            if connection_id in self.active_connections:
                try:
                    websocket = self.active_connections[connection_id]
                    await websocket.send_text(message_json)
                except Exception as e:
                    print(
                        f"[MetricsWebSocketManager] WARNING: Failed to send to connection {connection_id}: {str(e)}"
                    )

        print(
            f"[MetricsWebSocketManager] Message sent to user {user_id} ({len(connection_ids)} connections)"
        )

    def get_connection_count(self) -> int:
        """Get total active connection count."""
        return len(self.active_connections)

    def get_user_connection_count(self, user_id: str) -> int:
        """Get connection count for specific user."""
        return len(self.user_connections.get(user_id, []))


# Global instance
metrics_ws_manager = MetricsWebSocketManager()
