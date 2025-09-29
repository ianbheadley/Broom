#!/usr/bin/env python3
import os
import sys
import argparse
import json
import shutil
from typing import Dict, List, Any
import asyncio
import ollama
from tqdm.asyncio import tqdm as async_tqdm
from tqdm import tqdm

class OllamaClient:
    """
    A client for interacting with the Ollama API.
    This class handles the communication with the Ollama model, including error handling.
    """
    def __init__(self, model: str):
        """
        Initializes the OllamaClient.
        Args:
            model (str): The name of the Ollama model to use.
        """
        self.model = model

    def check_connection(self):
        """
        Checks if the Ollama service is reachable.
        Returns:
            bool: True if the service is running, False otherwise.
        """
        try:
            ollama.list()
            return True
        except Exception as e:
            print(f"\n❌ Error: Could not connect to Ollama. Is the application running?\n   (Details: {e})")
            return False

    async def get_plan_async(self, prompt: str, batch_num: int) -> dict:
        """
        Asynchronously gets an organization plan from the Ollama model.
        Args:
            prompt (str): The prompt to send to the model.
            batch_num (int): The batch number for logging purposes.
        Returns:
            dict: The JSON response from the model.
        """
        try:
            response = await asyncio.to_thread(
                ollama.chat,
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.0},
                format='json'
            )
            return response
        except Exception as e:
            print(f"\n❌ Error in AI batch {batch_num}: {e}")
            return {}

    def get_plan_sync(self, prompt: str) -> dict:
        """
        Synchronously gets an organization plan from the Ollama model.
        Args:
            prompt (str): The prompt to send to the model.
        Returns:
            dict: The JSON response from the model.
        """
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.0},
                format='json'
            )
            return json.loads(response['message']['content'])
        except Exception as e:
            print(f"\n❌ An AI communication error occurred: {e}")
            return None


