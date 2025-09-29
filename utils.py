import os
import json
import sys
import shutil
from typing import Dict, List
from tqdm import tqdm
import config

class UndoManager:
    """
    Manages the undo functionality for file and folder organization.
    """
    @classmethod
    def save_undo_log(cls, directory: str, actions: List[Dict[str, str]]):
        """
        Saves the undo log to a file.
        Args:
            directory (str): The directory where the undo log will be saved.
            actions (List[Dict[str, str]]): A list of actions to be saved.
        """
        with open(os.path.join(directory, config.UNDO_FILENAME), 'w') as f:
            json.dump(actions, f, indent=2)
        print(f"\n📝 Undo log saved. To reverse this action, run with the --undo flag.")

    @classmethod
    def run(cls, directory: str):
        """
        Runs the undo process.
        Args:
            directory (str): The directory where the undo operation will be performed.
        """
        undo_path = os.path.join(directory, config.UNDO_FILENAME)
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


def display_plan(plan: Dict[str, List[str]], mode: str):
    """
    Displays the organization plan to the user.
    Args:
        plan (Dict[str, List[str]]): The organization plan.
        mode (str): The organization mode ('files' or 'folders').
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