import os
import sys
import json
import shutil
from typing import Dict, List, Any
from concurrent.futures import ThreadPoolExecutor
import ollama
from tqdm import tqdm
import config
from utils import UndoManager, display_plan

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

    def get_file_batch_plan_sync(self, prompt: str, batch_num: int) -> dict:
        """
        Synchronously gets an organization plan for a file batch from the Ollama model.
        Args:
            prompt (str): The prompt to send to the model.
            batch_num (int): The batch number for logging purposes.
        Returns:
            dict: The raw JSON response from the model.
        """
        try:
            response = ollama.chat(
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

    def get_plan_stream(self, prompt: str):
        """
        Gets an organization plan from the Ollama model, streaming the response.
        Args:
            prompt (str): The prompt to send to the model.
        Yields:
            str: The content chunks of the JSON response.
        """
        try:
            response_stream = ollama.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.0},
                format='json',
                stream=True
            )
            for chunk in response_stream:
                yield chunk['message']['content']
        except Exception as e:
            print(f"\n❌ An AI communication error occurred during streaming: {e}")


class FileOrganizer:
    """
    Organizes files in a directory based on an AI-generated plan.
    """
    def __init__(self, directory: str, recursive: bool, ollama_client: OllamaClient):
        self.directory = directory
        self.recursive = recursive
        self.ollama_client = ollama_client
        self.batch_size = config.BATCH_SIZE
        self.text_extensions = config.TEXT_EXTENSIONS
        self.max_content_length = config.MAX_CONTENT_LENGTH

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
                if filename.startswith('.') or filename in [".broom_log.json", config.UNDO_FILENAME]:
                    continue

                filepath = os.path.join(root, filename)
                if not os.path.isfile(filepath):
                    continue

                relative_path = os.path.relpath(filepath, self.directory)
                file_ext = os.path.splitext(filename)[1].lower()

                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content_sample = f.read(self.max_content_length)

                    if '\x00' in content_sample and file_ext not in self.text_extensions:
                        content = "Binary file."
                    else:
                        content = content_sample if content_sample else "<Empty file>"
                except (IOError, OSError):
                    content = "Binary file."
                except Exception:
                    content = "<Unreadable>"

                files_index.append({"path": relative_path, "file_type": file_ext, "content_summary": content})

            if not self.recursive:
                break

        print(f"✅ Indexed {len(files_index)} files.")
        return files_index

    def organize(self, dry_run: bool, skip_confirmation: bool, stream: bool = False):
        """
        Runs the file organization process.
        """
        file_index = self.index()
        if not file_index:
            print("No files found to organize.")
            return

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

        display_plan(final_plan, "files")
        if not dry_run and (skip_confirmation or input("Apply this plan? (y/N): ").lower().strip() == 'y'):
            self.execute_plan(final_plan)
        else:
            if not dry_run:
                print("Aborted by user.")
            print("\n🏁 This was a DRY RUN. No items were moved.")

    def execute_plan(self, plan: Dict[str, List[str]]):
        """
        Executes the file organization plan.
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
        """
        folder_index = self.index()
        if not folder_index:
            print("No folders found to organize.")
            return

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
            print("\n")
            try:
                response_data = json.loads(full_response_content)
            except json.JSONDecodeError:
                print("\n❌ Could not decode the streamed JSON response from the AI.")
                return
        else:
            response_data = self.ollama_client.get_plan_sync(prompt)

        if not response_data or "organization_plan" not in response_data:
            print("❌ Could not get a valid organization plan from the AI.")
            return

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