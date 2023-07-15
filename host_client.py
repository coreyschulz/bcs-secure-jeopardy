import socket
from pynput import keyboard

class HostClient:
    def __init__(self):
        self.host = 'localhost'
        self.port = 9999
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.locked = False
        print("Host client created")

    def connect(self):
        self.client.connect((self.host, self.port))
        print("Connected to server on {}:{}".format(self.host, self.port))

    def send(self, message):
        self.client.send(message.encode('utf-8'))

    def toggle_buzzer(self):
        if self.locked:
            self.send("UNLOCK")
            print("Unlocked the buzzer")
        else:
            self.send("LOCK")
            print("Locked the buzzer")
        self.locked = not self.locked

    def clear_buzzes(self):
        self.send("CLEAR")
        print("Cleared buzzes")
        # receive and print the list of buzzes
        buzzes = self.client.recv(1024).decode('utf-8')
        print("Order of buzzes: {}".format(buzzes))

if __name__ == "__main__":
    client = HostClient()
    client.connect()

    def on_press(key):
        try:
            if key == keyboard.Key.enter or key == keyboard.Key.space:
                client.toggle_buzzer()
            elif key.char == 'c':
                client.clear_buzzes()  # press 'c' to clear buzzes
        except AttributeError:
            pass

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    print("Listening for key presses")
    while True:
        pass  # Keep the program running.
