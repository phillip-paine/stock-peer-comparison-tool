import os

DOWNLOAD_DIR = "~/Documents/Code/peer-comparison-tool/data"

HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
DB_PATH = os.getenv("DB_PATH")

if not DB_PATH:
    raise ValueError("DB not set in environment")

if not HUGGINGFACE_API_TOKEN:
    raise ValueError("HUGGINGFACE_API_TOKEN not set in environment")

url = "https://router.huggingface.co/hf-inference/models/"
# model = "mistralai/Mistral-7B-Instruct-v0.3"  # deprecated now it seems
model = "meta-llama/Llama-3.2-3B-Instruct"
HUGGINGFACE_MODEL = model
HUGGINGFACE_API_URL = f"{url}{model}"


