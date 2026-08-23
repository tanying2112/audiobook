import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8000/api/ws/pipeline/11"
    
    try:
        async with websockets.connect(uri) as ws:
            print("Connected!")
            for i in range(10):
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"Received: {msg}")
                data = json.loads(msg)
                if data.get("type") == "connected":
                    print("Connection confirmed!")
                    await ws.send(json.dumps({"type": "ping"}))
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"Invalid status code: {e.status_code}")
        print(f"Headers: {e.headers}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")

asyncio.run(test_websocket())
