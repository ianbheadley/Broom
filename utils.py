from typing import Dict, List

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
