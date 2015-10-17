import uuid

current_status = ""

def status_message(msg):
    global current_status
    current_status = msg

def set_timeout_async(fn, delay):
    pass

def set_timeout(fn, delay):
    fn()

def load_settings():
    pass


# class FakeBackend():



class FakeWindow():

    def __init__(self, folder):
        self._folders = [folder]
        self._id = uuid.uuid4()

    def id(self):
        return self._id

    def folders(self):
        return self._folders

fake_windows = []

ENCODED_POSITION = 1 #flag used for window.open_file

clipboard = None

def create_window(path):
    global fake_windows
    fake_windows.append(FakeWindow(path))

def destroy_windows():
    global fake_windows
    fake_windows = []

def set_clipboard(text):
    global clipboard
    clipboard = text

def windows():
    global fake_windows
    return fake_windows

class Region():

    def __init__(self, start, end):
        self.start = start
        self.end = end



