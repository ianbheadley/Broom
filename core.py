import os
import sys
import json
import shutil
from typing import Dict, List, Any
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from utils import display_plan


class FileOrganizer:
    """
    Organizes files in a directory based on an AI-generated plan.
    """
    def __init__(self, directory: str, recursive: bool, ollama_client: 'OllamaClient', batch_size: int, text_extensions: list, max_content_length: int):
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
                if filename.startswith('.') or filename in [".broom_log.json", ".broom_undo.json", ".broom_redo.json"]:
                    continue

                filepath = os.path.join(root, filename)
                if not os.path.isfile(filepath):
                    continue

                relative_path = os.path.relpath(filepath, self.directory)
                file_ext = os.path.splitext(filename)[1].lower()

                # Improved file type detection: try to read all files as text by default,
                # and only classify as binary if it contains null bytes or is unreadable.
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content_sample = f.read(self.max_content_length)

                    # Heuristic: If a file contains a null byte, it's likely binary.
                    # We make an exception for known text types that might contain them.
                    if '\x00' in content_sample and file_ext not in self.text_extensions:
                        content = "Binary file."
                    else:
                        content = content_sample if content_sample else "<Empty file>"
                except (IOError, OSError):
                    content = "Binary file." # Can't be opened in text mode.
                except Exception:
                    content = "<Unreadable>" # Other unexpected errors.

                files_index.append({"path": relative_path, "file_type": file_ext, "content_summary": content})

            if not self.recursive:
                break


        print(f"✅ Indexed {len(files_index)} files.")
        return files_index

    def organize(self, dry_run: bool, skip_confirmation: bool, stream: bool = False):
        """
        Runs the file organization process.
        Args:
            dry_run (bool): If True, shows the plan without moving anything.
            skip_confirmation (bool): If True, skips the confirmation prompt.
            stream (bool): If True, streams the AI response in real-time.
        """
        file_index = self.index()
        if not file_index:
            sys.exit("No files found to organize.")

        batches = [file_index[i:i + self.batch_size] for i in range(0, len(file_index), self.batch_size)]
        final_plan = {}

        if stream:
            print(f"\n➡️  Step 2: Analyzing files in {len(batches)} batches sequentially (streaming)...")
            for i, batch in enumerate(tqdm(batches, desc="Processing Batches")):
                file_data_str = json.dumps(batch)
                prompt = f"Task: Categorize files based on path, file_type, and content. Output ONLY JSON with one key 'organization_plan'. Data: {file_data_str}"

                print(f"\n--- Batch {i+1}/{len(batches)} ---")
                full_response_content = ""
                for chunk in self.ollama_client.get_plan_stream(prompt):
                    print(chunk, end='', flush=True)
                    full_response_content += chunk
                print("\n")

                try:
                    response_data = json.loads(full_response_content)
                    partial_plan = response_data.get("organization_plan", {})
                    for category, files in partial_plan.items():
                        final_plan.setdefault(category, []).extend([f for f in files if f not in final_plan.get(category, [])])
                except json.JSONDecodeError:
                    print(f"\n⚠️ Warning: Could not decode AI response for batch {i+1}")

        else:
            print(f"\n➡️  Step 2: Analyzing files in {len(batches)} batches concurrently...")
            with ThreadPoolExecutor() as executor:
                futures = []
                for i, batch in enumerate(batches):
                    file_data_str = json.dumps(batch)
                    prompt = f"Task: Categorize files based on path, file_type, and content. Output ONLY JSON with one key 'organization_plan'. Data: {file_data_str}"
                    futures.append(executor.submit(self.ollama_client.get_file_batch_plan_sync, prompt, i + 1))

                results = [future.result() for future in tqdm(futures, desc="Processing Batches")]

            for response in results:
                if response:
                    content = response.get('message', {}).get('content', '{}')
                    try:
                        partial_plan = json.loads(content).get("organization_plan", {})
                        for category, files in partial_plan.items():
                            final_plan.setdefault(category, []).extend([f for f in files if f not in final_plan.get(category, [])])
                    except json.JSONDecodeError:
                        print(f"⚠️ Warning: Could not decode AI response: {content}")

        display_plan(final_plan, "files", self.recursive)
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
    def __init__(self, directory: str, ollama_client: 'OllamaClient'):
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

    def organize(self, dry_run: bool, skip_confirmation: bool, stream: bool = False):
        """
        Runs the folder organization process.
        Args:
            dry_run (bool): If True, shows the plan without moving anything.
            skip_confirmation (bool): If True, skips the confirmation prompt.
            stream (bool): If True, streams the AI response in real-time.
        """
        folder_index = self.index()
        if not folder_index:
            sys.exit("No folders found to organize.")

        print("\n➡️  Step 2: Analyzing folder structure...")
        folder_data_str = json.dumps(folder_index)
        prompt = (f"Task: Group folders into parent categories. Rules: "
                  f"1. A group MUST contain 2 or more folders. "
                  f"2. A parent category's name MUST NOT be the same as any of the folders inside it. "
                  f"3. Ungroupable folders go into a special category named '_standalone'. "
                  f"4. Output ONLY JSON with a single key 'organization_plan'. Data: {folder_data_str}")

        print("   - Asking AI for a folder organization plan...")

        if stream:
            print("   - Streaming AI response... (raw JSON will be printed below)")
            full_response_content = ""
            for chunk in self.ollama_client.get_plan_stream(prompt):
                print(chunk, end='', flush=True)
                full_response_content += chunk
            print("\n") # Newline after stream finishes
            try:
                response_data = json.loads(full_response_content)
            except json.JSONDecodeError:
                sys.exit("\n❌ Could not decode the streamed JSON response from the AI.")
        else:
            response_data = self.ollama_client.get_plan_sync(prompt)

        if not response_data or "organization_plan" not in response_data:
            sys.exit("❌ Could not get a valid organization plan from the AI.")

        raw_plan = response_data.get("organization_plan", {})
        final_plan = {}
        standalone_folders = raw_plan.get('_standalone', [])
        groups_to_process = {k: v for k, v in raw_plan.items() if k != '_standalone'}

        for parent, children in groups_to_process.items():
            valid_children = [child for child in children if child != parent]
            if len(valid_children) >= 2:
                final_plan[parent] = valid_children
            else:
                standalone_folders.extend(valid_children)

        if standalone_folders:
            final_plan['_standalone'] = sorted(list(set(standalone_folders)))

        display_plan(final_plan, "folders")
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
    def run(cls, directory: str, no_confirm: bool = False):
        """
        Runs the undo process.
        Args:
            directory (str): The directory where the undo operation will be performed.
            no_confirm (bool): If True, bypasses the confirmation prompt.
        """
        undo_path = os.path.join(directory, cls.UNDO_FILENAME)
        if not os.path.exists(undo_path):
            sys.exit(f"❌ No undo log found at '{undo_path}'. Cannot undo.")

        with open(undo_path, 'r') as f:
            undo_actions = json.load(f)

        if not no_confirm:
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

        os.rename(undo_path, os.path.join(directory, RedoManager.REDO_FILENAME))
        print("\n✅ Undo complete.")

