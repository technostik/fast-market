llm do not supported session history properly

it was done by a hack in common.agent.loop : 

def format_message_history(messages: list[dict]) -> str:
    """Format message history for the prompt."""
    formatted = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")
        if role == "tool":
            tc_id = msg.get("tool_call_id", "")
            formatted.append(f"[TOOL RESULT for {tc_id}]\n{content}")
        elif msg.get("tool_calls"):
            tc_list = []
            for tc in msg["tool_calls"]:
                tc_list.append(
                    f"- {tc['function']['name']}: {tc['function']['arguments']}"
                )
            formatted.append(
                f"[ASSISTANT]\n{content}\n[TOOL CALLS]\n" + "\n".join(tc_list)
            )
        else:
            formatted.append(f"[{role.upper()}]\n{content}")
    return "\n\n".join(formatted)

=> needed proxy-server upgrade (bugs correction)
