"""
Dashboard-level constants.

Bug found while tracing app.py for the dashboard refactor (see refactor
handoff notes, section on "real bugs found"): this module used to raise
`ValueError` at *import* time if `DB_PATH` or `HUGGINGFACE_API_TOKEN` were
unset. `DOWNLOAD_DIR` is imported by four live page modules
(`company_quarterly_report_page.py`, `company_balance_sheet_report_page.py`,
`individual_company_overview_page.py`, `discounted_cashflow_model_page.py`)
that have nothing to do with either of those two settings — the entire
dashboard failed to import unless someone had a Hugging Face token and a
`DB_PATH` env var set, even though those two values are only ever consumed
by `bad_news_trading_model.py` and `agent_chat.py`, neither of which is
wired into the app's routing. Fixed by making both lazy (`os.getenv`, no
raise) so importing this module never has side effects; anything that
actually needs a Hugging Face token should check for `None` itself at the
point of use.

`DB_PATH` itself is dropped rather than kept lazy: the dashboard now reads
data exclusively through `data.database.session_scope()` /
`data.config.settings.database_url`, the same connection the pipeline uses
(see data/pipeline.py's entry point) — so there's no longer a second,
independent "where's the database" setting for the dashboard to disagree
with the pipeline about.
"""
import os

from src.peer_comparison_tool.data.config import settings

# Where exported CSVs (quarterly/balance-sheet downloads) get written.
# Previously a hardcoded "/data_files" absolute path; now shares the same
# configurable data directory as the rest of the app.
DOWNLOAD_DIR = str(settings.data_dir)

# Only used by the not-yet-wired-in agent-chat / bad-news-trading-model
# features (see agent_chat.py, bad_news_trading_model.py). Left as an
# optional lazy lookup rather than removed, since those features may be
# finished later — but importing this module must never require it.
HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")

url = "https://router.huggingface.co/hf-inference/models/"
model = "meta-llama/Llama-3.2-3B-Instruct"
HUGGINGFACE_MODEL = model
HUGGINGFACE_API_URL = f"{url}{model}"
