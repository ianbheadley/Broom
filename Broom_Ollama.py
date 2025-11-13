#!/usr/bin/env python3
import os
import sys
import argparse
import json
import ollama
import config
from core import FileOrganizer, FolderOrganizer, UndoManager

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


class Broom:
    """
    An AI-powered file and folder organizer.
    """
    def __init__(self):
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
        parser.add_argument("--stream", action="store_true", help="Stream the AI's response in real-time (folders mode only).")
        parser.add_argument("--model", type=str, default=config.OLLAMA_MODEL, help=f"The Ollama model to use (default: {config.OLLAMA_MODEL}).")
        return parser

    def run(self):
        """
        Runs the main application logic.
        """
        args = self.parser.parse_args()

        if args.mode == 'files' and args.stream:
            print("⚠️  Warning: Streaming for files is sequential and does not run concurrently.")

        ollama_client = OllamaClient(args.model)
        if not any(arg in ['--undo', '-h', '--help'] for arg in sys.argv) and not ollama_client.check_connection():
            sys.exit(1)

        if args.undo:
            if not args.directory:
                sys.exit("❌ Error: Please specify the directory where you want to run the undo operation.")
            UndoManager.run(os.path.expanduser(args.directory))
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
                batch_size=config.BATCH_SIZE,
                text_extensions=config.TEXT_EXTENSIONS,
                max_content_length=config.MAX_CONTENT_LENGTH
            )
            organizer.organize(args.dry_run, args.yes, args.stream)
        else: # folders mode
            if args.recursive:
                print("⚠️  Warning: Recursive mode is only supported for file organization. Running on top-level folders only.")
            organizer = FolderOrganizer(
                directory=target_directory,
                ollama_client=ollama_client
            )
            organizer.organize(args.dry_run, args.yes, args.stream)


if __name__ == "__main__":
    broom = Broom()
    broom.run()
