import socket
from pynput import keyboard

class PlayerClient:
    def __init__(self, username):
        self.host = 'localhost'
        self.port = 9999
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.username = username
        print("Player client created for user {}".format(self.username))

    def connect(self):
        self.client.connect((self.host, self.port))
        self.send(self.username)  # send username to server upon connection
        print("Connected to server on {}:{}".format(self.host, self.port))

    def send(self, message):
        self.client.send(message.encode('utf-8'))

    def buzz(self):
        self.send("BUZZ")
        print("Buzzed")

if __name__ == "__main__":
    username = input('Enter your username: ')
    client = PlayerClient(username)
    client.connect()

    def on_press(key):
        if key == keyboard.Key.enter or key == keyboard.Key.space:
            client.buzz()

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    print("Listening for key presses")
    while True:
        pass  # Keep the program running.
