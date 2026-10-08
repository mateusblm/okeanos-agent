#!/usr/bin/env python3
"""Gera os adaptadores do Okeanos a partir de core/process.md.

    python3 scripts/build.py          # escreve os arquivos gerados
    python3 scripts/build.py --check  # sai com erro se algum estiver desatualizado

Só biblioteca padrão.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESS = Path("core/process.md")

CLAUDE_FRONTMATTER = """\
---
name: okeanos
description: Fluxo contínuo de desenvolvimento. Classifica cada demanda e conduz pelo processo, com dois gates de aprovação.
keep-coding-instructions: true
force-for-plugin: true
---

"""

AGENTS_MD_START = "<!-- okeanos:start -->"
AGENTS_MD_END = "<!-- okeanos:end -->"
AGENTS_MD_NOTE = (
    "<!-- Arquivo gerado por scripts/build.py a partir de core/process.md."
    " Não edite à mão. -->"
)


def agents_md_block(process):
    return (
        f"{AGENTS_MD_START}\n{AGENTS_MD_NOTE}\n\n"
        f"{process.rstrip()}\n\n{AGENTS_MD_END}\n"
    )


def outputs(process):
    """Mapa caminho relativo -> conteúdo esperado de cada arquivo gerado."""
    return {
        Path("output-styles/okeanos.md"): CLAUDE_FRONTMATTER + process,
        Path("adapters/agents-md/okeanos.md"): agents_md_block(process),
    }


def main(argv):
    process = (ROOT / PROCESS).read_text(encoding="utf-8")
    for rel, content in outputs(process).items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
