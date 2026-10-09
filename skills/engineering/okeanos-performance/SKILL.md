---
name: okeanos-performance
description: Measure-first performance work - baseline, find the real bottleneck, change one thing, keep it only if it beats the noise, then protect it. Use when something is slow, a performance regression shows up, a performance budget (bundle size, LCP, p95 latency) is at stake, or the user asks to optimise or speed something up.
metadata:
  credits:
    - skill: performance-optimization, web-performance-auditor
      author: Addy Osmani
      license: MIT
      url: "https://github.com/addyosmani/agent-skills"
    - skill: benchmark-checklist, principle-explain-the-number, perf-issue
      author: Lauren Tan
      license: MIT
      url: "https://github.com/cursor/plugins/tree/main/pstack"
---

# Performance

Performance work without a measurement is guessing, and guessing adds complexity that buys nothing. Every step below runs on numbers you took, not on reading code.

```
measure → identify → fix → verify → protect
```

Don't start without evidence of a problem: a report, a failing budget, a regression between two known states, or a target in the spec. "This looks slow" in code review is a potential impact, not a reason to optimise.

## Metric honesty

**No tool, no real measurement → no number.** Reading source cannot tell you LCP, p95 or throughput. Without a run:

- report source-level findings only, each labelled **potential impact**;
- say "not measured" wherever a number would go;
- never estimate a gain ("should be ~30% faster").

When you do have data, name its source with the number: lab run, field data (real users), profiler trace, benchmark script. Lab and field numbers are not interchangeable. A made-up number is worse than no number.

## 1. Measure

Write down the claim you expect to make, in the words you would ship ("export is 30% faster at p50 on the 60k-row dataset"). Then build the **baseline**:

- **One command** that produces the number: a benchmark script, a timing harness, a load test, a lab audit of the page, `EXPLAIN ANALYZE` for a query. Show the invocation and its output.
- **Fixed conditions**: same data size, same build (release, production flags), same cache state (warm or cold, as production sees it), same machine load, same budget (runs, requests, or wall-clock). Write them next to the command.
- **Repeat** it, at least 5 runs, and record the median and the range. The range is the noise every later change must beat.

Measure the path the user waits on, not only the function you suspect. A helper that takes 1% of a request can make it at most 1% faster.

## 2. Identify

Find the bottleneck from the measurement, not from the code. Profile in a run you don't report (profilers slow the work down), then map the hot spot to source.

Ask **"why not twice as fast?"** and name the limiter: a core, a lock, the disk, the network, a query, the connection pool, the main thread, the load generator itself. A guess from reading code is not a limiter.

[PATTERNS.md](PATTERNS.md) lists the usual suspects, backend and frontend, with the signature of each. Open it once you know which layer is slow.

## 3. Fix

Fix the one thing step 2 named. Try the cheapest kind of fix first, and stop when one meets the target:

1. Don't do it (stop work whose result nothing uses).
2. Don't do it again (cache or reuse; see PATTERNS.md for the cache rules).
3. Do less of it (batch, paginate, narrow the query).
4. Do it later or off the hot path (defer, queue, lazy-load).
5. Do it concurrently.
6. Do it cheaper (better algorithm, index, smaller payload).

**One change at a time.** Three optimisations measured together give one number you can't attribute. If they must ship together, measure each alone first.

**Correctness gates the metric.** A "win" that skips a validation, caches what must be fresh, drops an `await`, or needs a test changed or deleted is a regression.

## 4. Verify: keep or revert

Re-measure with **the same command and the same conditions** as the baseline. A cold-cache baseline against a warm-cache result measures the cache, not your change.

| Result vs. baseline | Action |
| :- | :- |
| Better by more than the measured range, tests green | **Keep.** |
| Inside the noise | **Revert.** |
| Worse | **Revert.** |
| Better, but a test went red | **Revert.** |

**Neutral is a revert.** The change is written, so keeping it feels free; it isn't. Code you keep, you maintain. If a change didn't move the number, the limiter usually explains why: go back to step 2 before calling the idea useless.

Before trusting any number, run the checklist at the end of [PATTERNS.md](PATTERNS.md): did it error, did the work actually happen, does it break a physical limit, was every side tuned.

### Log every attempt

Reverted work leaves no trace in git, which is why the same dead idea gets tried again. Keep a short table, kept and reverted alike, in the PR body (use the `okeanos-pr` skill) or, before publishing, in the publish-gate summary:

| Idea | Baseline → result | Verdict | Why |
| :- | :- | :- | :- |
| Memoise the row component | INP 240 ms → 235 ms | reverted | inside noise (±15 ms); rows weren't the limiter |
| Virtualise the list | INP 240 ms → 90 ms | kept | long tasks gone from the trace |

## 5. Protect

Guard the metric that justified the fix, not every number available:

- **Cheap and deterministic** (bundle size, query count, allocation count, a fixed-input benchmark with a generous threshold): turn it into a test, or propose a budget check for the `onDone` list in `docs/agents/checks.json` so the hooks run it before every stop. Adding a check is free; removing or loosening one needs the user's approval.
- **Noisy or slow** (latency, page-load metrics): a CI step that compares a median over repeated runs, or field monitoring with an alert on a meaningful p75 move. Don't add a flaky gate.
- **Nothing cheap fits**: say so in the report, and name what would detect a regression.

When a guard fires, go back to step 1 with a fresh baseline.

## Report

Lead with the verdict: faster, slower, no measurable difference, or inconclusive. Then, for each number:

- **number with its unit**, before → after;
- **run count** per side;
- **range** (spread across runs);
- **limiting factor** (what bounds the result now).

> p50 41 ms → 33 ms, median of 7 runs per side, range 32-35 ms after, bound by JSON parsing on one core.

Call it **inconclusive** when you can't name the limiter, a side ran untuned, or you couldn't confirm the work ran without errors. Name the gap. Keep the PR body to one primary number plus the attempt log.

## Done when

- [ ] Baseline and result came from the same command under the same conditions, both shown.
- [ ] Each kept change beats the measured range; neutral changes are reverted; tests are green.
- [ ] Every attempt, reverted ones included, is in the log.
- [ ] Unmeasured findings say "potential impact" and carry no number.
- [ ] The metric has a guard (test, budget check, monitor), or the report says why not.
