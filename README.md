# Broom 🧹

Broom is an AI-powered file and folder organizer that helps you tidy up your directories with the power of large language models. It can analyze your files or folders and suggest a more organized structure, which it can then apply automatically.

Broom can be run as a command-line tool or as a macOS menu bar application.

## Features

- **File Organization**: Scans files and categorizes them into subdirectories based on their content and type.
- **Folder Organization**: Groups related folders into parent categories.
- **AI-Powered**: Uses Ollama to generate organization plans.
- **Flexible**: Supports different Ollama models.
- **Interactive and Non-Interactive Modes**: Preview changes with a dry run, or apply them automatically.
- **Undo Functionality**: Revert the last organization.
- **Cross-Platform CLI**: The command-line interface works on any system with Python.
- **macOS GUI**: A convenient menu bar app for macOS users.

## Installation

1.  **Install Ollama**: Make sure you have [Ollama](https://ollama.ai/) installed and running. You can download it from the official website.

2.  **Pull a Model**: You'll need an Ollama model to analyze your files. We recommend starting with `gemma3:12b`, but you can use others.

    ```bash
    ollama pull gemma3:12b
    ```

3.  **Install Dependencies**: Clone this repository and install the required Python packages.

    ```bash
    git clone <repository-url>
    cd broom
    pip install -r requirements.txt
    ```

## Usage

### Command-Line Interface (CLI)

The CLI is the primary way to use Broom.

**Organize Files:**

```bash
python Broom_Ollama.py /path/to/your/directory
```

**Organize Folders:**

```bash
python Broom_Ollama.py /path/to/your/directory --mode folders
```

**Options:**

-   `--model`: Specify which Ollama model to use.
    ```bash
    # Example using a different model
    python Broom_Ollama.py /path/to/your/directory --model llama3
    ```
-   `--recursive`: Organize files in all subdirectories.
-   `--dry-run`: See the proposed plan without moving any files.
-   `--yes` or `-y`: Skip the confirmation prompt and apply the plan.
-   `--undo`: Revert the last organization in a directory.

### macOS Menu Bar App (GUI)

Broom also includes a simple menu bar application for macOS.

**To run the GUI:**

```bash
pythonw Broom_GUI.py
```

*Note: You may need to use `pythonw` instead of `python` to run the GUI application correctly on macOS. This ensures it runs as a background app without a terminal window.*

Once running, you'll see a new "Broom" icon in your menu bar. From there, you can:
-   **Toggle Mode**: Switch between organizing "Files" or "Folders".
-   **Organize Directory**: Open a dialog to select a directory to organize. The process will run in the background, and you'll receive a notification when it's complete.