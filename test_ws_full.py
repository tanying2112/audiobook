import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8000/api/ws/pipeline/11"
    
    try:
        async with websockets.connect(uri) as ws:
            print("Connected!")
            
            # Receive connected message
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {msg}")
            
            # Test ping
            print("\n--- Testing ping ---")
            await ws.send(json.dumps({"type": "ping"}))
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {msg}")
            
            # Test pause
            print("\n--- Testing pause ---")
            await ws.send(json.dumps({"type": "pause"}))
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {msg}")
            
            # Test resume
            print("\n--- Testing resume ---")
            await ws.send(json.dumps({"type": "resume"}))
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {msg}")
            
            # Test status
            print("\n--- Testing status ---")
            await ws.send(json.dumps({"type": "status"}))
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {msg}")
            
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")

asyncio.run(test_websocket())
