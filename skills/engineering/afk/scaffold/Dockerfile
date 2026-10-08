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
USER ${AGENT_UID}:${AGENT_GID}

RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/home/agent/.local/bin:$PATH"

WORKDIR /home/agent

# Sandcastle mounts the worktree and sets it as the working directory at start.
ENTRYPOINT ["sleep", "infinity"]
