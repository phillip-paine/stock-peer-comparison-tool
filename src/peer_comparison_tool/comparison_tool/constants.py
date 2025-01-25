import os

DOWNLOAD_DIR = "~/Documents/Code/peer-comparison-tool/data"

DB_FOLDER = os.path.dirname(__file__)
DB_PATH = os.path.join(DB_FOLDER, "comparison_tool.db")

HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
url = "https://api-inference.huggingface.co/models/"
model = "mistralai/Mistral-7B-Instruct-v0.3"
HUGGINGFACE_API_URL = f"{url}{model}"
