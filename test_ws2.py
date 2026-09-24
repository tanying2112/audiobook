import asyncio
import json

import pytest
import websockets


@pytest.mark.asyncio
async def test_websocket() -> None:
    uri = "ws://localhost:8000/api/ws/pipeline/11"

    try:
        async with websockets.connect(uri) as ws:
            print("Connected!")
            for _ in range(10):
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"Received: {msg!r}")
                data = json.loads(msg)
                if data.get("type") == "connected":
                    print("Connection confirmed!")
                    await ws.send(json.dumps({"type": "ping"}))
    except Exception as e:
        print(f"Error: {e}")


asyncio.run(test_websocket())
