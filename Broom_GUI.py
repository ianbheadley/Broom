import os
import sys
import rumps
import threading
import tkinter as tk
from tkinter import filedialog
from core import OllamaClient, FileOrganizer, FolderOrganizer
import config

class BroomApp(rumps.App):
    def __init__(self):
        super(BroomApp, self).__init__("Broom", icon=None, quit_button=None)
        self.mode_button = rumps.MenuItem("Mode: Files", callback=self.toggle_mode)
        self.organize_button = rumps.MenuItem("Organize Directory", callback=self.organize_directory)
        self.quit_button = rumps.MenuItem("Quit", callback=rumps.quit_application)
        self.menu = [self.mode_button, self.organize_button, None, self.quit_button]
        self.mode = "files"
        self.organizing = False

    def toggle_mode(self, sender):
        if self.mode == "files":
            self.mode = "folders"
            sender.title = "Mode: Folders"
        else:
            self.mode = "files"
            sender.title = "Mode: Files"

    def select_directory(self):
        root = tk.Tk()
        root.withdraw()
        directory = filedialog.askdirectory(title="Select a directory to organize")
        root.destroy()
        return directory

    def organize_directory(self, sender):
        if self.organizing:
            rumps.alert("Broom", "An organization task is already in progress.")
            return

        directory = self.select_directory()
        if directory:
            thread = threading.Thread(target=self.organize_thread, args=(directory,))
            thread.start()

    def organize_thread(self, directory):
        self.organizing = True
        self.organize_button.title = "Organizing..."
        try:
            ollama_client = OllamaClient(config.DEFAULT_OLLAMA_MODEL)
            if not ollama_client.check_connection():
                rumps.alert("Broom", "Could not connect to Ollama. Is the application running?")
                return

            rumps.notification("Broom", "Organization Started", f"Organizing {self.mode} in {directory}")

            if self.mode == 'files':
                # For the GUI, let's assume recursive is false for simplicity.
                organizer = FileOrganizer(directory, recursive=False, ollama_client=ollama_client)
                # In the GUI, we'll skip confirmation and stream is not applicable in the same way.
                organizer.organize(dry_run=False, skip_confirmation=True, stream=False)
            else:
                organizer = FolderOrganizer(directory, ollama_client=ollama_client)
                organizer.organize(dry_run=False, skip_confirmation=True, stream=False)

            rumps.notification("Broom", "Organization Complete", "The directory has been organized.")
        except Exception as e:
            rumps.alert("Broom", f"An error occurred: {e}")
        finally:
            self.organizing = False
            self.organize_button.title = "Organize Directory"

if __name__ == "__main__":
    try:
        app = BroomApp()
        app.run()
    except Exception as e:
        print(f"Could not start GUI: {e}", file=sys.stderr)
        print("Please note: This GUI is designed for macOS and may require special setup to run.", file=sys.stderr)
        # On macOS, you might need to run python with 'pythonw' or a framework build.
        sys.exit(1)