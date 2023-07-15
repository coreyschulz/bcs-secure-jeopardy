import asyncio
import websockets
import json

buzz_lock = False
buzz_queue = []
host_socket = None

async def handle_client(websocket, path):
    global buzz_lock
    global buzz_queue
    global host_socket
    username = await websocket.recv()
    print(f"{username} has connected")

    if username == "host":
        host_socket = websocket

    async for message in websocket:
        if message == "BUZZ":
            if buzz_lock and username not in buzz_queue:
                print(f"{username} buzzed in!")
                buzz_queue.append(username)
                if host_socket:
                    await host_socket.send(json.dumps({"queue": buzz_queue}))
            else:
                await websocket.send("PENALTY")
        elif message == "LOCK":
            buzz_lock = False
            buzz_queue = []
            if host_socket:
                await host_socket.send(json.dumps({"queue": buzz_queue}))
        elif message == "UNLOCK":
            buzz_lock = True

start_server = websockets.serve(handle_client, "0.0.0.0", 9999)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
