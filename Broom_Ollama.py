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

# --- CONFIGURATION ---
OLLAMA_MODEL = 'gemma3:12b'
MAX_CONTENT_LENGTH = 1024
TEXT_EXTENSIONS = [
    '.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv',
    '.sh', '.yaml', '.yml', '.ini', '.log', '.rst', '.tex', '.rtf'
]
BATCH_SIZE = 30
LOG_FILENAME = ".broom_log.json" # Hidden by default
UNDO_FILENAME = ".broom_undo.json" # Hidden by default

def check_ollama_is_running():
    """Checks if the Ollama service is reachable."""
    try:
        ollama.list()
        return True
    except Exception as e:
        print(f"\n❌ Error: Could not connect to Ollama. Is the application running?\n   (Details: {e})")
        return False

# --- CORE ASYNC FUNCTIONS ---

async def get_plan_from_llm_async(session, model: str, prompt: str, batch_num: int) -> dict:
    """Asynchronously gets an organization plan from the Ollama model."""
    try:
        # NOTE: ollama-python library isn't natively async, this simulates concurrency.
        # For true async with network I/O, a library like aiohttp would be used.
        # However, this structure allows for concurrent processing logic.
        response = await asyncio.to_thread(
            ollama.chat,
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.0},
            format='json'
        )
        return response
    except Exception as e:
        print(f"\n❌ Error in AI batch {batch_num}: {e}")
        return {}

# --- FILE ORGANIZATION MODE ---

def index_files(directory: str, recursive: bool) -> List[Dict[str, str]]:
    print(f"➡️  Step 1: Indexing all files {'recursively' if recursive else ''} in '{directory}'...")
    files_index = []
    
    if recursive:
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                if filename.startswith('.') or filename in [LOG_FILENAME, UNDO_FILENAME]:
                    continue
                filepath = os.path.join(root, filename)
                relative_path = os.path.relpath(filepath, directory)
                file_ext = os.path.splitext(filename)[1].lower()
                content = ""
                if file_ext in TEXT_EXTENSIONS:
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read(MAX_CONTENT_LENGTH)
                    except Exception: content = "<Unreadable>"
                else: content = "Binary file."
                files_index.append({"path": relative_path, "file_type": file_ext, "content_summary": content})
    else:
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if not os.path.isfile(filepath) or filename.startswith('.') or filename in [LOG_FILENAME, UNDO_FILENAME]:
                continue
            file_ext = os.path.splitext(filename)[1].lower()
            content = ""
            if file_ext in TEXT_EXTENSIONS:
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(MAX_CONTENT_LENGTH)
                except Exception: content = "<Unreadable>"
            else: content = "Binary file."
            files_index.append({"path": filename, "file_type": file_ext, "content_summary": content})

    print(f"✅ Indexed {len(files_index)} files.")
    return files_index

async def run_file_organization(directory: str, args: argparse.Namespace):
    file_index = index_files(directory, args.recursive)
    if not file_index: sys.exit("No files found to organize.")
    
    batches = [file_index[i:i + BATCH_SIZE] for i in range(0, len(file_index), BATCH_SIZE)]
    print(f"\n➡️  Step 2: Analyzing files in {len(batches)} batches concurrently...")

    tasks = []
    existing_categories = [] # This simplistic approach to context is less effective with async
    for i, batch in enumerate(batches):
        file_data_str = json.dumps(batch)
        prompt = f"Task: Categorize files based on path, file_type, and content. Output ONLY JSON with one key 'organization_plan'. Data: {file_data_str}"
        tasks.append(get_plan_from_llm_async(None, OLLAMA_MODEL, prompt, i + 1))

    final_plan = {}
    results = await async_tqdm.gather(*tasks, desc="Processing Batches")
    for response in results:
        partial_plan = json.loads(response.get('message', {}).get('content', '{}')).get("organization_plan", {})
        for category, files in partial_plan.items():
            final_plan.setdefault(category, []).extend([f for f in files if f not in final_plan.get(category, [])])
    
    display_plan(final_plan, "files")
    if not args.dry_run and (args.yes or input("Apply this plan? (y/N): ").lower().strip() == 'y'):
        execute_plan(directory, final_plan, "files")
    else:
        if not args.dry_run: print("Aborted by user.")
        print("\n🏁 This was a DRY RUN. No items were moved.")

