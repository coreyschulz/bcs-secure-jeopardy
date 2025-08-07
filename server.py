import asyncio
import websockets
import json
import time
import logging
import uuid
import os
from typing import Set, Dict, Optional

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('jeopardy_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Game state
buzz_lock = False
buzz_queue = []
host_socket = None
clients: Set[websockets.WebSocketServerProtocol] = set()
client_info: Dict[websockets.WebSocketServerProtocol, Dict] = {}
drawing_mode = False
currently_drawing = []  # Track who is currently drawing

# Host authentication
host_password = os.environ.get('HOST_PASSWORD', str(uuid.uuid4()))
logger.info(f"Host password: {host_password}")

# Scorekeeping
player_scores: Dict[str, int] = {}
scoreboard_enabled = False

# Heartbeat configuration
HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 90   # seconds - Increased to be more tolerant of inactive tabs

# Rate limiting configuration
RATE_LIMIT_WINDOW = 60   # seconds
RATE_LIMIT_MAX_MESSAGES = 100  # messages per window
RATE_LIMIT_BUZZ_WINDOW = 5   # seconds  
RATE_LIMIT_MAX_BUZZ = 3      # buzz attempts per window

# Security configuration
MAX_USERNAME_LENGTH = 50
MAX_MESSAGE_LENGTH = 500000  # Increased to accommodate drawing submissions
MAX_CLIENTS = 50
MAX_FINAL_ANSWER_LENGTH = 500
MAX_DRAWING_SIZE = 500000  # 500KB limit for drawing data

def validate_input(text: str, max_length: int, field_name: str) -> str:
    """Validate and sanitize input text"""
    if not isinstance(text, str):
        raise ValueError(f"{field_name} must be a string")
    
    # Remove control characters and excessive whitespace
    sanitized = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
    sanitized = ' '.join(sanitized.split())  # Normalize whitespace
    
    if len(sanitized) > max_length:
        raise ValueError(f"{field_name} exceeds maximum length of {max_length}")
    
    if not sanitized.strip():
        raise ValueError(f"{field_name} cannot be empty")
    
    return sanitized.strip()

def check_rate_limit(client_data: dict, limit_type: str = 'general') -> bool:
    """Check if client is within rate limits"""
    current_time = time.time()
    
    if limit_type == 'general':
        window = RATE_LIMIT_WINDOW
        max_messages = RATE_LIMIT_MAX_MESSAGES
        messages_key = 'message_timestamps'
    elif limit_type == 'buzz':
        window = RATE_LIMIT_BUZZ_WINDOW
        max_messages = RATE_LIMIT_MAX_BUZZ
        messages_key = 'buzz_timestamps'
    else:
        return True
    
    if messages_key not in client_data:
        client_data[messages_key] = []
    
    # Clean old timestamps
    client_data[messages_key] = [
        ts for ts in client_data[messages_key] 
        if current_time - ts < window
    ]
    
    # Check if limit exceeded
    if len(client_data[messages_key]) >= max_messages:
        return False
    
    # Add current timestamp
    client_data[messages_key].append(current_time)
    return True

async def handle_client(websocket):
    global buzz_lock, buzz_queue, host_socket
    
    # Check connection limit
    if len(clients) >= MAX_CLIENTS:
        logger.warning(f"Connection rejected: max clients ({MAX_CLIENTS}) reached")
        await websocket.close(code=1013, reason="Server full")
        return
    
    client_data = {
        'username': None,
        'last_heartbeat': time.time(),
        'is_host': False,
        'message_timestamps': [],
        'buzz_timestamps': []
    }
    client_info[websocket] = client_data
    clients.add(websocket)
    
    try:
        # Wait for username with timeout
        raw_username = await asyncio.wait_for(websocket.recv(), timeout=30.0)
        
        # Validate and sanitize username
        try:
            username = validate_input(raw_username, MAX_USERNAME_LENGTH, "Username")
        except ValueError as e:
            logger.warning(f"Invalid username from {websocket.remote_address}: {e}")
            await websocket.close(code=1008, reason=str(e))
            return
        
        # Check if this is a host connection with password
        if username.startswith("host:"):
            parts = username.split(":", 1)
            if len(parts) == 2 and parts[1] == host_password:
                username = "host"
                client_data['is_host'] = True
                logger.info(f"Host authenticated from {websocket.remote_address}")
            else:
                logger.warning(f"Invalid host password attempt from {websocket.remote_address}")
                await websocket.close(code=1008, reason="Invalid host password")
                return
        else:
            client_data['is_host'] = False
            # Initialize score for new players
            if username not in player_scores:
                player_scores[username] = 0
        
        client_data['username'] = username
        logger.info(f"Client {username} connected from {websocket.remote_address}")

        if client_data['is_host']:
            if host_socket is not None:
                logger.warning(f"New host connection replacing existing host")
            host_socket = websocket

        # Send initial state to all clients (including new one)
        await update_clients()

        async for raw_message in websocket:
            client_data['last_heartbeat'] = time.time()
            
            # Validate message length
            if len(raw_message) > MAX_MESSAGE_LENGTH:
                logger.warning(f"Message too long from {username}: {len(raw_message)} chars")
                await safe_send(websocket, json.dumps({"error": "Message too long"}))
                continue
            
            # Check general rate limit
            if not check_rate_limit(client_data, 'general'):
                logger.warning(f"Rate limit exceeded for {username}")
                await safe_send(websocket, json.dumps({"error": "Rate limit exceeded"}))
                continue
            
            try:
                await handle_message(websocket, raw_message, username)
            except Exception as e:
                logger.error(f"Error handling message from {username}: {e}")
                await safe_send(websocket, json.dumps({"error": "Message processing failed"}))
                
    except asyncio.TimeoutError:
        logger.warning(f"Client connection timed out during setup")
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Client {client_data.get('username', 'unknown')} disconnected")
    except Exception as e:
        logger.error(f"Unexpected error in handle_client: {e}")
    finally:
        await cleanup_client(websocket)

async def handle_message(websocket, message, username):
    global buzz_lock, buzz_queue, host_socket, drawing_mode, currently_drawing, scoreboard_enabled, player_scores
    
    client_data = client_info.get(websocket, {})
    
    if message == "PING":
        await safe_send(websocket, "PONG")
        return
    
    if message == "BUZZ":
        # Additional rate limiting for buzz attempts
        if not check_rate_limit(client_data, 'buzz'):
            logger.warning(f"Buzz rate limit exceeded for {username}")
            await safe_send(websocket, "PENALTY")
            return
            
        if buzz_lock and username not in buzz_queue:
            logger.info(f"{username} buzzed in!")
            buzz_queue.append(username)
            await update_clients()
        else:
            logger.info(f"{username} buzzed in but was denied!")
            await safe_send(websocket, "PENALTY")

    elif message == "BOOT" and websocket == host_socket:
        if buzz_queue:
            removed_player = buzz_queue.pop(0)
            logger.info(f"Host booted {removed_player}")
        await update_clients()

    elif message == "WIN" and websocket == host_socket:
        if buzz_queue:
            win_player = buzz_queue.pop(0)
            buzz_queue = []
            buzz_lock = False
            logger.info(f"Host marked {win_player} as winner")
            await update_clients(win_player)

    elif message == "LOCK" and websocket == host_socket:
        buzz_lock = False
        buzz_queue = []
        logger.info("Host locked buzzing")
        await update_clients()
        
    elif message == "UNLOCK" and websocket == host_socket:
        buzz_lock = True
        logger.info("Host unlocked buzzing")
        await update_clients()
        
    elif message == "FINAL" and websocket == host_socket:
        logger.info("Host started Final Jeopardy")
        await broadcast_to_clients("FINAL")
        
    elif message == "WAGER_REQUEST" and websocket == host_socket:
        logger.info("Host requested wagers")
        await broadcast_to_clients("WAGER_REQUEST")
        
    elif message == "RESET_GAME" and websocket == host_socket:
        logger.info("Host reset the game")
        # Reset server game state
        buzz_lock = False
        buzz_queue = []
        drawing_mode = False
        currently_drawing = []
        # Reset all scores
        for player in player_scores:
            player_scores[player] = 0
        await broadcast_to_clients("RESET_GAME")
        await update_clients()
    
    elif message.startswith("TOGGLE_SCOREBOARD:") and websocket == host_socket:
        enabled = message.split(":")[1] == "ON"
        scoreboard_enabled = enabled
        logger.info(f"Host set scoreboard to {enabled}")
        await update_clients()
    
    elif message.startswith("SCORE_UPDATE:") and websocket == host_socket:
        try:
            parts = message.split(":")
            if len(parts) >= 3:
                player_name = parts[1]
                score_change = int(parts[2])
                if player_name in player_scores:
                    player_scores[player_name] += score_change
                    logger.info(f"Host updated {player_name}'s score by {score_change} to {player_scores[player_name]}")
                    await update_clients()
                else:
                    logger.warning(f"Score update for unknown player: {player_name}")
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid score update format: {message}, error: {e}")
        
    elif message.startswith("FINAL_ANSWER:") and websocket != host_socket:
        # Validate final answer format and length
        try:
            parts = message.split(":", 2)
            if len(parts) < 3:
                raise ValueError("Invalid final answer format")
            
            answer_username = validate_input(parts[1], MAX_USERNAME_LENGTH, "Answer username")
            answer_text = validate_input(parts[2], MAX_FINAL_ANSWER_LENGTH, "Final answer")
            
            # Verify username matches
            if answer_username != username:
                logger.warning(f"Username mismatch in final answer from {username}")
                await safe_send(websocket, json.dumps({"error": "Username mismatch"}))
                return
            
            formatted_message = f"FINAL_ANSWER:{answer_username}:{answer_text}"
            logger.info(f"Final answer received from {username}: {answer_text[:50]}...")
            
            if host_socket:
                await safe_send(host_socket, formatted_message)
                
        except ValueError as e:
            logger.warning(f"Invalid final answer from {username}: {e}")
            await safe_send(websocket, json.dumps({"error": f"Invalid final answer: {e}"}))
    
    elif message.startswith("WAGER:") and websocket != host_socket:
        # Validate wager format and value
        try:
            parts = message.split(":", 2)
            if len(parts) < 3:
                raise ValueError("Invalid wager format")
            
            wager_username = validate_input(parts[1], MAX_USERNAME_LENGTH, "Wager username")
            wager_amount = parts[2].strip()
            
            # Verify username matches
            if wager_username != username:
                logger.warning(f"Username mismatch in wager from {username}")
                await safe_send(websocket, json.dumps({"error": "Username mismatch"}))
                return
            
            # Validate wager amount (can be numeric or text)
            wager_amount = validate_input(wager_amount, 50, "Wager amount")
            
            formatted_message = f"WAGER:{wager_username}:{wager_amount}"
            logger.info(f"Wager received from {username}: ${wager_amount}")
            
            if host_socket:
                await safe_send(host_socket, formatted_message)
                
        except ValueError as e:
            logger.warning(f"Invalid wager from {username}: {e}")
            await safe_send(websocket, json.dumps({"error": f"Invalid wager: {e}"}))
    
    elif message.startswith("DRAWING_MODE:") and websocket == host_socket:
        mode = message.split(":")[1]
        drawing_mode = (mode == "ON")
        if not drawing_mode:
            currently_drawing = []  # Clear the list when drawing mode ends
        logger.info(f"Host set drawing mode to {drawing_mode}")
        await broadcast_to_clients(f"DRAWING_MODE:{'ON' if drawing_mode else 'OFF'}")
    
    elif message == "CLEAR_DRAWINGS" and websocket == host_socket:
        logger.info("Host clearing all drawings")
        await broadcast_to_clients("CLEAR_DRAWINGS")
        
    elif message.startswith("DRAWING_SUBMIT:") and websocket != host_socket:
        if not drawing_mode:
            logger.warning(f"Drawing submission from {username} rejected - drawing mode is off")
            await safe_send(websocket, json.dumps({"error": "Drawing mode is not active"}))
            return
            
        # Validate drawing submission size
        if len(message) > MAX_DRAWING_SIZE:
            logger.warning(f"Drawing submission from {username} too large: {len(message)} bytes")
            await safe_send(websocket, json.dumps({"error": "Drawing is too large"}))
            return
            
        try:
            # Parse and validate drawing data
            drawing_json = message[15:]  # Remove "DRAWING_SUBMIT:"
            drawing_data = json.loads(drawing_json)
            
            # Validate required fields
            if not all(key in drawing_data for key in ['username', 'timestamp', 'imageData']):
                raise ValueError("Missing required fields in drawing submission")
            
            # Verify username matches
            if drawing_data['username'] != username:
                logger.warning(f"Username mismatch in drawing from {username}")
                await safe_send(websocket, json.dumps({"error": "Username mismatch"}))
                return
            
            # Forward to host and all other clients
            if host_socket:
                await safe_send(host_socket, message)
                # Broadcast to all non-host clients
                await broadcast_to_clients(message)
                logger.info(f"Drawing received from {username}, broadcasting to all clients")
            else:
                logger.warning(f"Drawing from {username} but no host connected")
                
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Invalid drawing submission from {username}: {e}")
            await safe_send(websocket, json.dumps({"error": f"Invalid drawing: {e}"}))
    
    else:
        logger.warning(f"Unknown message from {username}: {message[:100]}")
        await safe_send(websocket, json.dumps({"error": "Unknown message type"}))

async def cleanup_client(websocket):
    """Clean up client connection and update game state"""
    global host_socket, currently_drawing, player_scores
    
    if websocket in client_info:
        username = client_info[websocket].get('username', 'unknown')
        is_host = client_info[websocket].get('is_host', False)
        
        # Remove from buzz queue if present
        was_in_queue = username in buzz_queue
        if was_in_queue:
            buzz_queue.remove(username)
            logger.info(f"Removed {username} from buzz queue due to disconnect")
        
        # Remove from currently drawing list if present
        if username in currently_drawing:
            currently_drawing.remove(username)
            logger.info(f"Removed {username} from currently drawing list due to disconnect")
        
        # Clear host socket if host disconnected
        if is_host and websocket == host_socket:
            host_socket = None
            logger.warning("Host disconnected")
        else:
            # Keep player score even if disconnected (they might reconnect)
            # Score will persist until game reset
            logger.info(f"Player {username} disconnected, score preserved: {player_scores.get(username, 0)}")
        
        del client_info[websocket]
        
        # Update all clients with new connected players list
        if not is_host:  # Only update if a non-host player disconnected
            await update_clients()
    
    clients.discard(websocket)

async def safe_send(websocket, message):
    """Safely send message to websocket with error handling"""
    try:
        await websocket.send(message)
        return True
    except websockets.exceptions.ConnectionClosed:
        logger.debug(f"Attempted to send to closed connection")
        await cleanup_client(websocket)
        return False
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return False

async def update_clients(win_player=None):
    """Update all clients with current game state"""
    global scoreboard_enabled, player_scores
    
    if not clients:
        return
    
    # Get list of connected non-host players
    connected_names = [info['username'] for info in client_info.values() if info['username'] and not info['is_host']]
    
    # Build game state message
    game_state = {
        "queue": buzz_queue,
        "win_player": win_player,
        "connected_players": connected_names,
        "buzz_lock": buzz_lock,
        "scoreboard_enabled": scoreboard_enabled
    }
    
    # Include scores if scoreboard is enabled
    if scoreboard_enabled:
        game_state["scores"] = player_scores
    
    message = json.dumps(game_state)
    failed_clients = []
    
    for client in clients.copy():  # Use copy to avoid modification during iteration
        success = await safe_send(client, message)
        if not success:
            failed_clients.append(client)
    
    # Clean up failed clients
    for client in failed_clients:
        await cleanup_client(client)

async def broadcast_to_clients(message):
    """Broadcast a message to all non-host clients"""
    if not clients:
        return
        
    failed_clients = []
    for client in clients.copy():
        if client != host_socket:  # Don't send to host
            success = await safe_send(client, message)
            if not success:
                failed_clients.append(client)
    
    for client in failed_clients:
        await cleanup_client(client)

async def heartbeat_monitor():
    """Monitor client connections and remove stale ones"""
    while True:
        try:
            current_time = time.time()
            stale_clients = []
            
            for websocket, client_data in client_info.items():
                if current_time - client_data['last_heartbeat'] > HEARTBEAT_TIMEOUT:
                    logger.warning(f"Client {client_data.get('username', 'unknown')} heartbeat timeout")
                    stale_clients.append(websocket)
            
            for websocket in stale_clients:
                try:
                    await websocket.close()
                except:
                    pass
                await cleanup_client(websocket)
            
            await asyncio.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            logger.error(f"Error in heartbeat monitor: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

async def main():
    logger.info("Starting BCS Secure Jeopardy Server on port 9999")
    
    # Start heartbeat monitor
    heartbeat_task = asyncio.create_task(heartbeat_monitor())
    
    try:
        # Start WebSocket server
        start_server = websockets.serve(
            handle_client, 
            "0.0.0.0", 
            9999,
            ping_interval=20,  # Send ping every 20 seconds
            ping_timeout=10    # Wait 10 seconds for pong
        )
        
        server = await start_server
        logger.info("Server started successfully")
        
        # Run forever
        await asyncio.Future()
        
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        heartbeat_task.cancel()
        logger.info("Server shutting down")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
