# Performance patterns

The usual bottlenecks, each with its signature and the rule for fixing it. Open the section for the layer step 2 pointed at; this is not a list to apply wholesale. Every fix here is still a hypothesis until step 4 re-measures it.

## Where to start

| What is slow | Measure first |
| :- | :- |
| One endpoint | its queries (count and plan), then time spent outside the database |
| Every endpoint at once | connection pool waits, CPU, memory, an external dependency |
| Intermittent | lock contention, GC pauses, retries and timeouts on external calls |
| First page load | server response time, bundle size, render-blocking resources, the LCP element |
| Interaction feels sluggish | long tasks (> 50 ms) on the main thread, re-renders, layout thrashing |
| After navigation | API waterfalls (sequential requests), client render time |

## Backend

- **N+1 queries.** Signature: query count grows with the number of rows; the log shows the same query with different ids. Fetch the relation in the same query (join, include, batch load by id list). Protect with a test that asserts the query count.
- **Read the plan before adding an index.** "Add an index" is the guess; `EXPLAIN ANALYZE` (or the database's equivalent) is the measurement. Capture it before the change. A sequential scan where you expected an index, an estimated row count off by an order of magnitude (stale statistics: refresh them, don't add an index), or a sort node above the scan each call for a different fix. Index for the query's shape: equality columns first, then the range or sort column. A plain index won't serve a leading wildcard (needs trigram or full-text), a function on the column (index the expression), or the dominant value of a low-selectivity column (a partial index serves the rare one). Every index taxes every write. Re-run the plan after: an index that didn't change it is a revert.
- **Connection pool exhaustion.** Signature: every endpoint slows at once, time goes to waiting for a connection, the database shows mostly idle sessions. One pool per process; `instances × pool max` stays under the database's connection limit; set an acquire timeout so exhaustion fails fast. Find what holds connections (long transactions, a missing `await`, leaked clients) before resizing: a bigger pool only moves the queue into the database. With unbounded instance counts (serverless, autoscaling), put a multiplexing proxy in front instead of raising the pool.
- **Caching.** Cache only what is expensive to produce (measured) and read far more often than it changes; caching a fast call adds a hop and a staleness bug. Rules:
  - The key holds **every input the response depends on**: tenant, viewer, locale, permissions, feature flags. A key without the viewer serves one user's data to another.
  - Write down the **staleness window** and pick one invalidation strategy (TTL, event or tag, versioned keys).
  - Never cache what must be fresh: balances, permissions, stock at checkout.
  - Guard hot keys against the stampede (coalesce concurrent misses behind one in-flight load, or serve stale while one request refreshes).
  - Bound it (eviction policy, memory ceiling) and watch the hit rate; never cache an origin error.
- **Unbounded queries.** Signature: a list endpoint or job reads the whole table; memory and latency grow with data. Bound every read with a limit (for a public list, pagination as `API.md` in the `okeanos-codebase-design` skill decides it); select only the columns used.
- **Heavy synchronous work on the hot path.** Signature: CPU spikes on request, latency tracks payload size, one slow request blocks others. Move it off the request (queue, background job, precompute), stream instead of buffering, batch external calls instead of looping one per item, run independent calls concurrently, and put a timeout on every external call.
- **Memory growth.** Signature: memory climbs across requests and doesn't return. Take heap snapshots at two points and diff them; usual causes are unbounded caches or maps, listeners never removed, and payloads held longer than the request.

## Frontend

Identify the framework and rendering model first; don't recommend an idiom from a stack the project doesn't use.

- **Core Web Vitals.** Targets at p75: LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1. Lab runs (a local audit, a trace) are reproducible and catch regressions; field data (real users) says whether users felt it. Report which one a number is.
- **LCP.** Find the LCP element. If it's an image: not lazy-loaded, high fetch priority, preloaded if discovered late, correctly sized. Check server response time and render-blocking CSS and scripts (`defer`/`async`).
- **INP.** Break long tasks up and yield to the browser inside long loops; move non-urgent work (analytics, logging) out of event handlers; virtualise long lists; avoid reading and writing layout in a loop. Memoise only what the profiler shows is expensive: memoising everything is its own cost.
- **CLS.** Every image, video, iframe and embed declares `width` and `height` (or an aspect ratio); reserve space for late content; use `font-display: swap` with matched fallback metrics.
- **Images.** Modern formats (AVIF, WebP), `srcset`/`sizes` for resolution, `loading="lazy"` and `decoding="async"` below the fold, never on the LCP image.
- **Code splitting.** Split by route and lazy-load heavy, rarely used features. Modern bundlers already tree-shake named ESM imports; check the bundle analyser before rewriting imports. Load heavy third-party scripts late or behind a facade.
- **Bundle budget.** If the project has a budget (initial JS, CSS, per-image size), measure the built output before and after and report the growth in KB gzipped. A budget the build doesn't check is a wish: make it a build or test step.

## Benchmark checklist

Answer each with evidence from a run before reporting or acting on a number. For a quick ballpark the user asked for, one run is enough, but still check 4 and 7 and say it was one run. A choice between options is never a ballpark.

Before running: write the claim down, read the measurement script (what it times, counts and ignores), and check the machine load and core count. If something else is running and can't be stopped, alternate the sides so both see the same noise, and say so.

1. **Why not double?** Name the limiter from a profile or system counters (CPU per process, I/O wait, syscalls), then map it to source. If the load generator saturates first, you measured the load generator.
2. **Was it tuned?** Every side runs as production does: release build, production flags, pools, batching, cache warmth, same versions and data. A side on defaults compares configurations, not implementations. Don't pick a winner from an untuned run.
3. **Did it break limits?** Do the arithmetic against disk and network bandwidth and available cores. Removing a piece that takes 10% of the run makes it at most ~11% faster. A result past a limit measured something else: a cache, a no-op, a bug.
4. **Did it error?** Count failures and non-success responses, and check outputs are correct, not just present. Rejections are fast, timeouts slow; both distort. If the script doesn't count errors, add the count.
5. **Does it reproduce?** At least 5 runs per side, alternating sides (A, B, A, B) so warmup and drift don't favour one. Report median and range; a gap inside the run-to-run range is no measurable difference.
6. **Does it matter?** Next to a micro result, measure the end-to-end path with realistic data and concurrency, and report the micro result as a share of it.
7. **Did it even happen?** Confirm the work ran inside the timed region: the request reached the server, the rows were written, the result was used. Lazy code (an un-iterated generator, an un-awaited promise, a result the compiler discards) and timeouts produce numbers for work that never happened.
