# Agent Regression Gate — CI-integrated eval harness for agent tool-calls

Agent testing / regression detection against real environments, wired into CI/CD.

**Live demo:** https://ashr.ashanpraba.com

The demo runs entirely in the browser against seeded data — no API keys,
no accounts, and no external services required.

## Stack

- Python
- LangChain
- Bedrock (or Bedrock-compatible mock if no creds)
- MCP tool server (single tool, e.g. calculator or file lookup)
- Go
- Redis
- GitHub Actions

## How it works

- Write a tiny Python agent (LangChain + Bedrock) that uses one MCP tool (e.g. a lookup tool) to answer 5 frozen test prompts, saving each run's tool-call trace + final answer as JSON 'golden' baseline.
- Store the golden baseline in Redis keyed by scenario id.
- Write a Go CLI/service that pulls the current run's JSON output, diffs it field-by-field against the Redis golden record, and exits non-zero with a human-readable diff on mismatch.
- Introduce a deliberate change to the agent's system prompt or tool schema to simulate a regression.
- The Python runner + Go diff checker into a GitHub Actions workflow so the regression fails the build with a clear log output.
- Record the terminal running `git push` → Actions failing → diff output, narrating each component's role.

## Running locally

```bash
cd src
bash run.sh
```

Then open the printed URL. A prebuilt static version of the UI lives in
`src/web/` and can be opened directly with no server.