class RedoManager:
    """
    Manages the redo functionality for file and folder organization.
    """
    REDO_FILENAME = ".broom_redo.json"

    @classmethod
    def run(cls, directory: str, no_confirm: bool = False):
        """
        Runs the redo process.
        Args:
            directory (str): The directory where the redo operation will be performed.
            no_confirm (bool): If True, bypasses the confirmation prompt.
        """
        redo_path = os.path.join(directory, cls.REDO_FILENAME)
        if not os.path.exists(redo_path):
            sys.exit(f"❌ No redo log found at '{redo_path}'. Cannot redo.")

        with open(redo_path, 'r') as f:
            redo_actions = json.load(f)

        if not no_confirm:
            print(f"↪️  Found {len(redo_actions)} actions to re-apply. This will restore the state before the last undo.")
            if input("Proceed with redo? (y/N): ").lower().strip() != 'y':
                sys.exit("Redo aborted by user.")

        for action in tqdm(redo_actions, total=len(redo_actions), desc="Redoing moves"):
            source = os.path.join(directory, action['source'])
            dest = os.path.join(directory, action['dest'])

            os.makedirs(os.path.dirname(dest), exist_ok=True)

            if os.path.exists(source):
                shutil.move(source, dest)

        os.rename(redo_path, os.path.join(directory, UndoManager.UNDO_FILENAME))
        print("\n✅ Redo complete.")
