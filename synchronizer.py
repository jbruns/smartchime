class Synchronizer():
    def __init__(self):
        self.synchronized = {}

    def busy(self, task):
        self.synchronized[id(task)] = False

    def ready(self, task):
        self.synchronized[id(task)] = True

    def is_synchronized(self):
        for task in self.synchronized.items():
            if task[1] is False:
                return False
        return True