import asyncio
import websockets
import json

buzz_lock = False
buzz_queue = []
host_socket = None
clients = set()

async def handle_client(websocket, path):
    global buzz_lock
    global buzz_queue
    global host_socket
    clients.add(websocket)
    username = await websocket.recv()
    print(f"{username} has connected")

    if username == "host":
        host_socket = websocket

    async for message in websocket:
        if message == "BUZZ":
            if buzz_lock and username not in buzz_queue:
                print(f"{username} buzzed in!")
                buzz_queue.append(username)
                await update_clients()
            else:
                print(f"{username} buzzed in but was denied!")
                await websocket.send("PENALTY")

        elif message == "BOOT":
            if buzz_queue:
                buzz_queue.pop(0)
            await update_clients()

        elif message == "WIN":
            if buzz_queue:
                win_player = buzz_queue.pop(0)
                buzz_queue = []
                buzz_lock = False
                await update_clients(win_player)

        elif message == "LOCK":
            buzz_lock = False
            buzz_queue = []
            await update_clients()
        elif message == "UNLOCK":
            buzz_lock = True

    clients.remove(websocket)

async def update_clients(win_player=None):
    if clients:
        message = json.dumps({"queue": buzz_queue, "win_player": win_player})
        tasks = [asyncio.create_task(client.send(message)) for client in clients]
        await asyncio.wait(tasks)

start_server = websockets.serve(handle_client, "0.0.0.0", 9999)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
