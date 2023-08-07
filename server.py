import asyncio
import websockets
import json

buzz_lock = False
buzz_queue = []
host_socket = None
clients = set()
final_answers = {}

async def handle_client(websocket, path):
    global buzz_lock
    global buzz_queue
    global host_socket
    global final_answers

    try:
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

            elif message == "FINAL":
                for client in clients:
                    if client != host_socket:
                        await client.send("FINAL")

            elif message.startswith("FINAL_ANSWER:"):
                _, answer = message.split(":", 1)
                final_answers[username] = answer
                if host_socket:
                    await host_socket.send(f"FINAL_ANSWER:{username}:{answer}")

    except websockets.ConnectionClosed:
        print(f"{username} has disconnected")
    except Exception as e:
        print(f"Exception: {e}")

    finally:
        clients.remove(websocket)
        close_code = websocket.close_code
        if close_code == 1000:
            print(f"{username} has disconnected normally")
        elif close_code == 1001:
            print(f"{username} is going away (e.g., server shutdown or browser navigation).")
        elif close_code == 1002:
            print(f"{username} disconnected due to protocol error.")
        elif close_code == 1003:
            print(f"{username} disconnected due to unsupported data.")
        else:
            print(f"{username} disconnected with close code {close_code}.")

async def update_clients(win_player=None):
    if clients:
        message = json.dumps({"queue": buzz_queue, "win_player": win_player})
        tasks = [asyncio.create_task(client.send(message)) for client in clients]
        await asyncio.wait(tasks)

start_server = websockets.serve(handle_client, "0.0.0.0", 9999)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()