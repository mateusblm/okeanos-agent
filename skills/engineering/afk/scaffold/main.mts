// Okeanos AFK runner: implements a feature's local tickets in Docker sandboxes.
//
// Usage (from the repo root, on the integration branch):
//   .sandcastle/node_modules/.bin/tsx .sandcastle/main.mts <feature-slug> [--pilot]
//
// --pilot runs a single round on at most PILOT_SIZE tickets, so a broken
// setup (image, install, verify command, prompts) fails cheaply before the
// full fan-out.
//
// Each round:
//   1. Frontier: open tickets in .scratch/<feature>/issues/ whose blockers are
//      all done. Computed here from the ticket files, no planner agent.
//   2. Execute + review: one sandbox per frontier ticket, on its own branch.
//      The implementer drives the tdd skill; a reviewer polishes the branch.
//   3. Merge: one agent merges the finished branches into the current branch.
//      Tickets whose branch landed are marked `**Status:** done` here.
// Rounds repeat until no ticket is ready. The outcome is written to
// .scratch/<feature>/afk-report.md for Okeanos to pick up.

import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// ---------------------------------------------------------------------------
// Configuration (filled in by the afk skill at setup; edit freely)
// ---------------------------------------------------------------------------

// Runs inside each fresh sandbox before the agent starts. Empty to skip.
const INSTALL_COMMAND = "npm install";

// Typecheck + tests. The merger runs it after every merge.
const VERIFY_COMMAND = "npm test";

// Host paths copied into each ticket worktree (e.g. node_modules, .env).
const COPY_TO_WORKTREE: string[] = [];

// Coding agent that runs inside the sandboxes: "claude", "codex", "copilot"
// or "cursor". Its CLI must be installed in .sandcastle/Dockerfile and its
// token or key set in .sandcastle/.env.
const AGENT: string = "claude";

// Model per agent and role. Only the row for AGENT is used.
const MODELS = {
  claude: {
    implement: "claude-sonnet-5-5",
    review: "claude-sonnet-5-5",
    merge: "claude-sonnet-5-5",
    acceptance: "claude-sonnet-5-5",
  },
  codex: { implement: "gpt-5.4", review: "gpt-5.4", merge: "gpt-5.4", acceptance: "gpt-5.4" },
  copilot: {
    implement: "claude-sonnet-4.5",
    review: "claude-sonnet-4.5",
    merge: "claude-sonnet-4.5",
    acceptance: "claude-sonnet-4.5",
  },
  cursor: { implement: "composer-2", review: "composer-2", merge: "composer-2", acceptance: "composer-2" },
};

// Max tickets worked at once, and max plan→execute→merge rounds.
const PARALLEL = 3;
const MAX_ROUNDS = 10;
const PILOT_SIZE = 2;

// Hidden acceptance tests: before implementing, a separate agent writes tests
// from the ticket's acceptance criteria only. They are stored outside the repo
// and applied after the implementer and reviewer finish, so the implementer
// can't see or bend them. Doubles agent runs per ticket; worth it for
// critical features. The spec must name the interfaces (seams) to test.
const HIDDEN_ACCEPTANCE = false;

// ---------------------------------------------------------------------------

// Sandcastle agent factory per agent, and where that agent reads user skills.
type AgentName = keyof typeof MODELS;
type Role = keyof (typeof MODELS)[AgentName];
const AGENTS: Record<AgentName, { factory: (model: string) => sandcastle.AgentProvider; skillsDir: string }> = {
  claude: { factory: sandcastle.claudeCode, skillsDir: "/home/agent/.claude/skills" },
  codex: { factory: sandcastle.codex, skillsDir: "/home/agent/.agents/skills" },
  copilot: { factory: sandcastle.copilot, skillsDir: "/home/agent/.agents/skills" },
  cursor: { factory: sandcastle.cursor, skillsDir: "/home/agent/.agents/skills" },
};

const isAgentName = (name: string): name is AgentName => Object.hasOwn(AGENTS, name);
if (!isAgentName(AGENT)) {
  console.error(
    `Unsupported AGENT "${AGENT}" in .sandcastle/main.mts. Supported: ${Object.keys(AGENTS).join(", ")}.`,
  );
  process.exit(1);
}
const agentName: AgentName = AGENT;
const agentFor = (role: Role) => AGENTS[agentName].factory(MODELS[agentName][role]);

const DONE = new Set(["done", "resolved", "closed"]);

type Ticket = {
  id: string;
  title: string;
  status: string;
  blockedBy: string[];
  path: string;
  body: string;
};

