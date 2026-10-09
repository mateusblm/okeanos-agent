"""Package installs: parse install commands and check names against the registries."""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .model import ASK, DENY

POPULAR = {
    "npm": "react react-dom vue svelte next express koa fastify lodash underscore axios moment dayjs date-fns "
    "typescript webpack vite rollup esbuild babel jest vitest mocha chai sinon eslint prettier "
    "chalk commander yargs dotenv uuid zod yup joi ajv debug cors body-parser mongoose sequelize "
    "prisma pg mysql2 redis ioredis jsonwebtoken bcrypt bcryptjs passport socket.io ws nodemon "
    "rxjs immer redux zustand classnames clsx tailwindcss postcss autoprefixer sass graphql "
    "cheerio puppeteer playwright sharp multer nanoid ramda bluebird got node-fetch cross-env "
    "rimraf glob minimist semver tslib inquirer ora execa fs-extra",
    "pypi": "requests numpy pandas scipy matplotlib flask django fastapi uvicorn pydantic sqlalchemy "
    "pytest boto3 botocore urllib3 six setuptools wheel pip certifi idna charset-normalizer "
    "python-dateutil pyyaml jinja2 click rich typer httpx aiohttp celery redis psycopg2 "
    "psycopg2-binary pillow scikit-learn tensorflow torch transformers openai anthropic "
    "beautifulsoup4 lxml selenium cryptography pyjwt tqdm black ruff mypy flake8 isort poetry",
    "crates": "serde serde_json tokio anyhow thiserror clap rand regex reqwest log env_logger tracing "
    "chrono itertools lazy_static once_cell futures hyper axum actix-web syn quote proc-macro2",
}


def package_requests(toks):
    """Return [(ecosystem, name)] for install commands that add named packages."""
    if not toks:
        return []
    tool, args = toks[0], toks[1:]
    eco, names = None, []
    if tool in ("npm", "pnpm", "yarn", "bun") and args and args[0] in ("i", "install", "add"):
        eco, names = "npm", args[1:]
    elif tool in ("pip", "pip3") and args and args[0] == "install":
        eco, names = "pypi", args[1:]
    elif tool == "uv" and args[:1] == ["add"]:
        eco, names = "pypi", args[1:]
    elif tool == "uv" and args[:2] == ["pip", "install"]:
        eco, names = "pypi", args[2:]
    elif tool == "poetry" and args[:1] == ["add"]:
        eco, names = "pypi", args[1:]
    elif tool == "cargo" and args[:1] == ["add"]:
        eco, names = "crates", args[1:]
    elif tool == "gem" and args[:1] == ["install"]:
        eco, names = "rubygems", args[1:]
    elif tool == "bundle" and args[:1] == ["add"]:
        eco, names = "rubygems", args[1:]
    elif tool == "composer" and args[:1] == ["require"]:
        eco, names = "packagist", args[1:]
    elif tool == "go" and args[:1] in (["get"], ["install"]):
        eco, names = "go", args[1:]
    elif tool == "dotnet" and args[:2] == ["add", "package"]:
        eco, names = "nuget", args[2:]
    elif tool == "dotnet" and len(args) >= 3 and args[0] == "add" and args[2] == "package":
        eco, names = "nuget", args[3:]
    if not eco:
        return []
    out, skip_next = [], False
    for a in names:
        if skip_next:
            skip_next = False
            continue
        # Shell redirections (2>&1, >/dev/null, &>log, < in) are not names; a bare
        # operator (>, 2>, >>, <) also takes the next token as its target.
        redirect = re.search(r"^\d+(?=[<>])|&>|[<>]", a)
        if redirect:
            skip_next = bool(re.fullmatch(r"\d*(>>?|<|>&|<&)|&>>?", a[redirect.start():]))
            a = a[:redirect.start()]
            if not a:
                continue
        if a in ("-r", "--requirement", "-e", "--editable", "-c", "--constraint", "--index-url", "-i", "--registry", "--features"):
            skip_next = True
            continue
        if a.startswith("-") or a.startswith(".") or a.startswith("/") or "://" in a or a.startswith("git+"):
            continue
        if eco == "npm":
            name = re.sub(r"(?<=.)@[^@/]*$", "", a)
        elif eco == "go":
            name = a.split("@", 1)[0]
            if name in ("./...", "all") or not re.match(r"^[a-z0-9.-]+\.[a-z]+/", name):
                continue
        elif eco == "packagist":
            name = a.split(":", 1)[0]
        else:
            name = re.split(r"[=<>!~\[;@ ]", a, maxsplit=1)[0]
        if name:
            out.append((eco, name))
    return out


