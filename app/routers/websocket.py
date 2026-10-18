"""
websocket.py — Real-time WebSocket streaming hub for positions, ticks, and notifications.
"""

import asyncio
import json
import logging
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Manages active client WebSocket connections and message broadcasting."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("WebSocket client connected. Total connections: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Total connections: %d", len(self.active_connections))

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        payload = json.dumps(message)
        dead_connections = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.active_connections.discard(dead)


manager = ConnectionManager()


@router.websocket("/ws/stream")
async def websocket_stream_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint streaming live trading updates to Next.js clients.
    """
    await manager.connect(websocket)
    try:
        # Send initial connection acknowledgment
        await websocket.send_json({
            "type": "connection_ack",
            "status": "connected",
            "message": "Connected to TradeDash Real-Time Stream",
        })

        while True:
            # Keep connection open and handle incoming ping/pong or client commands
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except Exception:
                pass

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning("WebSocket exception: %s", e)
        manager.disconnect(websocket)
