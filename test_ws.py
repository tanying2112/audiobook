import asyncio
import websockets
import json

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2IiwidXNlcm5hbWUiOiJ3c190ZXN0X3VzZXIiLCJyb2xlcyI6W10sInBlcm1pc3Npb25zIjpbXSwiZXhwIjoxNzg3NDExOTU5LCJpYXQiOjE3ODc0MTAxNTksInR5cGUiOiJhY2Nlc3MifQ.h652e0p-0Wlf2ZG4nPqhrFQqE5eEmV1_UR-e6gX5d8M"

async def test_websocket():
    uri = "ws://localhost:8000/api/ws/pipeline/11"
    uri_with_token = f"{uri}?token={TOKEN}"
    
    try:
        async with websockets.connect(uri_with_token) as ws:
            print("Connected!")
            for i in range(5):
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"Received: {msg}")
                data = json.loads(msg)
                if data.get("type") == "connected":
                    print("Connection confirmed!")
                    await ws.send(json.dumps({"type": "ping"}))
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test_websocket())