class FileOrganizer:
    """
    Organizes files in a directory based on an AI-generated plan.
    """
    def __init__(self, directory: str, recursive: bool, ollama_client: OllamaClient, batch_size: int, text_extensions: list, max_content_length: int):
        self.directory = directory
        self.recursive = recursive
        self.ollama_client = ollama_client
        self.batch_size = batch_size
        self.text_extensions = text_extensions
        self.max_content_length = max_content_length

    def index(self) -> List[Dict[str, str]]:
        """
        Indexes files in the specified directory.
        Returns:
            List[Dict[str, str]]: A list of dictionaries, each representing a file.
        """
        print(f"➡️  Step 1: Indexing all files {'recursively' if self.recursive else ''} in '{self.directory}'...")
        files_index = []

        iterator = os.walk(self.directory) if self.recursive else [(self.directory, [], os.listdir(self.directory))]

        for root, _, filenames in iterator:
            for filename in filenames:
                if filename.startswith('.') or filename in [".broom_log.json", ".broom_undo.json"]:
                    continue

                filepath = os.path.join(root, filename)
                if not os.path.isfile(filepath):
                    continue

                relative_path = os.path.relpath(filepath, self.directory)
                file_ext = os.path.splitext(filename)[1].lower()
                content = ""
                if file_ext in self.text_extensions:
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read(self.max_content_length)
                    except Exception:
                        content = "<Unreadable>"
                else:
                    content = "Binary file."

                files_index.append({"path": relative_path, "file_type": file_ext, "content_summary": content})

            if not self.recursive:
                break


        print(f"✅ Indexed {len(files_index)} files.")
        return files_index

    async def organize(self, dry_run: bool, skip_confirmation: bool):
        """
        Runs the file organization process.
        Args:
            dry_run (bool): If True, shows the plan without moving anything.
            skip_confirmation (bool): If True, skips the confirmation prompt.
        """
        file_index = self.index()
        if not file_index:
            sys.exit("No files found to organize.")

        batches = [file_index[i:i + self.batch_size] for i in range(0, len(file_index), self.batch_size)]
        print(f"\n➡️  Step 2: Analyzing files in {len(batches)} batches concurrently...")

        tasks = []
        for i, batch in enumerate(batches):
            file_data_str = json.dumps(batch)
            prompt = f"Task: Categorize files based on path, file_type, and content. Output ONLY JSON with one key 'organization_plan'. Data: {file_data_str}"
            tasks.append(self.ollama_client.get_plan_async(prompt, i + 1))

        final_plan = {}
        results = await async_tqdm.gather(*tasks, desc="Processing Batches")
        for response in results:
            content = response.get('message', {}).get('content', '{}')
            try:
                partial_plan = json.loads(content).get("organization_plan", {})
                for category, files in partial_plan.items():
                    final_plan.setdefault(category, []).extend([f for f in files if f not in final_plan.get(category, [])])
            except json.JSONDecodeError:
                print(f"⚠️ Warning: Could not decode AI response: {content}")


        Broom.display_plan(final_plan, "files", self.recursive)
        if not dry_run and (skip_confirmation or input("Apply this plan? (y/N): ").lower().strip() == 'y'):
            self.execute_plan(final_plan)
        else:
            if not dry_run:
                print("Aborted by user.")
            print("\n🏁 This was a DRY RUN. No items were moved.")

    def execute_plan(self, plan: Dict[str, List[str]]):
        """
        Executes the file organization plan.
        Args:
            plan (Dict[str, List[str]]): The organization plan.
        """
        print("\n➡️  Step 3: Executing file organization plan...")
        undo_actions = []
        item_count = sum(len(items) for items in plan.values())

        with tqdm(total=item_count, desc="Moving files") as pbar:
            for folder, items in plan.items():
                target_dir_path = os.path.join(self.directory, folder)
                os.makedirs(target_dir_path, exist_ok=True)
                for item in items:
                    source_rel_path = item['path'] if isinstance(item, dict) else item
                    source_abs_path = os.path.join(self.directory, source_rel_path)

                    dest_rel_path = os.path.join(folder, os.path.basename(source_rel_path))
                    dest_abs_path = os.path.join(self.directory, dest_rel_path)

                    if os.path.exists(source_abs_path):
                        undo_actions.append({"source": source_rel_path, "dest": dest_rel_path})
                        shutil.move(source_abs_path, dest_abs_path)
                    pbar.update(1)

        if undo_actions:
            UndoManager.save_undo_log(self.directory, undo_actions)


