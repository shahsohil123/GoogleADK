# Building a Git History Analyzer with Google ADK and LLMs — The Hard Parts Nobody Talks About

*How I built an AI agent that reads your git history, explains what changed in plain English, and flags risky commits — and everything that went wrong along the way.*

---

I recently set out to build a simple demo with [Google's Agent Development Kit (ADK)](https://github.com/google/adk-python) — an AI agent that analyzes a git repository and produces a human-readable report of recent changes. The idea was straightforward. The execution was not.

This post covers what I built, how the code works, and the real-world lessons I learned about model selection, API quotas, and the hidden gotchas of building agentic applications.

**Full source code:** [github.com/shahsohil123/GoogleADK](https://github.com/shahsohil123/GoogleADK)

---

## What the Agent Does

The **Git Commit Explainer** agent connects to any git repository and produces a structured report:

- Reads the last 20 commits
- Inspects file-level changes with `git diff` and `git show`
- Explains what changed in plain English, grouped by feature or fix
- Flags commits touching sensitive areas: auth, payments, migrations, secrets
- Recommends what to review before the next release

Here's what the output looks like:

```
## Summary
- 18 commits over 6 days by 3 authors
- Primary focus: payment service refactor and auth token refresh logic

## Risk Flags
c4d8a91 — touches auth/token_manager.py and .env.production
This commit modifies token expiry logic AND updates production env config
in the same change. Worth reviewing: are the new expiry values intentional?

## Recommendations
- Review c4d8a91 before release — mixed concerns in one commit
- 4 hotfix commits in 2 days suggests instability in the payment module
```

---

## The Architecture

The agent is built on three components:

1. **Google ADK** — The agent framework
2. **ExecuteBashTool** — An experimental, undocumented tool in ADK v2.0.0 alpha that lets agents run shell commands
3. **BashToolPolicy** — A safety layer that restricts which commands the agent can execute

Here's the full agent definition:

```python
import os
from pathlib import Path

from google.adk import Agent
from google.adk.tools.bash_tool import ExecuteBashTool, BashToolPolicy

# Read-only git policy — agent can inspect but never modify
GIT_READ_POLICY = BashToolPolicy(
    allowed_command_prefixes=(
        "git log",
        "git diff",
        "git show",
        "git status",
        "git branch",
        "git shortlog",
        "git stash list",
    )
)

SYSTEM_INSTRUCTION = """
You are a Git Commit Explainer. Your job is to analyze a git repository
using bash commands and produce a clear report.

You have access to a bash tool to run git commands. Use it to:

1. Run: git log --oneline -20
2. Run: git log --stat -10
3. Run: git diff HEAD~5..HEAD --stat

Then write a report with:

## Summary
- Main focus of recent work
- Number of commits and authors
- Time period covered

## Recent Changes
- Explanation of what changed in the last 10 commits

## Risk Flags
- Any commits touching auth, config, migrations, or secrets
- Explain why they need careful review

## Recommendations
- What to review before next release
- Any patterns suggesting technical debt

Be direct and reference actual commit hashes and file names.
"""


def create_agent(repo_path: str) -> Agent:
    workspace = Path(repo_path).expanduser().resolve()
    if not workspace.exists() or not (workspace / ".git").exists():
        workspace = Path.home()

    return Agent(
        model="groq/llama-3.3-70b-versatile",
        name="git_commit_explainer",
        description="Analyzes git history and explains recent commits.",
        instruction=SYSTEM_INSTRUCTION,
        tools=[
            ExecuteBashTool(
                workspace=workspace,
                policy=GIT_READ_POLICY,
            )
        ],
    )
```

The key design decision is the `BashToolPolicy`. It acts as a static allowlist — the agent can only run commands that start with one of the approved prefixes. Any attempt to run `rm`, `curl`, `git push`, or anything else is blocked *before* the command even reaches the confirmation step.

On top of that, ADK's `ExecuteBashTool` has a built-in **human-in-the-loop (HITL)** confirmation for every command. Even if a command passes the policy check, the user still has to type "yes" to approve it. Defense in depth.

---

## The Model Selection Journey (Where Things Got Interesting)

This is where theory met reality. Here's what happened when I tried to run this agent with different model providers.

### Attempt 1: Gemini 2.0 Flash (Google)

The obvious first choice — ADK is a Google product, Gemini is Google's model, and there's a free tier.

```python
model="gemini-2.0-flash"
```

**Result:** Worked perfectly... for about 10 minutes. Then:

```
429 RESOURCE_EXHAUSTED
Quota exceeded for metric: generate_content_free_tier_requests
limit: 0, model: gemini-2.0-flash
```

The free tier gives you 1,500 requests/day, but the quota resets and can hit zero faster than you expect during development when you're iterating rapidly. Lesson: **free tiers are for demos, not for development.**

### Attempt 2: Ollama (Local Models)

No API keys, no quotas, runs entirely on your machine. I tried Mistral, Llama2, and neural-chat.

```python
model="ollama/mistral"
```

**Result:** The models connected fine, but every single one hallucinated tool names:

```
ValueError: Tool 'summary' not found.
Available tools: execute_bash
```

The agent would try to call `summary`, `report_git_history`, or `git_commit_explainer` instead of the actual `execute_bash` tool. This happened consistently across Mistral 7B, Llama2 7B, and neural-chat 7B.

**The takeaway:** Small local models (7B parameters) don't reliably handle function calling in ADK's format. They understand the *intent* but can't follow the *protocol*. If you need function calling with Ollama, you'll likely need a larger model (70B+) or one specifically fine-tuned for tool use.

### Attempt 3: Groq API (The Plot Twist)

Groq offers fast inference with a generous free tier. But I hit a different problem — **model deprecation**:

```
The model `mixtral-8x7b-32768` has been decommissioned.
The model `llama-3.1-70b-versatile` has been decommissioned.
The model `gemma-7b-it` has been decommissioned.
The model `llama-3.2-90b-vision-preview` has been decommissioned.
```

Four models, all decommissioned. The API key was valid the entire time — the model names were simply outdated. The fix was to query the Groq API directly to discover the current model list:

```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY" | python3 -m json.tool
```

This revealed that the correct current model name is `llama-3.3-70b-versatile` (not `3.1`, not `3.2`). A one-digit difference that took four failed attempts to discover.

**The takeaway:** Model IDs are not stable. They get deprecated, renamed, and decommissioned regularly. **Always query the `/models` endpoint** to verify what's actually available before hardcoding a model name.

### The Working Configuration

```python
model="groq/llama-3.3-70b-versatile"
```

This works because:
- Groq's free tier is generous (14,400 requests/day)
- Llama 3.3 70B handles function calling correctly
- The model follows ADK's tool-calling protocol without hallucinating tool names
- Inference is fast (Groq's LPU hardware)

### Attempt 4: functionGemma 270M (Local, No API Key Required)

After chasing 70B models in the cloud, I went in the opposite direction: a **270M parameter model fine-tuned specifically for function calling**. Google's [functionGemma](https://huggingface.co/google/functiongemma-270m-it) was trained end-to-end to output structured tool calls rather than free-form text.

**Problem 1: Gated HuggingFace repo**

```
401 GatedRepoError: Access to model google/functiongemma-270m-it is restricted.
You must accept the license on huggingface.co to use it.
```

Fix: Use the community mirror `unsloth/functiongemma-270m-it`, which is ungated and publishes the same weights.

**Problem 2: Non-standard output format**

functionGemma doesn't output OpenAI-compatible JSON. It uses its own custom format:

```
<start_function_call>call:execute_bash{command:<escape>git log --oneline -5<escape>}<end_function_call>
```

ADK/LiteLLM expect `{"tool_calls": [{"function": {"name": "...", "arguments": "..."}}]}`. These two formats are completely incompatible.

**The solution: A format adapter server**

I built a FastAPI server (`functiongemma_server.py`) that bridges the two worlds:

1. Loads the model locally via HuggingFace `transformers`
2. Accepts standard OpenAI `/v1/chat/completions` requests
3. Converts them to functionGemma's input format (using the `developer` role and tool schemas)
4. Runs inference and parses the custom output format back to OpenAI `tool_calls`
5. Serves on `http://localhost:11435`

**Ingesting the model** (four lines):

```python
from transformers import AutoModelForCausalLM, AutoProcessor

MODEL_ID = "unsloth/functiongemma-270m-it"
processor = AutoProcessor.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype="auto", device_map="auto")
```

HuggingFace caches the download in `~/.cache/huggingface/hub/`. Subsequent runs load from cache instantly.

**Parsing the custom output format:**

```python
FUNC_CALL_RE = re.compile(
    r"<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>",
    re.DOTALL,
)
PARAM_RE = re.compile(r"(\w+):<escape>(.*?)<escape>")

def parse_functiongemma_output(text: str):
    match = FUNC_CALL_RE.search(text)
    if not match:
        return None, text.strip()  # Plain text response
    tool_name = match.group(1)
    arguments = {m.group(1): m.group(2) for m in PARAM_RE.finditer(match.group(2))}
    return tool_name, arguments
```

**Connecting to ADK:**

```bash
# Terminal 1: Start the adapter server
python functiongemma_server.py
# Serving OpenAI-compatible API at http://localhost:11435
```

```bash
# Terminal 2: Run ADK pointing to the local server
export OPENAI_API_BASE=http://localhost:11435/v1
export OPENAI_API_KEY=none
# In agent.py: model="openai/functiongemma"
adk run .
```

**Standalone test result:**

```
Query: Show me the last 5 commits in this repository.

functionGemma output:
<start_function_call>call:execute_bash{command:<escape>last 5 commits<escape>}<end_function_call>

✅ YES — called the right tool!
```

The model correctly identified `execute_bash` — the exact failure mode that 7B general models couldn't overcome. The tradeoff: the `command` value is imprecise ("last 5 commits" instead of the actual bash command). The model understands *which* tool to call but needs prompt engineering to produce exact bash syntax.

**The takeaway:** Architecture beats parameter count for structured tasks. A 270M model fine-tuned for function calling outperforms a 7B general model on tool invocation. And it runs entirely locally — no API key, no quota, no latency to a cloud provider.

---

## Setting Up: Step by Step

### 1. Install ADK with LiteLLM Extensions

ADK uses Google's Gemini models by default. To use third-party models (Groq, Ollama, OpenAI, Anthropic, etc.), you need the `extensions` extra:

```bash
# Create a virtual environment
python3.11 -m venv adk-env
source adk-env/bin/activate

# Install ADK with LiteLLM support
pip install "google-adk[extensions]"
```

Without `[extensions]`, you'll get:

```
ValueError: Model ollama/mistral not found.
Provider-style models require the litellm package.
Install it with: pip install google-adk[extensions]
```

### 2. Set Your API Key

```bash
# For Groq (recommended for free usage)
export GROQ_API_KEY="your-groq-api-key"

# For Gemini (alternative)
export GOOGLE_API_KEY="your-gemini-api-key"
```

Get a free Groq key at [console.groq.com](https://console.groq.com). Get a free Gemini key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### 3. Clone and Run

```bash
git clone https://github.com/shahsohil123/GoogleADK.git
cd GoogleADK/git_commit_explainer

# Point to any git repo you want to analyze
export REPO_PATH=/path/to/your/repo

# Run the agent (interactive CLI)
adk run .

# Or use the web UI
adk web .
```

### 4. Interact with the Agent

```
[user]: Analyze the git history in this directory
[HITL confirm] Please approve or reject the bash command: git log --oneline -20
  Type "yes" to confirm, anything else to reject.
[user]: yes
```

The agent will run several git commands (each requiring your approval), then produce a structured report.

---

## The Safety Model

This is worth highlighting because it's often an afterthought in agent demos. The Git Commit Explainer has **three layers of safety**:

**Layer 1: BashToolPolicy (Static Allowlist)**

```python
GIT_READ_POLICY = BashToolPolicy(
    allowed_command_prefixes=(
        "git log",
        "git diff",
        "git show",
        "git status",
        "git branch",
        "git shortlog",
        "git stash list",
    )
)
```

If the LLM tries to run `git push`, `rm -rf`, or `curl`, it's blocked immediately. No confirmation prompt, no execution — just an error returned to the agent.

**Layer 2: HITL Confirmation (Runtime Approval)**

Every command that passes the policy check still requires explicit user approval. This is hardcoded in ADK's `ExecuteBashTool` — there's no way to bypass it:

```python
# From ADK source (bash_tool.py, line 121)
# Always request user confirmation.
if not tool_context.tool_confirmation:
    tool_context.request_confirmation(
        hint=f"Please approve or reject the bash command: {command}",
    )
```

**Layer 3: Workspace Scoping**

The `ExecuteBashTool` is scoped to a specific workspace directory. The agent can't escape to the parent filesystem.

---

## Key Lessons

1. **Model selection matters more than you think.** The same agent code can succeed or fail depending entirely on the model's ability to handle function calling. Small models hallucinate tool names. Large models follow the protocol.

2. **Model IDs are ephemeral.** Groq decommissioned four models in the time between when I found their documentation and when I tried to use them. Always query the `/models` endpoint.

3. **Free tiers are for demos, not development.** Gemini's 1,500 requests/day sounds generous until you're iterating on prompts and hitting the limit before lunch.

4. **ADK's `ExecuteBashTool` is undocumented but powerful.** It's not in the official docs yet, but it's in the source. The combination of `BashToolPolicy` + HITL confirmation is a solid safety pattern for giving agents shell access.

5. **LiteLLM is the escape hatch.** ADK's `[extensions]` extra unlocks 100+ model providers through LiteLLM. Without it, you're locked to Gemini.

6. **Architecture beats parameter count for structured tasks.** A 270M model fine-tuned for function calling beats a 7B general model at tool invocation. If your use case is narrow and well-defined, look for task-specific fine-tunes before defaulting to the biggest model you can find.

7. **Non-OpenAI models require an adapter layer.** Not every local model speaks the OpenAI protocol. When it doesn't, a thin FastAPI server is all you need to bridge the gap — the investment is 200 lines of Python for full LiteLLM/ADK compatibility.

---

## What's Next

- Adding **sub-agents** for deeper analysis (e.g., a security-focused agent that runs `git log --all -- '*.env'`)
- Integrating with **GitHub Actions** for automated PR reviews
- Improving functionGemma's bash command quality via **few-shot prompting** in the system instruction
- Benchmarking functionGemma vs Llama 3.3 70B on ADK tool-calling accuracy

---

## Resources

- **Source code:** [github.com/shahsohil123/GoogleADK](https://github.com/shahsohil123/GoogleADK)
- **Google ADK:** [github.com/google/adk-python](https://github.com/google/adk-python)
- **ADK Documentation:** [google.github.io/adk-docs](https://google.github.io/adk-docs)
- **functionGemma on HuggingFace:** [huggingface.co/unsloth/functiongemma-270m-it](https://huggingface.co/unsloth/functiongemma-270m-it)
- **Groq Console:** [console.groq.com](https://console.groq.com)
- **LiteLLM Providers:** [docs.litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers)

---

*If you're building agents with ADK and running into similar issues, I'd love to hear about it. Drop a comment or open an issue on the repo.*
