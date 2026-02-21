from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain_core.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from peer_comparison_tool.comparison_tool.constants import HUGGINGFACE_MODEL, HUGGINGFACE_API_TOKEN
from typing import List, Optional, Union


def get_chat_model():
    return ChatHuggingFace(
        llm = HuggingFaceEndpoint(
            huggingfacehub_api_token=HUGGINGFACE_API_TOKEN,
            repo_id=HUGGINGFACE_MODEL,
        )
    )


def call_llm(
        llm: BaseChatModel,
        messages: List[Union[HumanMessage, SystemMessage]],
        tools: Optional[List[BaseTool]] = None,
):
    """
    Call the chat model with the given messages and optional tools.

    Returns the raw LLM response (which may include tool calls).
    """

    if tools:
        llm = llm.bind_tools(tools)

    return llm.invoke(messages)