class FolderOrganizer:
    """
    Organizes folders in a directory based on an AI-generated plan.
    """
    def __init__(self, directory: str, ollama_client: OllamaClient):
        self.directory = directory
        self.ollama_client = ollama_client

    def index(self) -> List[Dict[str, Any]]:
        """
        Indexes folders in the specified directory.
        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a folder.
        """
        print(f"➡️  Step 1: Indexing all folders in '{self.directory}'...")
        folder_index = []
        for item in os.listdir(self.directory):
            if os.path.isdir(os.path.join(self.directory, item)) and not item.startswith('.'):
                folder_index.append({"folder_name": item})
        print(f"✅ Indexed {len(folder_index)} folders.")
        return folder_index

    def organize(self, dry_run: bool, skip_confirmation: bool):
        """
        Runs the folder organization process.
        Args:
            dry_run (bool): If True, shows the plan without moving anything.
            skip_confirmation (bool): If True, skips the confirmation prompt.
        """
        folder_index = self.index()
        if not folder_index:
            sys.exit("No folders found to organize.")

        print("\n➡️  Step 2: Analyzing folder structure...")
        folder_data_str = json.dumps(folder_index)
        prompt = f"Task: Group folders. Rules: Group MUST contain >= 2 folders. Ungroupable folders go into '_standalone'. Output ONLY JSON with 'organization_plan' key. Data: {folder_data_str}"
        print("   - Asking AI for a folder organization plan...")
        response_data = self.ollama_client.get_plan_sync(prompt)

        if not response_data or "organization_plan" not in response_data:
            sys.exit("❌ Could not get a valid organization plan from the AI.")

        final_plan = response_data["organization_plan"]
        Broom.display_plan(final_plan, "folders")
        if not dry_run and (skip_confirmation or input("Apply this plan? (y/N): ").lower().strip() == 'y'):
            self.execute_plan(final_plan)
        else:
            if not dry_run:
                print("Aborted by user.")
            print("\n🏁 This was a DRY RUN. No items were moved.")

    def execute_plan(self, plan: Dict[str, List[str]]):
        """
        Executes the folder organization plan.
        Args:
            plan (Dict[str, List[str]]): The organization plan.
        """
        print("\n➡️  Step 3: Executing folder organization plan...")
        undo_actions = []
        item_count = sum(len(items) for items in plan.values())

        with tqdm(total=item_count, desc="Moving folders") as pbar:
            for p_folder, s_folders in plan.items():
                if p_folder == '_standalone':
                    pbar.update(len(s_folders))
                    continue
                target_dir = os.path.join(self.directory, p_folder)
                os.makedirs(target_dir, exist_ok=True)
                for s_folder in s_folders:
                    if p_folder == s_folder:
                        pbar.update(1)
                        continue
                    source_path = os.path.join(self.directory, s_folder)
                    dest_path = os.path.join(target_dir, s_folder)
                    if os.path.isdir(source_path):
                        undo_actions.append({"source": s_folder, "dest": os.path.join(p_folder, s_folder)})
                        shutil.move(source_path, dest_path)
                    pbar.update(1)

        if undo_actions:
            UndoManager.save_undo_log(self.directory, undo_actions)


class UndoManager:
    """
    Manages the undo functionality for file and folder organization.
    """
    UNDO_FILENAME = ".broom_undo.json"

    @classmethod
    def save_undo_log(cls, directory: str, actions: List[Dict[str, str]]):
        """
        Saves the undo log to a file.
        Args:
            directory (str): The directory where the undo log will be saved.
            actions (List[Dict[str, str]]): A list of actions to be saved.
        """
        with open(os.path.join(directory, cls.UNDO_FILENAME), 'w') as f:
            json.dump(actions, f, indent=2)
        print(f"\n📝 Undo log saved. To reverse this action, run with the --undo flag.")

    @classmethod
    def run(cls, directory: str):
        """
        Runs the undo process.
        Args:
            directory (str): The directory where the undo operation will be performed.
        """
        undo_path = os.path.join(directory, cls.UNDO_FILENAME)
        if not os.path.exists(undo_path):
            sys.exit(f"❌ No undo log found at '{undo_path}'. Cannot undo.")

        with open(undo_path, 'r') as f:
            undo_actions = json.load(f)

        print(f"↩️  Found {len(undo_actions)} actions to reverse. This will restore the state before the last organization.")
        if input("Proceed with undo? (y/N): ").lower().strip() != 'y':
            sys.exit("Undo aborted by user.")

        for action in tqdm(reversed(undo_actions), total=len(undo_actions), desc="Undoing moves"):
            source = os.path.join(directory, action['dest'])
            dest = os.path.join(directory, action['source'])

            os.makedirs(os.path.dirname(dest), exist_ok=True)

            if os.path.exists(source):
                shutil.move(source, dest)

        for folder in {os.path.dirname(action['dest']) for action in undo_actions}:
            folder_path = os.path.join(directory, folder)
            if os.path.exists(folder_path) and not os.listdir(folder_path):
                try:
                    os.rmdir(folder_path)
                except OSError as e:
                    print(f"⚠️ Warning: Could not remove directory {folder_path}: {e}")

        os.remove(undo_path)
        print("\n✅ Undo complete.")


