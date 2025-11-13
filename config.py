# config.py

# -- AI Configuration --
# Specifies the Ollama model to be used for generating organization plans.
# The default is 'gemma3:12b', a powerful model suitable for complex classification.
# You can replace this with any other model available in your Ollama setup.
OLLAMA_MODEL = 'gemma3:12b'

# -- File Processing Configuration --
# The maximum number of bytes to read from the beginning of a file for content analysis.
# A larger value might provide more context to the AI but will increase processing time
# and memory usage. The default is 1024 bytes (1 KB).
MAX_CONTENT_LENGTH = 1024

# A list of file extensions to be treated as text files.
# The script will attempt to read the content of these files.
# Files with extensions not in this list that contain null bytes are treated as binary.
TEXT_EXTENSIONS = [
    '.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml', '.csv',
    '.sh', '.yaml', '.yml', '.ini', '.log', '.rst', '.tex', '.rtf'
]

# The number of files to be processed in a single batch.
# A larger batch size can be faster but may consume more memory and might
# hit the context limits of the AI model. The default is 30.
BATCH_SIZE = 30

# -- GUI Configuration --
# The title of the application as it appears in the macOS menu bar.
APP_TITLE = "Broom"

# The icon for the application in the menu bar.
# This is a base64 encoded string of the icon image.
APP_ICON = "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