# --- FOLDER ORGANIZATION MODE ---
# Note: Folder mode is less suited for recursion and is kept simple.

def index_folders(directory: str) -> List[Dict[str, Any]]:
    print(f"➡️  Step 1: Indexing all folders in '{directory}'...")
    folder_index = []
    for item in os.listdir(directory):
        if os.path.isdir(os.path.join(directory, item)) and not item.startswith('.'):
            folder_index.append({"folder_name": item})
    print(f"✅ Indexed {len(folder_index)} folders.")
    return folder_index

def get_folder_plan_from_llm(folder_index: List[Dict[str, str]]) -> Dict[str, Any]:
    folder_data_str = json.dumps(folder_index)
    prompt = f"Task: Group folders. Rules: Group MUST contain >= 2 folders. Ungroupable folders go into '_standalone'. Output ONLY JSON with 'organization_plan' key. Data: {folder_data_str}"
    print("   - Asking AI for a folder organization plan...")
    try:
        response = ollama.chat(model=OLLAMA_MODEL, messages=[{'role': 'user', 'content': prompt}], options={'temperature': 0.0}, format='json')
        return json.loads(response['message']['content'])
    except Exception as e:
        print(f"\n❌ An AI communication error occurred: {e}")
        return None

def run_folder_organization(directory: str, args: argparse.Namespace):
    # This remains a synchronous operation for simplicity
    folder_index = index_folders(directory)
    if not folder_index: sys.exit("No folders found to organize.")
    
    print("\n➡️  Step 2: Analyzing folder structure...")
    response_data = get_folder_plan_from_llm(folder_index)
    if not response_data or "organization_plan" not in response_data:
        sys.exit("❌ Could not get a valid organization plan from the AI.")

    final_plan = response_data["organization_plan"]
    display_plan(final_plan, "folders")
    if not args.dry_run and (args.yes or input("Apply this plan? (y/N): ").lower().strip() == 'y'):
        execute_plan(directory, final_plan, "folders")
    else:
        if not args.dry_run: print("Aborted by user.")
        print("\n🏁 This was a DRY RUN. No items were moved.")

# --- UNDO FUNCTIONALITY ---

def run_undo(directory: str):
    undo_path = os.path.join(directory, UNDO_FILENAME)
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
        
        # Ensure destination directory for the reversal exists
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        
        if os.path.exists(source):
            shutil.move(source, dest)

    # Clean up empty directories left behind by the organization
    for folder in {os.path.dirname(action['dest']) for action in undo_actions}:
        folder_path = os.path.join(directory, folder)
        if os.path.exists(folder_path) and not os.listdir(folder_path):
            os.rmdir(folder_path)

    os.remove(undo_path)
    print("\n✅ Undo complete.")


# --- SHARED DISPLAY & EXECUTION ---

def display_plan(plan: Dict[str, List[str]], mode: str):
    print("\n✨ Here is the final proposed organization plan:")
    print("─" * 40)
    if mode == 'files':
        for folder, items in sorted(plan.items()):
            # For recursive plans, item is a dict, otherwise a string
            paths = [item['path'] if isinstance(item, dict) else item for item in items]
            print(f"📁 Create folder: '{folder}'")
            for path in sorted(paths)[:5]: print(f"    └── Move '{path}'")
            if len(paths) > 5: print(f"    └── and {len(paths) - 5} more...")
    else:
        # Folder display logic...
        standalone = plan.pop('_standalone', [])
        for p_folder, s_folders in sorted(plan.items()):
            print(f"📁 Create parent folder: '{p_folder}'")
            for s_folder in sorted(s_folders): print(f"    └── Move folder '{s_folder}' into it")
        if standalone: print(f"\n👉 {len(standalone)} folders will be left as they are.")
    print("─" * 40)