class Broom:
    """
    An AI-powered file and folder organizer.
    """
    def __init__(self):
        self.config = {
            'OLLAMA_MODEL': 'gemma3:12b',
            'MAX_CONTENT_LENGTH': 1024,
            'TEXT_EXTENSIONS': [
                '.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv',
                '.sh', '.yaml', '.yml', '.ini', '.log', '.rst', '.tex', '.rtf'
            ],
            'BATCH_SIZE': 30,
        }
        self.parser = self._create_parser()

    def _create_parser(self):
        """
        Creates the command-line argument parser.
        Returns:
            argparse.ArgumentParser: The argument parser.
        """
        parser = argparse.ArgumentParser(description="Broom: An AI-powered file and folder organizer.")
        parser.add_argument("directory", nargs='?', default=None, help="The directory to organize. Required unless using --undo.")
        parser.add_argument("--mode", choices=['files', 'folders'], default='files', help="Organize 'files' or group 'folders'.")
        parser.add_argument("--recursive", action="store_true", help="Organize files in all subdirectories (files mode only).")
        parser.add_argument("--undo", action="store_true", help="Undo the last organization in the specified directory.")
        parser.add_argument("--dry-run", action="store_true", help="Show the plan without moving anything.")
        parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation and execute the plan.")
        return parser

    @staticmethod
    def display_plan(plan: Dict[str, List[str]], mode: str, recursive: bool = False):
        """
        Displays the organization plan to the user.
        Args:
            plan (Dict[str, List[str]]): The organization plan.
            mode (str): The organization mode ('files' or 'folders').
            recursive (bool): Whether the file indexing was recursive.
        """
        print("\n✨ Here is the final proposed organization plan:")
        print("─" * 40)
        if mode == 'files':
            for folder, items in sorted(plan.items()):
                paths = [item['path'] if isinstance(item, dict) else item for item in items]
                print(f"📁 Create folder: '{folder}'")
                for path in sorted(paths)[:5]:
                    print(f"    └── Move '{path}'")
                if len(paths) > 5:
                    print(f"    └── and {len(paths) - 5} more...")
        else:
            standalone = plan.pop('_standalone', [])
            for p_folder, s_folders in sorted(plan.items()):
                print(f"📁 Create parent folder: '{p_folder}'")
                for s_folder in sorted(s_folders):
                    print(f"    └── Move folder '{s_folder}' into it")
            if standalone:
                print(f"\n👉 {len(standalone)} folders will be left as they are.")
        print("─" * 40)

    async def run(self):
        """
        Runs the main application logic.
        """
        args = self.parser.parse_args()

        if not any(arg in ['--undo', '-h', '--help'] for arg in sys.argv):
            ollama_client = OllamaClient(self.config['OLLAMA_MODEL'])
            if not ollama_client.check_connection():
                sys.exit(1)
        else:
            ollama_client = None

        if args.undo:
            if not args.directory:
                sys.exit("❌ Error: Please specify the directory where you want to run the undo operation.")
            target_directory = os.path.expanduser(args.directory)
            UndoManager.run(target_directory)
            return

        if not args.directory:
            sys.exit("❌ Error: Please specify a directory to organize.")

        target_directory = os.path.expanduser(args.directory)
        if not os.path.isdir(target_directory):
            sys.exit(f"❌ Error: Directory '{target_directory}' not found.")

        if args.mode == 'files':
            organizer = FileOrganizer(
                directory=target_directory,
                recursive=args.recursive,
                ollama_client=ollama_client,
                batch_size=self.config['BATCH_SIZE'],
                text_extensions=self.config['TEXT_EXTENSIONS'],
                max_content_length=self.config['MAX_CONTENT_LENGTH']
            )
            await organizer.organize(args.dry_run, args.yes)
        else:
            if args.recursive:
                print("⚠️  Warning: Recursive mode is only supported for file organization. Running on top-level folders only.")
            organizer = FolderOrganizer(
                directory=target_directory,
                ollama_client=ollama_client
            )
            organizer.organize(args.dry_run, args.yes)


if __name__ == "__main__":
    broom = Broom()
    asyncio.run(broom.run())