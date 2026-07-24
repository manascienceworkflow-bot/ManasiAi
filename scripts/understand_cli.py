import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.nodes.understanding_node import build_understanding_graph  # noqa: E402

MAX_HISTORY_TURNS = 6

SEED_HISTORY = [
    {"role": "user", "content": "What therapies do you have for attention difficulties in children?"},
    {"role": "assistant", "content": "We offer several attention-focused therapy programs designed for children."},
]


def main():
    parser = argparse.ArgumentParser(
        description="Manasi Understanding Node spot-check tool (Phase 1, no answers generated)."
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Pre-load a fake prior turn about children's attention therapy, useful for testing "
        "follow-up/pronoun disambiguation (e.g. typing 'What about for adults?').",
    )
    args = parser.parse_args()

    settings.validate()
    print("Building the Understanding Node graph...")
    graph = build_understanding_graph()
    history = list(SEED_HISTORY) if args.seed else []

    print("\nManasi Understanding Node — spot-check tool. Type 'exit' or 'quit' to leave.\n")
    print("This does NOT answer your question — it only prints the structured")
    print("intent/topic/search_query/emotional_state JSON for inspection.\n")
    if args.seed:
        print("Seeded with a prior turn about children's attention therapy.\n")

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

        result = graph.invoke(
            {"user_message": user_input, "chat_history": history, "understanding": None}
        )
        understanding = result["understanding"]
        print(f"Understanding: {understanding}\n")

        history.append({"role": "user", "content": user_input})
        history[:] = history[-(MAX_HISTORY_TURNS * 2):]


if __name__ == "__main__":
    main()
