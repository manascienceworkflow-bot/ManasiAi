from langchain_core.messages import AIMessage, HumanMessage

from app.config import settings
from app.rag.chain import build_chain

MAX_HISTORY_TURNS = 6


def main():
    settings.validate()
    print("Loading the Manasi knowledge base...")
    chain = build_chain()
    history = []

    print("\nManasi — ManaScience AI guide. Type 'exit' or 'quit' to leave.\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        result = chain.invoke({"input": user_input, "chat_history": history})
        answer = result["answer"]
        print(f"Manasi: {answer}\n")

        history.append(HumanMessage(content=user_input))
        history.append(AIMessage(content=answer))
        history[:] = history[-(MAX_HISTORY_TURNS * 2):]


if __name__ == "__main__":
    main()
