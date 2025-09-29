#!/usr/bin/env python3
import os
import sys
import argparse
import config
from core import OllamaClient, FileOrganizer, FolderOrganizer
from utils import UndoManager

def main():
    """
    Main function to run the Broom application.
    """
    parser = argparse.ArgumentParser(description="Broom: An AI-powered file and folder organizer.")
    parser.add_argument("directory", nargs='?', default=None, help="The directory to organize. Required unless using --undo.")
    parser.add_argument("--mode", choices=['files', 'folders'], default='files', help="Organize 'files' or group 'folders'.")
    parser.add_argument("--recursive", action="store_true", help="Organize files in all subdirectories (files mode only).")
    parser.add_argument("--undo", action="store_true", help="Undo the last organization in the specified directory.")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without moving anything.")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation and execute the plan.")
    parser.add_argument("--stream", action="store_true", help="Stream the AI's response in real-time.")
    parser.add_argument("--model", type=str, default=config.DEFAULT_OLLAMA_MODEL, help=f"The Ollama model to use (default: {config.DEFAULT_OLLAMA_MODEL}).")

    args = parser.parse_args()

    if args.mode == 'files' and args.stream:
        print("⚠️  Warning: Streaming for files is sequential and does not run concurrently.")

    if not any(arg in ['--undo', '-h', '--help'] for arg in sys.argv):
        ollama_client = OllamaClient(args.model)
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
            ollama_client=ollama_client
        )
        organizer.organize(args.dry_run, args.yes, args.stream)
    else:
        if args.recursive:
            print("⚠️  Warning: Recursive mode is only supported for file organization. Running on top-level folders only.")
        organizer = FolderOrganizer(
            directory=target_directory,
            ollama_client=ollama_client
        )
        organizer.organize(args.dry_run, args.yes, args.stream)

if __name__ == "__main__":
    main()