def execute_plan(directory: str, plan: Dict[str, List[str]], mode: str):
    print(f"\n➡️  Step 3: Executing {mode} organization plan...")
    undo_actions = []
    
    item_count = sum(len(items) for items in plan.values())
    with tqdm(total=item_count, desc=f"Moving {mode}") as pbar:
        if mode == 'files':
            for folder, items in plan.items():
                target_dir_path = os.path.join(directory, folder)
                os.makedirs(target_dir_path, exist_ok=True)
                for item in items:
                    # Item is a dict in recursive mode, string otherwise
                    source_rel_path = item['path'] if isinstance(item, dict) else item
                    source_abs_path = os.path.join(directory, source_rel_path)
                    
                    dest_rel_path = os.path.join(folder, os.path.basename(source_rel_path))
                    dest_abs_path = os.path.join(directory, dest_rel_path)
                    
                    if os.path.exists(source_abs_path):
                        undo_actions.append({"source": source_rel_path, "dest": dest_rel_path})
                        shutil.move(source_abs_path, dest_abs_path)
                    pbar.update(1)
        # Folder execution logic...
        else:
            for p_folder, s_folders in plan.items():
                if p_folder == '_standalone':
                    pbar.update(len(s_folders)); continue
                target_dir = os.path.join(directory, p_folder)
                os.makedirs(target_dir, exist_ok=True)
                for s_folder in s_folders:
                    if p_folder == s_folder: pbar.update(1); continue
                    source_path = os.path.join(directory, s_folder)
                    dest_path = os.path.join(target_dir, s_folder)
                    if os.path.isdir(source_path):
                        undo_actions.append({"source": s_folder, "dest": os.path.join(p_folder, s_folder)})
                        shutil.move(source_path, dest_path)
                    pbar.update(1)

    if undo_actions:
        with open(os.path.join(directory, UNDO_FILENAME), 'w') as f:
            json.dump(undo_actions, f, indent=2)
        print(f"\n📝 Undo log saved. To reverse this action, run with the --undo flag.")
    
    print("\n✅ Organization complete!")


async def main():
    parser = argparse.ArgumentParser(description="Broom: An AI-powered file and folder organizer.")
    parser.add_argument("directory", nargs='?', default=None, help="The directory to organize. Required unless using --undo.")
    parser.add_argument("--mode", choices=['files', 'folders'], default='files', help="Organize 'files' or group 'folders'.")
    parser.add_argument("--recursive", action="store_true", help="Organize files in all subdirectories (files mode only).")
    parser.add_argument("--undo", action="store_true", help="Undo the last organization in the specified directory.")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without moving anything.")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation and execute the plan.")
    args = parser.parse_args()

    # Special handling for undo
    if args.undo:
        if not args.directory: sys.exit("❌ Error: Please specify the directory where you want to run the undo operation.")
        target_directory = os.path.expanduser(args.directory)
        run_undo(target_directory)
        return
        
    if not args.directory:
        sys.exit("❌ Error: Please specify a directory to organize.")
        
    target_directory = os.path.expanduser(args.directory)
    if not os.path.isdir(target_directory): sys.exit(f"❌ Error: Directory '{target_directory}' not found.")
    
    if args.mode == 'files':
        await run_file_organization(target_directory, args)
    else:
        if args.recursive: print("⚠️  Warning: Recursive mode is only supported for file organization. Running on top-level folders only.")
        run_folder_organization(target_directory, args)

if __name__ == "__main__":
    # Check for Ollama before starting async loop
    if not any(arg in ['--undo', '-h', '--help'] for arg in sys.argv) and not check_ollama_is_running():
        sys.exit(1)
    asyncio.run(main())