def fetch_json(url, timeout=4):
    fake = os.environ.get("OKEANOS_REGISTRY_FAKE")
    if fake:
        # Tests: a JSON map {url: body | http_status}; a url not in the map behaves as offline.
        with open(fake) as f:
            table = json.load(f)
        if url not in table:
            raise urllib.error.URLError("not in fake registry")
        if isinstance(table[url], int):
            raise urllib.error.HTTPError(url, table[url], "fake registry", None, None)
        return table[url]
    req = urllib.request.Request(url, headers={"User-Agent": "okeanos-hook (claude code plugin)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def edit_distance(a, b):
    """Damerau-Levenshtein (optimal string alignment): a swap of two letters counts as one edit."""
    if abs(len(a) - len(b)) > 1:
        return 2
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def check_package(eco, name):
    """Return (action, reason) or None when the package looks fine or can't be checked."""
    concerns = []
    try:
        if eco == "npm":
            meta = fetch_json("https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@"))
            created = (meta.get("time") or {}).get("created", "")
            try:
                dl = fetch_json("https://api.npmjs.org/downloads/point/last-week/" + urllib.parse.quote(name, safe="@"))
                if dl.get("downloads", 0) < 1000:
                    concerns.append(f"{dl.get('downloads', 0)} downloads na última semana")
            except Exception:  # noqa: BLE001
                pass
        elif eco == "pypi":
            meta = fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
            uploads = [f.get("upload_time_iso_8601", "") for files in meta.get("releases", {}).values() for f in files]
            created = min((u for u in uploads if u), default="")
        elif eco == "crates":
            meta = fetch_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(name)}")
            created = (meta.get("crate") or {}).get("created_at", "")
        elif eco == "rubygems":
            meta = fetch_json(f"https://rubygems.org/api/v1/gems/{urllib.parse.quote(name)}.json")
            created = ""
            if meta.get("downloads", 0) < 1000:
                concerns.append(f"{meta.get('downloads', 0)} downloads no total")
        elif eco == "packagist":
            meta = fetch_json(f"https://repo.packagist.org/p2/{urllib.parse.quote(name)}.json")
            created = ""
        elif eco == "nuget":
            fetch_json(f"https://api.nuget.org/v3-flatcontainer/{urllib.parse.quote(name.lower())}/index.json")
            created = ""
        elif eco == "go":
            # The module proxy answers 404/410 for modules that don't exist.
            fetch_json(f"https://proxy.golang.org/{urllib.parse.quote(name.lower())}/@latest")
            created = ""
        else:
            return None
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return (DENY, f"[Okeanos] o pacote `{name}` não existe em {eco}. Pode ser um nome alucinado; confira o nome certo antes de instalar.")
        return None
    except Exception:  # noqa: BLE001
        return None  # offline or registry down: don't block work
    if created:
        try:
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
            if age < 30:
                concerns.append(f"publicado há {age} dias")
        except Exception:  # noqa: BLE001
            pass
    # Compare the full name: a scoped package (@org/core) is not a typo of an
    # unscoped one (cors); its scope already says who publishes it.
    base = name.lower()
    for pop in POPULAR.get(eco, "").split():
        if base != pop and edit_distance(base, pop) == 1:
            concerns.append(f"nome a uma letra de `{pop}`")
            break
    if concerns:
        return (ASK, f"[Okeanos] confira o pacote `{name}` antes de instalar: {', '.join(concerns)}.")
    return None
