import socket
import threading
import time

class Server:
    def __init__(self):
        self.host = 'localhost'
        self.port = 9999
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind((self.host, self.port))
        print("Server started and listening on {}:{}".format(self.host, self.port))

        self.clients = {}
        self.buzz_lock = threading.Lock()
        self.buzz_allowed = False
        self.buzzes = []

    def start(self):
        self.server.listen()
        while True:
            client, address = self.server.accept()
            username = client.recv(1024).decode('utf-8')  # receive username from client
            self.clients[username] = client
            print("{} has connected".format(username))
            thread = threading.Thread(target=self.handle_client, args=(client, username,))
            thread.start()

    def handle_client(self, client, username):
        while True:
            message = client.recv(1024).decode('utf-8')
            if message == "LOCK":
                with self.buzz_lock:
                    self.buzz_allowed = False
                print("Buzzing is now locked")
            elif message == "UNLOCK":
                with self.buzz_lock:
                    self.buzz_allowed = True
                print("Buzzing is now unlocked")
            elif message == "BUZZ":
                if not self.buzz_allowed:
                    client.send("TIMEOUT".encode('utf-8'))
                    print("{} buzzed too early, timeout imposed".format(username))
                    time.sleep(3)  # pause this client for 3 seconds
                else:
                    self.buzzes.append(username)
                    print("{} buzzed in!".format(username))
            elif message == "CLEAR":
                buzzes = self.buzzes.copy()
                self.buzzes.clear()
                print("Buzzes cleared, order was: {}".format(buzzes))
                client.send(str(buzzes).encode('utf-8'))

if __name__ == "__main__":
    server = Server()
    server.start()