const feature = process.argv[2];
const pilot = process.argv.includes("--pilot");
if (!feature) {
  console.error("Usage: tsx .sandcastle/main.mts <feature-slug> [--pilot]");
  process.exit(1);
}

const featureDir = join(".scratch", feature);
const issuesDir = join(featureDir, "issues");
if (!existsSync(issuesDir)) {
  console.error(`No tickets found at ${issuesDir}`);
  process.exit(1);
}

const git = (...args: string[]) =>
  execFileSync("git", args, { encoding: "utf8" }).trim();

const currentBranch = git("rev-parse", "--abbrev-ref", "HEAD");
if (["main", "master", "develop"].includes(currentBranch)) {
  console.error(
    `Refusing to run on ${currentBranch}. Check out an integration branch first.`,
  );
  process.exit(1);
}

const matchLine = (body: string, label: string) =>
  body.match(new RegExp(`^(?:\\*\\*)?${label}:(?:\\*\\*)?[ \\t]*(.*)$`, "mi"))?.[1]?.trim() ?? "";

function readTickets(): Ticket[] {
  return readdirSync(issuesDir)
    .filter((f) => /^\d+-.*\.md$/.test(f))
    .sort()
    .map((file) => {
      const path = join(issuesDir, file);
      const body = readFileSync(path, "utf8");
      const id = file.match(/^(\d+)/)![1]!.padStart(2, "0");
      const title =
        body.match(/^#\s+\d+:\s*(.+)$/m)?.[1]?.trim() ?? file.replace(/\.md$/, "");
      const blockedLine = matchLine(body, "Blocked by");
      const blockedBy = /^none/i.test(blockedLine)
        ? []
        : [...blockedLine.matchAll(/\b(\d{1,3})\b/g)].map((m) => m[1]!.padStart(2, "0"));
      const status = matchLine(body, "Status").toLowerCase();
      return { id, title, status, blockedBy, path, body };
    });
}

function markDone(ticket: Ticket, branch: string) {
  let body = readFileSync(ticket.path, "utf8");
  body = body.replace(
    /^((?:\*\*)?Status:(?:\*\*)?[ \t]*).*$/m,
    (_, prefix: string) => `${prefix}done`,
  );
  if (!/^## Comments$/m.test(body)) body = `${body.trimEnd()}\n\n## Comments\n`;
  body = `${body.trimEnd()}\n\n- Implemented AFK by Okeanos on \`${branch}\`, merged into \`${currentBranch}\`.\n`;
  writeFileSync(ticket.path, body);
}

const isMerged = (branch: string) => {
  try {
    git("merge-base", "--is-ancestor", branch, "HEAD");
    return true;
  } catch {
    return false;
  }
};

const specPath = join(featureDir, "spec.md");
const spec = existsSync(specPath) ? readFileSync(specPath, "utf8") : "(no spec file)";

const sandbox = () =>
  docker({
    // Okeanos skills (tdd, codebase-design) available to the agent in the sandbox.
    mounts: [
      { hostPath: ".sandcastle/skills", sandboxPath: AGENTS[agentName].skillsDir, readonly: true },
    ],
  });

const hooks = INSTALL_COMMAND
  ? { sandbox: { onSandboxReady: [{ command: INSTALL_COMMAND, timeoutMs: 600_000 }] } }
  : {};

// Writes acceptance tests on a throwaway branch, returns them as a patch kept
// outside the repo, and deletes the branch so no worktree can reach it.
async function writeHiddenAcceptance(ticket: Ticket): Promise<string> {
  const accBranch = `okeanos/acc-${feature}-${ticket.id}`;
  const box = await sandcastle.createSandbox({
    branch: accBranch,
    sandbox: sandbox(),
    hooks,
    copyToWorktree: COPY_TO_WORKTREE,
  });
  try {
    const run = await box.run({
      name: `acceptance-${ticket.id}`,
      maxIterations: 5,
      agent: agentFor("acceptance"),
      promptFile: "./.sandcastle/acceptance-prompt.md",
      promptArgs: { TICKET_ID: ticket.id, TICKET_BODY: ticket.body, SPEC: spec },
    });
    if (run.commits.length === 0) throw new Error("acceptance agent wrote no tests");
  } finally {
    await box.close();
  }
  const patch = git("diff", `${currentBranch}...${accBranch}`);
  git("branch", "-D", accBranch);
  if (!patch) throw new Error("acceptance agent produced an empty diff");
  const file = join(mkdtempSync(join(tmpdir(), "okeanos-acc-")), `${ticket.id}.patch`);
  writeFileSync(file, `${patch}\n`);
  return file;
}

const done: string[] = [];
const failed = new Map<string, string>();

const rounds = pilot ? 1 : MAX_ROUNDS;
const width = pilot ? Math.min(PILOT_SIZE, PARALLEL) : PARALLEL;

for (let round = 1; round <= rounds; round++) {
  const tickets = readTickets();
  const doneIds = new Set(tickets.filter((t) => DONE.has(t.status)).map((t) => t.id));
  const frontier = tickets
    .filter((t) => !DONE.has(t.status) && !failed.has(t.id))
    .filter((t) => t.blockedBy.every((b) => doneIds.has(b)))
    .slice(0, width);

  if (frontier.length === 0) break;

  console.log(`\n=== Round ${round}: ${frontier.map((t) => t.id).join(", ")} ===\n`);

  const settled = await Promise.allSettled(
    frontier.map(async (ticket) => {
      const branch = `okeanos/afk-${feature}-${ticket.id}`;
      const acceptancePatch = HIDDEN_ACCEPTANCE ? await writeHiddenAcceptance(ticket) : null;
      const box = await sandcastle.createSandbox({
        branch,
        sandbox: sandbox(),
        hooks,
        copyToWorktree: COPY_TO_WORKTREE,
      });
      try {
        const implement = await box.run({
          name: `implement-${ticket.id}`,
          maxIterations: 20,
          agent: agentFor("implement"),
          promptFile: "./.sandcastle/implement-prompt.md",
          promptArgs: {
            TICKET_ID: ticket.id,
            TICKET_TITLE: ticket.title,
            TICKET_BODY: ticket.body,
            SPEC: spec,
            VERIFY_COMMAND,
          },
        });
        if (implement.commits.length === 0) throw new Error("no commits produced");
        await box.run({
          name: `review-${ticket.id}`,
          maxIterations: 1,
          agent: agentFor("review"),
          promptFile: "./.sandcastle/review-prompt.md",
          promptArgs: { TICKET_BODY: ticket.body, VERIFY_COMMAND },
        });
        if (acceptancePatch) {
          const apply = await box.exec("git apply --index -", { stdin: readFileSync(acceptancePatch, "utf8") });
          if (apply.exitCode !== 0) throw new Error(`hidden acceptance tests did not apply: ${apply.stderr.slice(-300)}`);
          await box.exec(`git commit -m "test: hidden acceptance tests for ticket ${ticket.id}"`);
          const verify = await box.exec(VERIFY_COMMAND);
          if (verify.exitCode !== 0) {
            const out = `${verify.stdout}\n${verify.stderr}`.trim().split("\n").slice(-15).join(" | ");
            throw new Error(`hidden acceptance tests failed: ${out.slice(-500)}`);
          }
        }
        return branch;
      } finally {
        await box.close();
      }
    }),
  );

  const finished: { ticket: Ticket; branch: string }[] = [];
  settled.forEach((outcome, i) => {
    const ticket = frontier[i]!;
    if (outcome.status === "fulfilled") finished.push({ ticket, branch: outcome.value });
    else failed.set(ticket.id, String(outcome.reason));
  });

  if (finished.length > 0) {
    await sandcastle.run({
      name: "merge",
      maxIterations: 1,
      sandbox: sandbox(),
      hooks,
      agent: agentFor("merge"),
      promptFile: "./.sandcastle/merge-prompt.md",
      promptArgs: {
        BRANCHES: finished.map((f) => `- ${f.branch}`).join("\n"),
        VERIFY_COMMAND,
      },
    });
  }

  for (const { ticket, branch } of finished) {
    if (isMerged(branch)) {
      markDone(ticket, branch);
      done.push(`${ticket.id}: ${ticket.title} (${branch})`);
    } else {
      failed.set(ticket.id, `branch ${branch} did not merge cleanly`);
    }
  }
}

const remaining = readTickets().filter((t) => !DONE.has(t.status));
const report = `# AFK report: ${feature}${pilot ? " (pilot)" : ""}

Integration branch: \`${currentBranch}\`

## Done

${done.map((d) => `- ${d}`).join("\n") || "- (none)"}

## Failed

${[...failed].map(([id, why]) => `- ${id}: ${why}`).join("\n") || "- (none)"}

## Still open

${remaining.map((t) => `- ${t.id}: ${t.title} (blocked by: ${t.blockedBy.join(", ") || "none"})`).join("\n") || "- (none)"}
`;
writeFileSync(join(featureDir, "afk-report.md"), report);
console.log(`\n${report}`);
