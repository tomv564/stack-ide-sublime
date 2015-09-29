import uuid

def status_message(msg):
    pass

def set_timeout_async(fn, delay):
    pass


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

def create_window(path):
    global fake_windows
    fake_windows.append(FakeWindow(path))

def destroy_windows():
    global fake_windows
    fake_windows = []

def windows():
    global fake_windows
    return fake_windows

class Region():

    def __init__(self, start, end):
        self.start = start
        self.end = end



