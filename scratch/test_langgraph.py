import os
import warnings
os.environ["ADK_SUPPRESS_EXPERIMENTAL_FEATURE_WARNINGS"] = "true"
warnings.filterwarnings("ignore", category=UserWarning)

from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from google.adk.agents.langgraph_agent import LangGraphAgent
from google.adk import Agent
import asyncio

class State(TypedDict):
    messages: Annotated[list, add_messages]

def my_node(state: State):
    return {"messages": [AIMessage(content="Hello from LangGraph!")]}

graph_builder = StateGraph(State)
graph_builder.add_node("chatbot", my_node)
graph_builder.add_edge(START, "chatbot")
graph_builder.add_edge("chatbot", END)
graph = graph_builder.compile()

langgraph_agent = LangGraphAgent(
    name="langgraph_agent",
    description="A simple langgraph agent",
    graph=graph
)

main_agent = Agent(
    name="main_agent",
    model="gemini-2.5-flash",
    instruction="You are a helpful assistant. If the user says 'hello', talk to the langgraph_agent to get a response.",
    tools=[langgraph_agent]
)

async def main():
    async for event in main_agent.run("hello"):
        print(event)

if __name__ == "__main__":
    asyncio.run(main())
