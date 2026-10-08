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
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
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

const IMPLEMENT_MODEL = "claude-sonnet-5-5";
const REVIEW_MODEL = "claude-sonnet-5-5";
const MERGE_MODEL = "claude-sonnet-5-5";

// Max tickets worked at once, and max plan→execute→merge rounds.
const PARALLEL = 3;
const MAX_ROUNDS = 10;
const PILOT_SIZE = 2;

// ---------------------------------------------------------------------------

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
      { hostPath: ".sandcastle/skills", sandboxPath: "/home/agent/.claude/skills", readonly: true },
    ],
  });

const hooks = INSTALL_COMMAND
  ? { sandbox: { onSandboxReady: [{ command: INSTALL_COMMAND, timeoutMs: 600_000 }] } }
  : {};

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
          agent: sandcastle.claudeCode(IMPLEMENT_MODEL),
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
          agent: sandcastle.claudeCode(REVIEW_MODEL),
          promptFile: "./.sandcastle/review-prompt.md",
          promptArgs: { TICKET_BODY: ticket.body, VERIFY_COMMAND },
        });
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
      agent: sandcastle.claudeCode(MERGE_MODEL),
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
