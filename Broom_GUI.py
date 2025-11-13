import rumps
import config
from Broom_Ollama import OllamaClient
from core import FileOrganizer, FolderOrganizer, UndoManager, RedoManager
import threading
import queue
import os
from AppKit import NSOpenPanel, NSFileHandlingPanelOKButton
import json
import base64
import tempfile

class BroomApp(rumps.App):
    def __init__(self):
        icon_path = self.setup_icon()
        super(BroomApp, self).__init__(config.APP_TITLE, icon=icon_path)
        self.ollama_client = OllamaClient(config.OLLAMA_MODEL)
        self.menu = [
            'Organize Files',
            'Organize Folders',
            None,
            'Undo Last Organization',
            'Redo Last Action',
        ]
        self.organize_queue = queue.Queue()
        self.organize_timer = rumps.Timer(self.process_queue, 1)
        self.organize_timer.start()
        self.thinking_window = None
        self.plan_window = None
        self.current_directory = None
        self.current_plan = None
        self.current_mode = None

    def setup_icon(self):
        """Decodes the icon and saves it to a temporary file."""
        try:
            icon_data = base64.b64decode(config.APP_ICON)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as fp:
                fp.write(icon_data)
                self.icon_path = fp.name
            return self.icon_path
        except Exception as e:
            print(f"Error setting up icon: {e}")
            return None

    def cleanup(self):
        """Remove the temporary icon file on exit."""
        if hasattr(self, 'icon_path') and os.path.exists(self.icon_path):
            os.remove(self.icon_path)

    def process_queue(self, _):
        """Process messages from the background thread."""
        try:
            message = self.organize_queue.get_nowait()
            if message['type'] == 'status':
                self.thinking_window.title = message['text']
            elif message['type'] == 'progress':
                self.thinking_window.pbar.value = message['value']
            elif message['type'] == 'thinking':
                self.thinking_window.text.insert_end(message['text'])
            elif message['type'] == 'plan':
                self.current_plan = message['plan']
                self.current_mode = message['mode']
                self.display_plan_window()
            elif message['type'] == 'error':
                rumps.alert(title="Error", message=message['text'])
            elif message['type'] == 'success':
                rumps.alert(title="Success!", message=message['text'])
            elif message['type'] == 'close':
                if self.thinking_window:
                    self.thinking_window.hide()

        except queue.Empty:
            return

    def select_directory(self):
        """Open a native macOS directory selection dialog."""
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseDirectories_(True)
        panel.setCanChooseFiles_(False)
        panel.setAllowsMultipleSelection_(False)

        if panel.runModal() == NSFileHandlingPanelOKButton:
            return panel.URLs()[0].path()
        return None

    def organization_thread(self, directory, mode):
        """The function that runs in the background thread."""
        try:
            self.organize_queue.put({'type': 'status', 'text': 'Starting...'})
            if mode == 'files':
                organizer = FileOrganizer(
                    directory=directory,
                    recursive=False,
                    ollama_client=self.ollama_client,
                    batch_size=config.BATCH_SIZE,
                    text_extensions=config.TEXT_EXTENSIONS,
                    max_content_length=config.MAX_CONTENT_LENGTH
                )
                file_index = organizer.index()
                if not file_index:
                    self.organize_queue.put({'type': 'error', 'text': 'No files found to organize.'})
                    return

                batches = [file_index[i:i + organizer.batch_size] for i in range(0, len(file_index), organizer.batch_size)]
                final_plan = {}
                self.organize_queue.put({'type': 'progress', 'value': 0})

                for i, batch in enumerate(batches):
                    self.organize_queue.put({'type': 'status', 'text': f"Processing Batch {i+1}/{len(batches)}"})
                    file_data_str = json.dumps(batch)
                    prompt = f"Task: Categorize files based on path, file_type, and content. Output ONLY JSON with one key 'organization_plan'. Data: {file_data_str}"

                    full_response_content = ""
                    for chunk in self.ollama_client.get_plan_stream(prompt):
                        self.organize_queue.put({'type': 'thinking', 'text': chunk})
                        full_response_content += chunk

                    try:
                        response_data = json.loads(full_response_content)
                        partial_plan = response_data.get("organization_plan", {})
                        for category, files in partial_plan.items():
                            final_plan.setdefault(category, []).extend([f for f in files if f not in final_plan.get(category, [])])
                    except json.JSONDecodeError:
                        self.organize_queue.put({'type': 'error', 'text': f"Could not decode AI response for batch {i+1}"})

                    self.organize_queue.put({'type': 'progress', 'value': (i+1)/len(batches) * 100})

                self.organize_queue.put({'type': 'plan', 'plan': final_plan, 'mode': 'files'})

            elif mode == 'folders':
                 organizer = FolderOrganizer(
                    directory=directory,
                    ollama_client=self.ollama_client
                )
                 folder_index = organizer.index()
                 if not folder_index:
                     self.organize_queue.put({'type': 'error', 'text': 'No folders found to organize.'})
                     return

                 folder_data_str = json.dumps(folder_index)
                 prompt = (f"Task: Group folders into parent categories. Rules: "
                  f"1. A group MUST contain 2 or more folders. "
                  f"2. A parent category's name MUST NOT be the same as any of the folders inside it. "
                  f"3. Ungroupable folders go into a special category named '_standalone'. "
                  f"4. Output ONLY JSON with a single key 'organization_plan'. Data: {folder_data_str}")

                 response_data = self.ollama_client.get_plan_sync(prompt)
                 self.organize_queue.put({'type': 'plan', 'plan': response_data.get("organization_plan", {}), 'mode': 'folders'})

        except Exception as e:
            self.organize_queue.put({'type': 'error', 'text': str(e)})
        finally:
            self.organize_queue.put({'type': 'close'})

    def display_plan_window(self):
        if self.thinking_window:
            self.thinking_window.hide()

        plan_text = ""
        if self.current_mode == 'files':
            for folder, items in sorted(self.current_plan.items()):
                paths = [item['path'] if isinstance(item, dict) else item for item in items]
                plan_text += f"📁 Create folder: '{folder}'\n"
                for path in sorted(paths)[:5]:
                    plan_text += f"    └── Move '{path}'\n"
                if len(paths) > 5:
                    plan_text += f"    └── and {len(paths) - 5} more...\n"
        else: # folders
            standalone = self.current_plan.pop('_standalone', [])
            for p_folder, s_folders in sorted(self.current_plan.items()):
                plan_text += f"📁 Create parent folder: '{p_folder}'\n"
                for s_folder in sorted(s_folders):
                    plan_text += f"    └── Move folder '{s_folder}' into it\n"
            if standalone:
                plan_text += f"\n👉 {len(standalone)} folders will be left as they are.\n"

        self.plan_window = rumps.Window(title="Proposed Organization Plan", ok="Execute", cancel="Cancel")
        self.plan_window.message.text = plan_text

        response = self.plan_window.run()
        if response.clicked: # Execute
            self.execute_plan()

    def execute_plan(self):
        if self.current_mode == 'files':
            organizer = FileOrganizer(
                directory=self.current_directory,
                recursive=False,
                ollama_client=self.ollama_client,
                batch_size=config.BATCH_SIZE,
                text_extensions=config.TEXT_EXTENSIONS,
                max_content_length=config.MAX_CONTENT_LENGTH
            )
            organizer.execute_plan(self.current_plan)
        else: # folders
            organizer = FolderOrganizer(
                directory=self.current_directory,
                ollama_client=self.ollama_client
            )
            organizer.execute_plan(self.current_plan)
        rumps.alert("Success!", "The organization plan has been executed.")


    def create_thinking_window(self):
        self.thinking_window = rumps.Window(title="Broom is Thinking...", cancel=True)
        self.thinking_window.pbar = rumps.ProgressBar(0, 100, 0)
        self.thinking_window.text = rumps.TextBox()
        self.thinking_window.add_widgets(self.thinking_window.pbar, self.thinking_window.text)
        self.thinking_window.show()


    @rumps.clicked('Organize Files')
    def organize_files(self, _):
        self.current_directory = self.select_directory()
        if self.current_directory:
            self.create_thinking_window()
            thread = threading.Thread(target=self.organization_thread, args=(self.current_directory, 'files'))
            thread.start()

    @rumps.clicked('Organize Folders')
    def organize_folders(self, _):
        self.current_directory = self.select_directory()
        if self.current_directory:
            self.create_thinking_window()
            thread = threading.Thread(target=self.organization_thread, args=(self.current_directory, 'folders'))
            thread.start()

    def undo_thread(self, directory):
        """The function that runs in the background thread for undo."""
        try:
            UndoManager.run(directory, no_confirm=True)
            self.organize_queue.put({'type': 'success', 'text': 'The last organization has been undone.'})
        except SystemExit as e:
            self.organize_queue.put({'type': 'error', 'text': str(e)})
        except Exception as e:
            self.organize_queue.put({'type': 'error', 'text': str(e)})

    @rumps.clicked('Undo Last Organization')
    def undo(self, _):
        self.current_directory = self.select_directory()
        if self.current_directory:
            response = rumps.alert(
                title="Undo Last Organization",
                message="Are you sure you want to undo the last organization? This cannot be undone.",
                ok="Undo",
                cancel="Cancel"
            )
            if response == 1:
                thread = threading.Thread(target=self.undo_thread, args=(self.current_directory,))
                thread.start()

    def redo_thread(self, directory):
        """The function that runs in the background thread for redo."""
        try:
            RedoManager.run(directory, no_confirm=True)
            self.organize_queue.put({'type': 'success', 'text': 'The last action has been redone.'})
        except SystemExit as e:
            self.organize_queue.put({'type': 'error', 'text': str(e)})
        except Exception as e:
            self.organize_queue.put({'type': 'error', 'text': str(e)})

    @rumps.clicked('Redo Last Action')
    def redo(self, _):
        self.current_directory = self.select_directory()
        if self.current_directory:
            response = rumps.alert(
                title="Redo Last Action",
                message="Are you sure you want to redo the last action? This will re-apply the last organization.",
                ok="Redo",
                cancel="Cancel"
            )
            if response == 1:
                thread = threading.Thread(target=self.redo_thread, args=(self.current_directory,))
                thread.start()

if __name__ == "__main__":
    app = BroomApp()
    try:
        app.run()
    finally:
        app.cleanup()
