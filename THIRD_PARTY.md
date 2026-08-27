# Clean-room and third-party boundary

This repository was implemented from public feature descriptions and independently designed interfaces. No source code was copied from the projects below, and none is vendored or required at runtime.

| Project | Publicly described concept considered | Code incorporated |
|---|---|---:|
| LiteLLM | provider abstraction, routing, fallback, cost visibility | No |
| RouteLLM | quality/cost-aware model selection | No |
| Claude Code Router | common provider front door and fallback | No |
| Aider | planning/editing roles and validation loop | No |
| OpenHands | repository-level coding-agent execution | No |
| SWE-agent | issue-to-repository agent workflow | No |

A future bridge that invokes one of these tools remains subject to that project's license, terms, CLI contract, and security model. Keep such bridges optional and separately reviewed.

Project links:

- https://github.com/BerriAI/litellm
- https://github.com/lm-sys/RouteLLM
- https://github.com/musistudio/claude-code-router
- https://github.com/Aider-AI/aider
- https://github.com/OpenHands/OpenHands
- https://github.com/SWE-agent/SWE-agent
