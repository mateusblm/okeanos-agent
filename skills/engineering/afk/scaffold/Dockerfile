FROM node:22-bookworm

RUN apt-get update && apt-get install -y \
  git \
  curl \
  jq \
  && rm -rf /var/lib/apt/lists/*

# OKEANOS: project runtimes and tools (python, go, etc.) go here.

# Sandcastle passes the host UID/GID so bind-mounted files share an owner.
ARG AGENT_UID=1000
ARG AGENT_GID=1000

RUN groupmod -o -g $AGENT_GID node && usermod -o -u $AGENT_UID -g $AGENT_GID -d /home/agent -m -l agent node

# OKEANOS: agent CLI. Keep the block matching AGENT in main.mts, comment the
# others. Install lines come from Sandcastle's own init templates.

# Codex (AGENT = "codex"), installed as root:
# RUN npm install -g @openai/codex

# GitHub Copilot CLI (AGENT = "copilot"), installed as root:
# RUN npm install -g @github/copilot

USER ${AGENT_UID}:${AGENT_GID}

# Claude Code (AGENT = "claude", the default):
RUN curl -fsSL https://claude.ai/install.sh | bash

# Cursor Agent CLI (AGENT = "cursor"), installed as the agent user:
# RUN curl https://cursor.com/install -fsS | bash

ENV PATH="/home/agent/.local/bin:$PATH"

WORKDIR /home/agent

# Sandcastle mounts the worktree and sets it as the working directory at start.
ENTRYPOINT ["sleep", "infinity"]
