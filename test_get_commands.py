#!/usr/bin/env python3
"""Test script to get supported commands for a device"""

import asyncio
import json
from src.clients.websocket_client import WebSocketClient

async def main():
    # Connect to WebSocket
    ws_client = WebSocketClient(url="ws://eufy-ws-webapp.onrender.com:3000/ws")

    await ws_client.connect()

    # Query commands for T8B00511242309F6
    print("Querying supported commands for T8B00511242309F6...")
    response = await ws_client.send_command(
        "device.get_commands",
        {
            "serialNumber": "T8B00511242309F6"
        },
        wait_response=True,
        timeout=10.0
    )

    print("\nResponse:")
    print(json.dumps(response, indent=2))

    await ws_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
